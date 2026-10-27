"""Bounded source-only API discovery. No R, NAMESPACE or Rd is evaluated."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .errors import KnowledgeError
from .parsers import decode, discovery_name, parse_namespace, rd_index_record

SCHEMA_VERSION = 1
MAX_ENTRIES = 10_000
MAX_RELATIONS = 5
MAX_FUZZY_CANDIDATES = 1000
MAX_INDEX_BYTES = 8 << 20
PAGE_BYTES = 16 << 10

KINDS = ("export", "alias", "topic", "method")
COLLECTIONS = ("exports", "aliases", "documentation_topics", "methods")


def _links(values) -> dict:
    values = sorted(set(values))
    return {
        "documentation_topics": values[:MAX_RELATIONS],
        "documentation_topics_count": len(values),
        "documentation_topics_complete": len(values) <= MAX_RELATIONS,
    }


@dataclass(frozen=True)
class DiscoveryIndex:
    """Normalized source-backed entries; all backend modes share these semantics."""

    entries: tuple[dict, ...]
    namespace_status: str
    rd_status: str
    patterns: tuple[str, ...]
    issues: tuple[str, ...]
    estimated_bytes: int

    def ranked(self, query: str | None, package: str) -> tuple[list[tuple[dict, str]], bool]:
        if query is None or not query.strip():
            return [(entry, "all") for entry in self.entries], True
        needle = query.strip()
        if needle.startswith(package + "::"):
            needle = needle.split("::", 1)[1]
        needle = needle.removesuffix("()").casefold()
        exact, candidates = [], []
        for entry in self.entries:
            name = entry["name"]
            if name == query.strip():
                kind = entry["kind"]
                exact.append(
                    (entry, "alias" if kind == "alias" else "topic" if kind == "topic" else "exact")
                )
            elif name.casefold() == needle:
                exact.append((entry, "normalized"))
            else:
                candidates.append(entry)
        exact.sort(key=lambda row: (KINDS.index(row[0]["kind"]), row[0]["id"]))
        # Exact scan is exhaustive. Fuzzy work has a separate bounded deterministic shortlist.
        candidates.sort(
            key=lambda e: (
                needle not in e["name"].casefold(),
                not e["name"].casefold().startswith(needle[:3]),
                abs(len(e["name"]) - len(needle)),
                e["id"],
            )
        )
        complete = len(candidates) <= MAX_FUZZY_CANDIDATES
        fuzzy = []
        for entry in candidates[:MAX_FUZZY_CANDIDATES]:
            score = SequenceMatcher(None, needle, entry["name"].casefold(), autojunk=False).ratio()
            if score >= 0.55 or (len(needle) >= 3 and needle in entry["name"].casefold()):
                fuzzy.append((-score, entry["id"], entry))
        fuzzy.sort(key=lambda row: (row[0], row[1]))
        return exact + [(row[2], "fuzzy") for row in fuzzy], complete

    def page(self, package: str, query: str | None, limit: int, offset: int) -> dict:
        ranked, fuzzy_complete = self.ranked(query, package)
        if offset > len(ranked):
            raise KnowledgeError("invalid_input", "Offset exceeds matching entry count")
        output = {
            "schema_version": SCHEMA_VERSION,
            "query": query,
            "offset": offset,
            "exports": [],
            "aliases": [],
            "documentation_topics": [],
            "methods": [],
            "matches": [],
            "next_offset": None,
            "callability": "not_checked",
            "coverage": {
                "namespace": self.namespace_status,
                "rd": self.rd_status,
                "scope": "literal Rd and static namespace declarations; runtime not checked",
                "fuzzy_search_complete": fuzzy_complete,
            },
            "export_patterns": list(self.patterns[:20]),
            "export_patterns_count": len(self.patterns),
            "export_patterns_complete": len(self.patterns) <= 20,
            "issues": list(self.issues[:20]),
            "pagination_scope": "one ordered entity stream; arrays project the same page",
            "collections": {},
        }
        for kind, collection in zip(KINDS, COLLECTIONS, strict=True):
            output["collections"][collection] = {
                "total": sum(e["kind"] == kind for e in self.entries),
                "matched": sum(e["kind"] == kind for e, _ in ranked),
                "returned": 0,
                "page_complete": False,
                "source_status": self.namespace_status
                if kind in {"export", "method"}
                else self.rd_status,
            }
        returned = 0
        for entry, match_type in ranked[offset : offset + limit]:
            collection = COLLECTIONS[KINDS.index(entry["kind"])]
            match = {
                "id": entry["id"],
                "name": entry["name"],
                "kind": entry["kind"],
                "match_type": match_type,
                "relationship_verified": match_type in {"exact", "alias", "topic", "all"},
            }
            output[collection].append(entry)
            output["matches"].append(match)
            if len(json.dumps(output, ensure_ascii=False).encode()) > PAGE_BYTES:
                output[collection].pop()
                output["matches"].pop()
                if not returned:
                    raise KnowledgeError("response_too_large", "Discovery entry exceeds page limit")
                break
            returned += 1
        output["next_offset"] = offset + returned if offset + returned < len(ranked) else None
        output["total_matches"] = len(ranked)
        output["returned"] = returned
        for collection in COLLECTIONS:
            counts = output["collections"][collection]
            counts["returned"] = len(output[collection])
            counts["page_complete"] = (
                offset == 0
                and output["next_offset"] is None
                and counts["returned"] == counts["matched"]
            )
        return output

    def suggestions(self, query: str, package: str) -> list[dict]:
        ranked, _ = self.ranked(query, package)
        exports = {e["name"]: e for e in self.entries if e["kind"] == "export"}
        output = []
        for entry, match in ranked:
            if entry["kind"] != "alias":
                continue
            output.append(
                {
                    "name": entry["name"],
                    "match_type": match,
                    "alias_verified": True,
                    "export_status": "declared" if entry["name"] in exports else "unknown",
                    "documentation_topics": entry["documentation_topics"],
                    "documentation_topics_count": entry["documentation_topics_count"],
                    "callability": "not_checked",
                }
            )
            if len(output) == 3:
                break
        return output


def build_discovery_index(package: str, metadata: dict, files: dict[str, bytes]) -> DiscoveryIndex:
    encoding = metadata.get("Encoding", "UTF-8")
    issues = []
    try:
        source = files.get(f"{package}/NAMESPACE")
        namespace = parse_namespace(decode(source, encoding) if source is not None else None)
    except KnowledgeError as exc:
        if exc.code == "source_too_large":
            raise
        namespace = parse_namespace(None)
        namespace["issues"] = ["namespace_encoding_unavailable"]
    issues.extend(namespace["issues"])
    topics, alias_topics = [], {}
    rd_status = "verified"
    relation_count = 0
    for member, body in sorted(files.items()):
        if not member.endswith(".Rd"):
            continue
        if len(member) > 512:
            rd_status = "partial"
            issues.append("rd_member_name_too_long")
            continue
        try:
            text = decode(body, encoding)
        except KnowledgeError:
            rd_status = "partial"
            issues.append("rd_encoding_unavailable")
            continue
        topic, good, complete, identifier_source = rd_index_record(member, text)
        if not complete:
            rd_status = "partial"
            issues.append("rd_literal_coverage_partial")
        if not discovery_name(topic):
            issues.append("rd_topic_name_unavailable")
            continue
        relation_count += len(good)
        if relation_count > 20_000:
            raise KnowledgeError("source_too_large", "Too many Rd alias relations")
        topics.append(
            {
                "id": "topic:" + member,
                "kind": "topic",
                "name": topic,
                "archive_member": member,
                "identifier_source": identifier_source,
                "aliases": good[:MAX_RELATIONS],
                "alias_count": len(good),
                "aliases_complete": len(good) <= MAX_RELATIONS,
                "verification_status": "verified" if complete else "partial",
                "callability": "not_checked",
            }
        )
        for name in good:
            alias_topics.setdefault(name, []).append(member)
    exports = {}
    for declaration in namespace["exports"]:
        name = declaration["name"]
        if name not in exports:
            exports[name] = {
                "id": "export:" + name,
                "kind": "export",
                "name": name,
                "declaration_kinds": [],
                "evidence": [],
                "possible_reexport_from": [],
                "callability": "not_checked",
                "verification_status": "verified",
                **_links(alias_topics.get(name, [])),
            }
        entry = exports[name]
        if declaration["declaration_kind"] not in entry["declaration_kinds"]:
            entry["declaration_kinds"].append(declaration["declaration_kind"])
        if len(entry["evidence"]) < MAX_RELATIONS:
            entry["evidence"].append(declaration["evidence"])
    for name, entry in exports.items():
        origins = sorted({i["package"] for i in namespace["imports"] if i["name"] == name})
        entry["possible_reexport_from"] = origins[:MAX_RELATIONS]
        entry["reexport_status"] = "possible" if origins else "not_established"
    alias_entries = [
        {
            "id": "alias:" + name,
            "kind": "alias",
            "name": name,
            "verification_status": "verified",
            "alias_verified": True,
            "export_status": "declared" if name in exports else "unknown",
            "callability": "not_checked",
            **_links(members),
        }
        for name, members in sorted(alias_topics.items())
    ]
    methods = {}
    for method in namespace["methods"]:
        method_identity = [method[k] for k in ("method_kind", "name", "generic", "class")]
        key = (
            "method:"
            + hashlib.sha256(json.dumps(method_identity, ensure_ascii=False).encode()).hexdigest()
        )
        methods.setdefault(
            key,
            {
                **method,
                "id": key,
                "kind": "method",
                "verification_status": "verified",
                **_links(alias_topics.get(method["name"], [])),
            },
        )
    entries = tuple(
        sorted(
            [*exports.values(), *alias_entries, *topics, *methods.values()],
            key=lambda entry: (entry["name"].casefold(), entry["name"], entry["kind"], entry["id"]),
        )
    )
    if len(entries) > MAX_ENTRIES:
        raise KnowledgeError("source_too_large", "Discovery index exceeds 10000 entries")
    estimated = len(json.dumps(entries, ensure_ascii=False).encode())
    if estimated > MAX_INDEX_BYTES:
        raise KnowledgeError("source_too_large", "Discovery index exceeds 8 MiB")
    return DiscoveryIndex(
        entries,
        namespace["status"],
        rd_status,
        tuple(namespace["patterns"]),
        tuple(sorted(set(issues))),
        estimated,
    )


def snapshot_id(identity: dict, archive_digest: str, query: str | None) -> str:
    payload = [SCHEMA_VERSION, identity, archive_digest, (query or "").strip()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_request(query, limit, offset, snapshot):
    if query is not None and (
        not isinstance(query, str)
        or len(query) > 200
        or not query.isprintable()
        or not query.strip()
    ):
        raise KnowledgeError("invalid_input", "query must be printable text, 1..200 characters")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise KnowledgeError("invalid_input", "limit must be an integer in 1..50")
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise KnowledgeError("invalid_input", "offset must be an integer in 0..100000")
    if snapshot is not None and (
        not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot)
    ):
        raise KnowledgeError("invalid_input", "snapshot must be the returned SHA256 token")
    if offset and snapshot is None:
        raise KnowledgeError("invalid_input", "Continuation pages require the returned snapshot")
