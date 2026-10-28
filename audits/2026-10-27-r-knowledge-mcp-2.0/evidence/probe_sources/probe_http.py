import asyncio, json, socket, threading, time, sys
import httpx, uvicorn
from cran_knowledge_mcp.server import create_http_app

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

INIT = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"a","version":"0"}}}
H = {"Content-Type":"application/json","Accept":"application/json, text/event-stream"}

def run(allowed=None, label=""):
    port = free_port()
    app = create_http_app(allowed)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(cfg); t = threading.Thread(target=srv.run, daemon=True); t.start()
    for _ in range(100):
        try: socket.create_connection(("127.0.0.1", port), 0.1).close(); break
        except OSError: time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    print(f"== {label} allowed_hosts={allowed}")
    def post(headers=None, body=INIT, path="/mcp", **kw):
        r = httpx.post(base+path, json=body, headers={**H, **(headers or {})}, timeout=20, **kw)
        return r.status_code, r.text[:140].replace("\n"," ")
    print(" default Host:", post())
    print(" Host evil.example:", post({"Host":"evil.example"}))
    print(" Host 127.0.0.1.evil.example:", post({"Host":"127.0.0.1.evil.example"}))
    print(" Origin http://evil.example:", post({"Origin":"http://evil.example"}))
    print(" Origin http://localhost:1234:", post({"Origin":"http://localhost:1234"}))
    print(" Origin http://localhost.evil.example:", post({"Origin":"http://localhost.evil.example"}))
    print(" Origin null:", post({"Origin":"null"}))
    print(" no Authorization header accepted (no auth layer):", post()[0] == 200)
    try:
        with httpx.stream("GET", base+"/mcp", headers=H, timeout=httpx.Timeout(3.0)) as r:
            print(" GET /mcp status", r.status_code, r.headers.get("content-type"))
            try:
                n = 0
                for _ in r.iter_raw(): n += 1
                print("  stream ended")
            except Exception as e: print("  GET stream still open after 3s read timeout:", type(e).__name__)
    except Exception as e: print(" GET exc", type(e).__name__)
    r = httpx.options(base+"/mcp", headers={"Origin":"http://localhost:1","Access-Control-Request-Method":"POST"}); print(" OPTIONS preflight:", r.status_code, dict((k,v) for k,v in r.headers.items() if k.startswith("access-control")))
    # large body
    big = {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_package","arguments":{"package":"x"*(20<<20)}}}
    t0 = time.time(); print(" 20 MiB body:", post(body=big), f"{time.time()-t0:.1f}s")
    # deep json
    deep = "[" * 100000 + "]" * 100000
    r = httpx.post(base+"/mcp", content=deep, headers=H, timeout=20); print(" deeply nested JSON:", r.status_code, r.text[:100])
    # malformed protocol version header
    print(" bad MCP-Protocol-Version header:", post({"MCP-Protocol-Version":"1900-01-01"}, body={"jsonrpc":"2.0","id":3,"method":"tools/list"}))
    srv.should_exit = True; t.join(5)
run(None, "default")
run(["example.test"], "custom allowed host")
