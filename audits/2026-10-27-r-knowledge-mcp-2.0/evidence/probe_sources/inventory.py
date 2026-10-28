"""Static inventory over TRACKED files at the audited commit (ast only; nothing is imported or executed)."""
import ast
import collections
import json
import os
import subprocess
import sys

REPO = sys.argv[1]
files = subprocess.check_output(["git", "-C", REPO, "ls-files"], text=True).split("\n")
py = [f for f in files if f.endswith(".py")]
groups = collections.Counter()
loc = collections.Counter()
for f in py:
    g = "src" if f.startswith("src/") else "tests" if f.startswith("tests/") else "benchmarks" if f.startswith("benchmarks/") else "scripts" if f.startswith("scripts/") else "other"
    groups[g] += 1
    with open(os.path.join(REPO, f), encoding="utf-8") as fh:
        loc[g] += sum(1 for _ in fh)
print("python files/LOC by group:", {g: (groups[g], loc[g]) for g in groups})
other = collections.Counter(os.path.splitext(f)[1] for f in files if f and not f.endswith(".py"))
print("other tracked extensions:", other.most_common(10))

# ---- src import graph
mods = {}
for f in py:
    if f.startswith("src/cran_knowledge_mcp/"):
        name = f[len("src/"):-3].replace("/", ".")
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods[name] = f
edges = collections.defaultdict(set)
toplevel_edges = collections.defaultdict(set)


def resolve(mod, node):
    if node.level == 0:
        return node.module
    base = mod.split(".")
    is_pkg = mods[mod].endswith("__init__.py")
    pkg = base if is_pkg else base[:-1]
    up = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
    return ".".join(up + ([node.module] if node.module else []))


funcs = []
for mod, f in mods.items():
    tree = ast.parse(open(os.path.join(REPO, f), encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            targets = []
            if isinstance(node, ast.ImportFrom):
                t = resolve(mod, node)
                if t:
                    targets.append(t)
                    for a in node.names:
                        targets.append(t + "." + a.name)
            else:
                targets += [a.name for a in node.names]
            for t in targets:
                if t in mods and t != mod:
                    edges[mod].add(t)
    for node in tree.body:
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            targets = []
            if isinstance(node, ast.ImportFrom):
                t = resolve(mod, node)
                if t:
                    targets.append(t)
                    targets += [t + "." + a.name for a in node.names]
            for t in targets:
                if t in mods and t != mod:
                    toplevel_edges[mod].add(t)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node.end_lineno - node.lineno + 1, mod, node.name, node.lineno))

fan_in = collections.Counter(t for s in edges.values() for t in s)
print("modules:", len(mods))
print("fan-in top:", fan_in.most_common(8))
print("fan-out top:", sorted(((len(v), k) for k, v in edges.items()), reverse=True)[:8])


def cycles(graph):
    sys.setrecursionlimit(10000)
    index, low, stack, on, out, counter = {}, {}, [], set(), [], [0]

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in list(graph):
        if v not in index:
            strong(v)
    return out


print("import cycles (all imports incl. function-local):", cycles(edges))
print("import cycles (module top-level only):", cycles(toplevel_edges))
funcs.sort(reverse=True)
print("largest functions:", [(n, m.replace("cran_knowledge_mcp.", ""), fn, ln) for n, m, fn, ln in funcs[:12]])
json.dump({"edges": {k: sorted(v) for k, v in edges.items()}, "funcs": funcs[:40]}, open(os.path.join(sys.argv[2], "inventory_src_graph.json"), "w"), indent=1)

# ---- class sizes and function-local imports
classes = []
local_imports = collections.Counter()
for mod, f in mods.items():
    tree = ast.parse(open(os.path.join(REPO, f), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append((node.end_lineno - node.lineno + 1, mod.replace("cran_knowledge_mcp.", ""), node.name, sum(isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) for b in node.body)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    local_imports[mod.replace("cran_knowledge_mcp.", "")] += 1
classes.sort(reverse=True)
print("largest classes (lines, module, name, methods):", classes[:6])
print("function-local imports per module:", local_imports.most_common(6))

# ---- tests per area
tests = collections.Counter()
for f in py:
    if f.startswith("tests/"):
        tree = ast.parse(open(os.path.join(REPO, f), encoding="utf-8").read())
        n = sum(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name.startswith("test") for x in ast.walk(tree))
        tests[f] = n
bench_tests = sum(v for k, v in tests.items() if any(s in k for s in ("codex", "benchmark", "knowledge_pilot", "bioc_benchmark", "d_scorer", "telemetry", "baseline", "function_discovery_replay", "mcp_discovery")))
print("test functions (static count, before parametrization):", sum(tests.values()), "| benchmark/telemetry harness-related:", bench_tests)
print("assert-free tests:", end=" ")
free = []
for f in py:
    if f.startswith("tests/") and f != "tests/conftest.py":
        tree = ast.parse(open(os.path.join(REPO, f), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                has = any(isinstance(s, ast.Assert) or (isinstance(s, ast.Call) and getattr(s.func, "attr", "") in {"raises", "approx", "fail"}) or (isinstance(s, ast.Attribute) and s.attr in {"raises"}) or (isinstance(s, ast.Call) and getattr(s.func, "attr", "").startswith("assert")) for s in ast.walk(node))
                if not has:
                    free.append((f, node.name))
print(len(free), free[:8])
