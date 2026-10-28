import gzip
import io
import tarfile

import httpx


def tgz(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for n, b in files.items():
            b = b.encode() if isinstance(b, str) else b
            m = tarfile.TarInfo(n)
            m.size = len(b)
            t.addfile(m, io.BytesIO(b))
    return gzip.compress(buf.getvalue())


NL = chr(10)
BS = chr(92)


def rd(name, *aliases):
    return NL.join([BS + "name{" + name + "}", *[BS + "alias{" + a + "}" for a in aliases], BS + "title{T}", BS + "description{D}", ""])


DESC = NL.join(["Package: Ex", "Version: 2.10-1", "Title: T", "Description: D.", "License: MIT", "Encoding: UTF-8", "URL: https://github.com/own/ex", ""])
RD = rd("ex", "ex", "ex_alias")
NS = NL.join(["export(ex)", 'exportPattern("^zz")', "S3method(print, exc)", ""])
CRAN_INDEX = NL.join(["Package: Ex", "Version: 2.10-1", "License: MIT", "", "Package: Other", "Version: 1.0", "License: MIT", ""])
CATALOG = "<table><tr><td>Ex</td><td>Example tools</td></tr><tr><td>Other</td><td>Other tools</td></tr></table>"
BIOC_CFG = NL.join(['release_version: "3.22"', 'devel_version: "3.23"', "r_ver_for_bioc_ver:", '  "3.21": "4.5"', '  "3.22": "4.5"', '  "3.23": "4.6"', ""])


def make_routes():
    r = {
        "/src/contrib/PACKAGES": CRAN_INDEX.encode(),
        "/web/packages/available_packages_by_name.html": CATALOG.encode(),
        "/web/packages/Ex/DESCRIPTION": DESC.encode(),
        "/src/contrib/Ex_2.10-1.tar.gz": tgz({"Ex/DESCRIPTION": DESC, "Ex/NAMESPACE": NS, "Ex/man/ex.Rd": RD}),
        "/config.yaml": BIOC_CFG.encode(),
    }
    for cat, pk in (("bioc", "BEx"), ("data/annotation", "BAnn"), ("data/experiment", "BExp")):
        r[f"/packages/3.22/{cat}/src/contrib/PACKAGES"] = NL.join([f"Package: {pk}", "Version: 1.0.0", f"Title: Bioc {pk}", "License: MIT", ""]).encode()
    d = NL.join(["Package: BEx", "Version: 1.0.0", "Title: T", "Description: D.", "License: MIT", "Encoding: UTF-8", ""])
    r["/packages/3.22/bioc/src/contrib/BEx_1.0.0.tar.gz"] = tgz(
        {"BEx/DESCRIPTION": d, "BEx/NAMESPACE": "export(bx)" + NL, "BEx/man/bx.Rd": rd("bx", "bx")}
    )
    return r


def make_client(routes=None, calls=None):
    routes = routes if routes is not None else make_routes()

    def handler(request):
        if calls is not None:
            calls.append(str(request.url))
        p = request.url.path
        c = routes.get(p)
        if c is None and p.endswith("/PACKAGES.gz") and p[:-3] in routes:
            c = gzip.compress(routes[p[:-3]])
        return httpx.Response(404 if c is None else 200, content=c or b"")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), routes
