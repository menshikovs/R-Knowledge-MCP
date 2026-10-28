"""MCP usage measures derived from canonical trial telemetry (schema 1.x), stage2_validity_v1.

The levels are kept apart on purpose; none implies the next:

  available   the arm gave the agent access (configuration, not behaviour)
  listed      the server answered a tools/list request (the server's view; the agent's own tool
              discovery is not observable through the Agents SDK)
  attempted   the agent event stream shows a started MCP call
  completed   the agent event stream shows a terminal, non-error event for that call
  errored     terminal event with is_error true
  delivered   the server recorded a successful, non-failed result for the call
  used        NOT measurable here; `result_use_proxy` is a lexical proxy with stated limits

A started call without a terminal event is *attempted but never completed* (interrupted), not a
success. Client and server events are linked by order only unless a protocol-level identifier is
available from an observing proxy; the linkage status is reported, never upgraded.
"""

from __future__ import annotations

import re
from collections import Counter

CLIENT = "agent_stream"
SERVER = "mcp_server"
TERMINAL = ("mcp.tool.completed", "mcp.tool.failed")


def _dedup_by_call_id(events: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for event in events:
        cid = event.get("call_id")
        if isinstance(cid, str):
            if cid in seen:
                continue
            seen.add(cid)
        out.append(event)
    return out


def _calls(events: list[dict], source: str) -> tuple[list[dict], list[dict]]:
    started = _dedup_by_call_id(
        [e for e in events if e["event_type"] == "mcp.tool.started" and e["source"] == source]
    )
    terminal = _dedup_by_call_id(
        [e for e in events if e["event_type"] in TERMINAL and e["source"] == source]
    )
    return started, terminal


def correlate_calls(
    client_terminal: list[dict],
    server_terminal: list[dict],
    proxy_entries: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Trial-level linkage status and the per-call links.

    With `proxy_entries` (rows `{jsonrpc_id, tool}` from a proxy that saw the wire) a server call is
    `confirmed_protocol_id` only if its recorded protocol call id equals a proxy row with the same
    tool. Without a proxy, equal counts and identical tool order give `ordinal_unconfirmed`;
    anything else is `unmatched`. No call is ever promoted beyond what the evidence supports.
    """
    if not client_terminal and not server_terminal:
        return "not_applicable", []
    links: list[dict] = []
    if proxy_entries is not None:
        by_id = {str(row["jsonrpc_id"]): row for row in proxy_entries if "jsonrpc_id" in row}
        for call in server_terminal:
            pid = call.get("server_protocol_call_id")
            if pid is None:
                pid = call.get("protocol_call_id")
            row = by_id.get(str(pid)) if pid is not None else None
            ok = row is not None and row.get("tool") == call.get("tool")
            links.append(
                {"server_call": call.get("call_id"), "status": "confirmed" if ok else "unmatched"}
            )
        confirmed = bool(links) and all(link["status"] == "confirmed" for link in links)
        counts_agree = len(proxy_entries) == len(client_terminal) == len(server_terminal)
        return ("confirmed_protocol_id" if confirmed and counts_agree else "unmatched"), links
    comparable = len(client_terminal) == len(server_terminal) and [
        c.get("tool") for c in client_terminal
    ] == [s.get("tool") for s in server_terminal]
    for index, call in enumerate(server_terminal):
        links.append(
            {
                "server_call": call.get("call_id"),
                "client_call": client_terminal[index].get("call_id") if comparable else None,
                "status": "ordinal_unconfirmed" if comparable else "unmatched",
            }
        )
    return ("ordinal_unconfirmed" if comparable else "unmatched"), links


def summarize_trace(
    events: list[dict],
    *,
    available: bool,
    proxy_entries: list[dict] | None = None,
) -> dict:
    """The `mcp` object of a trial record, from one trial's events."""
    c_started, c_terminal = _calls(events, CLIENT)
    s_started, s_terminal = _calls(events, SERVER)
    discovery = [e for e in events if e["event_type"] == "mcp.discovery.completed"]
    if not available:
        listed: bool | None = False
    elif discovery:
        listed = any((e.get("list_tools_requests") or 0) > 0 for e in discovery)
    else:
        listed = None  # configured, but the server audit was not collected: unknown, not "no"
    errored = sum(1 for e in c_terminal if e.get("is_error") is True)
    completed = sum(1 for e in c_terminal if e.get("is_error") is False)
    started_ids = {e.get("call_id") for e in c_started if isinstance(e.get("call_id"), str)}
    terminal_ids = {e.get("call_id") for e in c_terminal if isinstance(e.get("call_id"), str)}
    unstarted_terminals = [
        e
        for e in c_terminal
        if not isinstance(e.get("call_id"), str) or e.get("call_id") not in started_ids
    ]
    attempted = len(c_started) + len(unstarted_terminals)
    never_completed = (
        len(started_ids - terminal_ids) if started_ids else max(len(c_started) - len(c_terminal), 0)
    )
    status, links = correlate_calls(c_terminal, s_terminal, proxy_entries)
    delivered = [
        e
        for e in s_terminal
        if e["event_type"] == "mcp.tool.completed" and e.get("is_error") is False
    ]
    docs = [e for e in s_terminal if e.get("tool") == "get_function_docs"]
    docs_ok = [e for e in docs if e.get("is_error") is False and e.get("partial") is not True]
    first = min(
        (
            e.get("monotonic_offset_ms")
            for e in c_started
            if e.get("monotonic_offset_ms") is not None
        ),
        default=None,
    )
    latency = [
        e["duration_ms"] for e in s_terminal if isinstance(e.get("duration_ms"), (int, float))
    ]
    all_client_calls = c_started + unstarted_terminals
    return {
        "available": available,
        "listed": listed,
        "attempted": attempted,
        "completed": completed,
        "errored": errored,
        "never_completed": never_completed,
        "server_calls": len(s_terminal),
        "server_started_events": len(s_started),
        "delivered": len(delivered),
        "delivered_confirmed": len(delivered) if status == "confirmed_protocol_id" else None,
        "correlation": status,
        "links": links,
        "calls_by_tool": dict(Counter(e.get("tool") for e in all_client_calls)),
        "error_codes": dict(Counter(c for e in s_terminal for c in (e.get("error_codes") or []))),
        "docs_calls": len(docs),
        "docs_success_rate": (len(docs_ok) / len(docs)) if docs else None,
        "time_to_first_call_ms": first,
        "server_latency_ms_mean": (sum(latency) / len(latency)) if latency else None,
        "client_server_count_mismatch": len(c_terminal) != len(s_terminal),
    }


IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9._]{3,}")


def result_use_proxy(result_texts: list[str], prompt_text: str, answer_text: str) -> dict:
    """Lexical proxy for "the answer reflects retrieved facts". NOT evidence of correct use.

    Counts identifier-like tokens that occur in tool results but not in the task prompt (so mere
    restatement is excluded) and reports the share that reappears in the final answer. Limits:
    a token can reappear by chance or from model memory; correct use can paraphrase and share no
    token; results were not retained in the historical runs, so this applies to new runs only.
    """
    prompt_tokens = set(IDENTIFIER.findall(prompt_text))
    novel = {t for text in result_texts for t in IDENTIFIER.findall(text)} - prompt_tokens
    if not novel:
        return {"novel_result_tokens": 0, "reappearing": 0, "share": None, "kind": "proxy"}
    answer = set(IDENTIFIER.findall(answer_text))
    hit = novel & answer
    return {
        "novel_result_tokens": len(novel),
        "reappearing": len(hit),
        "share": len(hit) / len(novel),
        "kind": "proxy",
    }
