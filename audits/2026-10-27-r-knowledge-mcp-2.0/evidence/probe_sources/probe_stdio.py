import json, subprocess, sys, os, time, threading
exe = sys.argv[1]
def session(versions):
    for v in versions:
        p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "LOG_LEVEL": "INFO"})
        def send(o): p.stdin.write((json.dumps(o)+"\n").encode()); p.stdin.flush()
        send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":v,"capabilities":{},"clientInfo":{"name":"audit","version":"0"}}})
        line = p.stdout.readline().decode()
        r = json.loads(line)
        print(f"  requested {v!r:14} -> {r.get('result',{}).get('protocolVersion') or r.get('error')}")
        if v == versions[0]:
            send({"jsonrpc":"2.0","method":"notifications/initialized"})
            send({"jsonrpc":"2.0","id":2,"method":"tools/list"})
            tl = json.loads(p.stdout.readline().decode())
            print("  tools/list count:", len(tl["result"]["tools"]))
            send({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_package","arguments":{"package":"bad name!"}}})
            c = json.loads(p.stdout.readline().decode()); res = c["result"]
            print("  invalid-arg call isError:", res.get("isError"), json.dumps(res.get("structuredContent",{}).get("error")))
            send({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"nonexistent","arguments":{}}})
            c = json.loads(p.stdout.readline().decode()); print("  unknown tool:", json.dumps(c.get("result",c.get("error")))[:300])
            send({"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_package","arguments":{"package":"ok","include":["bogus"]}}})
            c = json.loads(p.stdout.readline().decode()); print("  bad enum:", json.dumps(c.get("result",c.get("error")))[:300])
            send({"jsonrpc":"2.0","id":6,"method":"resources/list"}); c=json.loads(p.stdout.readline().decode()); print("  resources:", [x["uri"] for x in c["result"]["resources"]])
            send({"jsonrpc":"2.0","id":7,"method":"prompts/get","params":{"name":"csv-import","arguments":{"request":"read a csv"}}}); c=json.loads(p.stdout.readline().decode()); print("  prompts/get ok:", "result" in c, len(json.dumps(c))); 
            send({"jsonrpc":"2.0","id":8,"method":"ping"}); c=json.loads(p.stdout.readline().decode()); print("  ping:", c.get("result"))
        p.stdin.close(); time.sleep(0.3); p.terminate()
        err = p.stderr.read().decode()
        if v == versions[0]: print("  stderr lines:", len(err.splitlines()), "| sample:", err.splitlines()[:3])
session(["2025-11-25","2025-06-18","2025-03-26","2024-11-05","2099-01-01"])
