"""Errors safe to return across the MCP boundary."""


class KnowledgeError(Exception):
    def __init__(self, code: str, message: str, source_url: str | None = None):
        self.code = code
        self.source_url = source_url
        super().__init__(message)
