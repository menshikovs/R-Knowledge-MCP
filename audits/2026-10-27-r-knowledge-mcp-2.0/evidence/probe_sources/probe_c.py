import asyncio, sys, json, os, tempfile
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
from fx import *
from cran_knowledge_mcp.prompt_intelligence.quality import validate_prompt
from cran_knowledge_mcp.providers.context7 import safe_query
from cran_knowledge_mcp.providers.r_documentation import RDocumentationProvider
from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.service import KnowledgeService
from pathlib import Path

print("== C1 structural score gaming")
good = "Objective: fit a mixed model with lme4 on sleepstudy. Deliverables: script. Constraints: R 4.4. Verification: run tests."
junk = "Objective Deliverables Constraints Verification Output expectations project context package R version unrelated nonsense words purple elephant banana"
for label, t in (("sensible", good), ("keyword salad", junk), ("one-liner", "build something"), ("wrong-task", "Fix the plumbing. Deliverables: none. Constraints: none. Verification: none. package R version")):
    r = validate_prompt(t)
    print(f"  {label:14} score={r['score']}  dims={ {k:v.get('passed', v) if isinstance(v,dict) else v for k,v in r['dimensions'].items()} }")

print("== D Context7 redaction false positives")
for q in ("How does token refresh work in httr2 OAuth?", "How do I manage a secret in httr2?", "password hashing with sodium: how to use password argument", "What is the api key argument of googleway?", "how to set apikey header in httr2 request"):
    print("  ", repr(q), "->", repr(safe_query(q)))

async def main():
    print("== F r-documentation on a fresh install (no index file)")
    d = Path(tempfile.mkdtemp()) / "none.json"
    p = RDocumentationProvider(None, d)
    r = await p.asearch("data frame", None, 5, None)
    print("  search ->", json.dumps({k: r.get(k) for k in ("verification_status","error")}, default=str)[:400])
asyncio.run(main())
