import asyncio, json, sys, os
from cran_knowledge_mcp.server import create_server
async def main(toolset):
    s = create_server(toolset=toolset)
    tools = await s.list_tools()
    out = []
    for t in tools:
        a = t.annotations
        props = (t.inputSchema or {}).get("properties", {})
        out.append(dict(name=t.name, title=t.title, desc_len=len(t.description or ""),
            ann=(a.model_dump(exclude_none=True) if a else None),
            nparams=len(props), required=(t.inputSchema or {}).get("required", []),
            has_outschema=t.outputSchema is not None,
            params_without_desc=[k for k,v in props.items() if "description" not in v],
            desc=t.description))
    res = await s.list_resources(); tmpl = await s.list_resource_templates(); pr = await s.list_prompts()
    return dict(toolset=toolset, ntools=len(out), tools=out,
        resources=[(str(r.uri), r.name) for r in res], templates=[(str(r.uriTemplate), r.name) for r in tmpl],
        prompts=[(p.name, [a.name for a in (p.arguments or [])]) for p in pr], instructions=s.instructions)
for ts in ("consolidated","legacy"):
    r = asyncio.run(main(ts))
    json.dump(r, open(os.path.join(sys.argv[1], f"tools_{ts}.json"), "w"), indent=1)
    print(ts, r["ntools"], len(r["resources"]), len(r["templates"]), len(r["prompts"]))
