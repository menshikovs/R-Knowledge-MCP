"""Synthetic HTTP fixtures, deliberately unrelated to real package versions."""

import gzip
import io
import ipaddress
import os
import re
import shlex
import shutil
import socket
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP
from cran_knowledge_mcp.service import KnowledgeService


class OfflineActionBlocked(AssertionError):
    """A test attempted an external connection or a live benchmark command."""


class _WindowsTempPathFactory:
    """Create test temp paths outside the checkout with inherited Windows ACLs."""

    _retention_policy = "failed"

    def __init__(self, root: Path, temp_parent: Path) -> None:
        self._root = root.resolve()
        self._temp_parent = temp_parent.resolve()
        if self._root.is_symlink() or self._root.parent != self._temp_parent:
            raise RuntimeError("Windows pytest temp root is not a direct child of system temp")
        if not self._root.name.startswith("cran-mcp-pytest-"):
            raise RuntimeError("Refusing an unexpected Windows pytest temp root")
        self._basetemp = self._root / f"pytest-{uuid.uuid4().hex}"
        self._basetemp.mkdir()

    def getbasetemp(self) -> Path:
        return self._basetemp

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        relative = Path(basename)
        if (
            not basename
            or relative.is_absolute()
            or len(relative.parts) != 1
            or relative.parts[0] in {".", ".."}
        ):
            raise ValueError(
                f"temporary directory name must be a single relative component: {basename!r}"
            )

        if numbered:
            suffix = 0
            candidate = self._basetemp / f"{basename}{suffix}"
            while candidate.exists():
                suffix += 1
                candidate = self._basetemp / f"{basename}{suffix}"
        else:
            candidate = self._basetemp / basename
        candidate.mkdir()
        return candidate

    def cleanup_after_success(self) -> None:
        root = self._root.resolve()
        if root.parent != self._temp_parent or not root.name.startswith("cran-mcp-pytest-"):
            raise RuntimeError("Refusing to clean outside this run's unique temp root")
        try:
            shutil.rmtree(root)
        except PermissionError:
            # Some Windows tests intentionally leave an open journal handle
            # until interpreter shutdown. Keep that unique temp tree instead
            # of turning a successful test run into a session teardown error.
            pass


def pytest_configure(config):
    """Use inherited ACLs for pytest and tempfile directories on Windows."""
    if os.name != "nt":
        return

    temp_parent = Path(tempfile.gettempdir()).resolve()
    root = temp_parent / f"cran-mcp-pytest-{uuid.uuid4().hex}"
    root.mkdir()
    factory = _WindowsTempPathFactory(root, temp_parent)
    config._windows_temp_path_factory = factory
    config._windows_original_tempdir = tempfile.tempdir
    config._windows_original_mkdtemp = tempfile.mkdtemp

    def inherited_acl_mkdtemp(suffix=None, prefix=None, dir=None):
        parent = Path(dir or tempfile.gettempdir())
        if not parent.is_dir():
            raise FileNotFoundError(f"Temporary directory parent does not exist: {parent}")
        for _ in range(100):
            name = f"{prefix or 'tmp'}{uuid.uuid4().hex}{suffix or ''}"
            candidate = parent / name
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            return str(candidate)
        raise FileExistsError("Could not allocate a unique inherited-ACL temp directory")

    # tempfile.TemporaryDirectory calls tempfile.mkdtemp internally. Creating
    # directories with Path.mkdir lets Windows inherit the parent's ACL instead
    # of applying Python's restrictive mode=0o700 path.
    tempfile.tempdir = str(root)
    tempfile.mkdtemp = inherited_acl_mkdtemp


@pytest.fixture(scope="session")
def tmp_path_factory(request):
    """Use the inherited-ACL factory on Windows and pytest's default elsewhere."""
    if os.name != "nt":
        return request.config._tmp_path_factory
    return request.config._windows_temp_path_factory


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Clean the unique Windows temp tree after success and restore tempfile globals."""
    factory = getattr(session.config, "_windows_temp_path_factory", None)
    try:
        if factory is not None and exitstatus == 0:
            factory.cleanup_after_success()
    finally:
        original_mkdtemp = getattr(session.config, "_windows_original_mkdtemp", None)
        if original_mkdtemp is not None:
            tempfile.mkdtemp = original_mkdtemp
        if hasattr(session.config, "_windows_original_tempdir"):
            tempfile.tempdir = session.config._windows_original_tempdir


def _is_loopback_host(host: object) -> bool:
    if not isinstance(host, str):
        return False
    normalized = host.casefold().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def _is_forbidden_process(args: object) -> bool:
    if isinstance(args, (str, bytes, os.PathLike)):
        command = os.fsdecode(args)
        try:
            tokens = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            tokens = [command]
    else:
        try:
            tokens = [os.fsdecode(token) for token in args]
        except (TypeError, OSError):
            tokens = [str(args)]

    blocked_executables = {
        "codex",
        "codex.exe",
        "codex-cli",
        "codex-cli.exe",
        "curl",
        "curl.exe",
        "docker",
        "docker.exe",
        "nc",
        "nc.exe",
        "ncat",
        "ncat.exe",
        "ssh",
        "ssh.exe",
        "telnet",
        "telnet.exe",
        "wget",
        "wget.exe",
    }
    blocked_operations = {"authorize-one", "run-one"}
    if tokens:
        executable = re.split(r"[/\\]", tokens[0])[-1].casefold()
        if executable in blocked_executables | blocked_operations:
            return True
    return any(
        re.split(r"[/\\]", token)[-1].casefold() in blocked_executables
        or token.casefold() in blocked_operations
        for token in tokens[1:]
    )


@pytest.fixture
def r01a_offline_guard(monkeypatch, request):
    """Block external sockets and live CLI commands while allowing local tests.

    Docker-marked tests retain their explicit operator-only behavior. Offline
    invocations should select ``-m 'not docker'`` and receive this guard.
    """
    if request.node.get_closest_marker("docker"):
        yield
        return

    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex
    original_gethostbyaddr = socket.gethostbyaddr
    original_getnameinfo = socket.getnameinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_bind = socket.socket.bind
    original_sendto = socket.socket.sendto
    original_create_connection = socket.create_connection
    original_popen = subprocess.Popen
    original_run = subprocess.run
    original_system = os.system
    original_os_popen = os.popen

    def check_host(host: object) -> None:
        if host in (None, "", 0):
            return
        if not _is_loopback_host(host):
            raise OfflineActionBlocked("Offline test guard blocked external network access")

    def guarded_getaddrinfo(host, *args, **kwargs):
        check_host(host)
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_gethostbyname(host):
        check_host(host)
        return original_gethostbyname(host)

    def guarded_gethostbyname_ex(host):
        check_host(host)
        return original_gethostbyname_ex(host)

    def guarded_gethostbyaddr(address):
        check_host(address)
        return original_gethostbyaddr(address)

    def guarded_getnameinfo(sockaddr, flags):
        if not isinstance(sockaddr, tuple) or not sockaddr:
            raise OfflineActionBlocked("Offline test guard blocked external name resolution")
        check_host(sockaddr[0])
        return original_getnameinfo(sockaddr, flags)

    def guarded_connect(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None):
            if not isinstance(address, tuple) or not address:
                raise OfflineActionBlocked("Offline test guard blocked an external socket")
            check_host(address[0])
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None):
            if not isinstance(address, tuple) or not address:
                raise OfflineActionBlocked("Offline test guard blocked an external socket")
            check_host(address[0])
        return original_connect_ex(sock, address)

    def guarded_bind(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None):
            if not isinstance(address, tuple) or not address:
                raise OfflineActionBlocked("Offline test guard blocked a nonlocal listener")
            check_host(address[0])
        return original_bind(sock, address)

    def guarded_sendto(sock, data, *args):
        if sock.family != getattr(socket, "AF_UNIX", None):
            address = args[-1] if args else None
            if not isinstance(address, tuple) or not address:
                raise OfflineActionBlocked("Offline test guard blocked an external datagram")
            check_host(address[0])
        return original_sendto(sock, data, *args)

    def guarded_create_connection(address, *args, **kwargs):
        if not isinstance(address, tuple) or not address:
            raise OfflineActionBlocked("Offline test guard blocked an external socket")
        check_host(address[0])
        return original_create_connection(address, *args, **kwargs)

    def guarded_popen(*args, **kwargs):
        command = args[0] if args else kwargs.get("args")
        if _is_forbidden_process(command):
            raise OfflineActionBlocked("Offline test guard blocked a live or external command")
        return original_popen(*args, **kwargs)

    def guarded_run(*args, **kwargs):
        command = args[0] if args else kwargs.get("args")
        if _is_forbidden_process(command):
            raise OfflineActionBlocked("Offline test guard blocked a live or external command")
        return original_run(*args, **kwargs)

    def guarded_system(command):
        if _is_forbidden_process(command):
            raise OfflineActionBlocked("Offline test guard blocked a live or external command")
        return original_system(command)

    def guarded_os_popen(command, *args, **kwargs):
        if _is_forbidden_process(command):
            raise OfflineActionBlocked("Offline test guard blocked a live or external command")
        return original_os_popen(command, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", guarded_gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", guarded_gethostbyname_ex)
    monkeypatch.setattr(socket, "gethostbyaddr", guarded_gethostbyaddr)
    monkeypatch.setattr(socket, "getnameinfo", guarded_getnameinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "bind", guarded_bind)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(os, "system", guarded_system)
    monkeypatch.setattr(os, "popen", guarded_os_popen)
    yield


INDEX_TEXT = """Package: ExamplePkg
Version: 2.10-1
Depends: R (>= 4.1)
Imports: stats, other (>= 1.0)
Suggests: testthat,
    knitr
License: MIT

Package: AnotherPkg
Version: 1.0
License: GPL-3
"""
DESCRIPTION = """Package: ExamplePkg
Version: 2.10-1
Title: Synthetic Data Tools
Description: A synthetic fixture for tests.
Author: Test Author
Authors@R: person('Test', 'Author')
License: MIT
URL: https://example.invalid
Encoding: UTF-8
"""
RD = r"""\name{example}
\alias{example}
\alias{example_alias}
\title{Synthetic example}
\description{Fixture documentation, not an actual R package.}
\usage{example(x)}
\arguments{\item{x}{Input.}}
\examples{example(1)}
"""


def archive(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            body = text.encode() if isinstance(text, str) else text
            member = tarfile.TarInfo(name)
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
    return gzip.compress(buffer.getvalue())


@pytest.fixture
async def service():
    routes = {
        INDEX: INDEX_TEXT.encode(),
        CATALOG: b"<table><tr><td><a>ExamplePkg</a></td><td>Synthetic Data Tools</td></tr>"
        b"<tr><td>AnotherPkg</td><td>Other Tools</td></tr></table>",
        "/web/packages/ExamplePkg/DESCRIPTION": DESCRIPTION.encode(),
        "/src/contrib/ExamplePkg_2.10-1.tar.gz": archive(
            {
                "ExamplePkg/DESCRIPTION": DESCRIPTION,
                "ExamplePkg/man/example.Rd": RD,
            }
        ),
    }
    calls = []

    def handler(request):
        calls.append(request)
        content = routes.get(request.url.path)
        plain = request.url.path.removesuffix(".gz")
        if content is None and request.url.path.endswith("/PACKAGES.gz") and plain in routes:
            # Like CRAN, serve the compressed index alongside the plain one.
            content = gzip.compress(routes[plain])
        return httpx.Response(404 if content is None else 200, content=content or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client)), routes, calls
