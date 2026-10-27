"""Errors safe to return across the MCP boundary."""


class KnowledgeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        source_url: str | None = None,
        *,
        related_sources: list[dict] | None = None,
        cached: bool = False,
        details: dict | None = None,
    ):
        self.code = code
        self.source_url = source_url
        self.related_sources = related_sources or []
        self.cached = cached
        # Bounded, verified fields merged into the returned error object.
        self.details = details or {}
        super().__init__(message)
