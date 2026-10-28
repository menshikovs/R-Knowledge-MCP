"""Bounded algorithmic-complexity probes on attacker-controlled text. Every case is wall-clock capped by input size."""
import time

from cran_knowledge_mcp.input_safety import contains_credential_like_text
from cran_knowledge_mcp.parsers import aliases, dcf, rd_index_record, _rd_complete, parse_namespace
from cran_knowledge_mcp.prompt_intelligence.intent import classify_request, detect_packages
from cran_knowledge_mcp.prompt_intelligence.quality import validate_prompt
from cran_knowledge_mcp.providers.context7 import safe_query

NL = chr(10)
BS = chr(92)


def t(label, fn):
    t0 = time.perf_counter()
    try:
        fn()
        status = "ok"
    except Exception as exc:  # noqa: BLE001
        status = type(exc).__name__ + ":" + getattr(exc, "code", "")
    print(f"{label:62} {(time.perf_counter() - t0) * 1000:10.1f} ms  {status}")


print("== DCF continuation-line growth (DESCRIPTION limit is 2 MiB = 2097152 bytes; 698000 lines is just under it)")
for lines in (5_000, 20_000, 40_000, 80_000, 350_000, 698_000):
    text = "Package: x" + NL + "Description: start" + NL + (" y" + NL) * lines
    t(f"dcf: {lines} continuation lines ({len(text)/1e6:.2f} MB)", lambda text=text: dcf(text))

print("== credential-like text detector on adversarial input (8000-char prompt cap)")
for label, s in (
    ("a_ x4000", "a_" * 4000),
    ("token x1600", "token" * 1600),
    ("api_key= + long", "api_key=" + "A" * 7900),
    ("access token then spaces", "access token" + " " * 7900),
    ("x- x 4000", "x-" * 4000),
    ("(a_a_)* x 2000", "a_a_" * 2000 + "token:"),
):
    t(f"input_safety: {label}", lambda s=s: contains_credential_like_text(s))

print("== intent / quality on 8000-char adversarial prompts")
for label, s in (("repeat 'csv '", "csv " * 2000), ("repeat 'data '", "data " * 2000), ("repeat 'sql query '", "sql query " * 800), ("repeat 'import read '", "import read " * 700)):
    t(f"classify_request: {label}", lambda s=s: classify_request(s))
    t(f"detect_packages: {label}", lambda s=s: detect_packages(s, None, "data_analysis"))
    t(f"validate_prompt: {label}", lambda s=s: validate_prompt(s))

print("== Context7 redaction on 500-char adversarial input")
for label, s in (("secret x", "secret " * 70), ("token a b", "token " + "a " * 240), ("password pass", "password " * 50)):
    t(f"safe_query: {label}", lambda s=s: safe_query(s))

print("== Rd parsing on 2 MiB attacker-controlled member")
big = 2 << 20
for label, s in (
    ("alias{ never closed", BS + "alias{" * (big // 7)),
    ("nested braces", "{" * 128 + "x" * (big - 256) + "}" * 128),
    ("backslash run", BS * big),
    ("many aliases", (BS + "alias{a}" + NL) * (big // 9)),
    ("percent comments", ("%" + "x" * 78 + NL) * (big // 80)),
):
    t(f"aliases(): {label}", lambda s=s: aliases(s))
    t(f"rd_index_record(): {label}", lambda s=s: rd_index_record("p/man/x.Rd", s))
    t(f"_rd_complete(): {label}", lambda s=s: _rd_complete(s))

print("== NAMESPACE parse on 256 KiB attacker-controlled text")
cap = 256 << 10
for label, s in (
    ("many export()", ("export(a)" + NL) * (cap // 10)),
    ("deep parens", "export(" + "(" * 20000 + ")" * 20000 + ")"),
    ("long string", "export(" + chr(34) + "a" * (cap - 20) + chr(34) + ")"),
    ("unterminated string", "export(" + chr(34) + "a" * (cap - 20)),
    ("comments", ("# " + "x" * 78 + NL) * (cap // 80)),
):
    t(f"parse_namespace: {label}", lambda s=s: parse_namespace(s))
