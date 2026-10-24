"""Optional Rust accelerators (package `cran-knowledge-native`, built from native/).

The pure-Python implementations remain the reference and the fallback: the server
works identically without the extension, and parity tests compare both paths.
Set R_KNOWLEDGE_NATIVE=0 to force the Python implementations.
"""

import os

ABI_VERSION = 3


def _load():
    if os.environ.get("R_KNOWLEDGE_NATIVE", "").strip().casefold() in {"0", "false", "no", "off"}:
        return None
    try:
        import cran_knowledge_native
    except ImportError:
        return None
    # A stale build with another result shape must never be used.
    if getattr(cran_knowledge_native, "ABI_VERSION", None) != ABI_VERSION:
        return None
    return cran_knowledge_native


native = _load()


def status() -> dict:
    return {"native_accelerators": native is not None, "abi_version": ABI_VERSION}
