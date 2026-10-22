# MCP tool errors and partial results

The adapter uses the installed MCP Python SDK 1.x FastMCP API (validated with
SDK 1.30.0). FastMCP normally turns a returned dictionary into a successful
`CallToolResult`, so the service's structured failure envelope alone did not
mark the protocol result as failed. The server now returns the SDK's
`mcp.types.CallToolResult` at the FastMCP call boundary. Its `isError` field
sets the MCP tool status while `structuredContent` retains the existing
application envelope and `content` contains the same JSON for clients that
read text only.

The classification uses the documented top-level response contract. An
application response with `verification_status="failed"` and its existing
`error.code` is a failed tool call. A failed repository aggregate has
`verification_status="failed"`, an empty `results` list, and provider errors
in `errors`; it is also a failed call. `verification_status="partial"` stays a
successful tool call even when it contains `errors` or failed optional
sections. Successful result fields and schemas remain unchanged.

SDK argument validation failures become a sanitized `invalid_input` envelope.
Unexpected exceptions become a sanitized `internal_error`; exception strings,
tracebacks, and secret values are not sent to clients. The SDK's
`CallToolResult` has no standard machine-readable error-code field. This server
keeps its application codes in `structuredContent.error.code`, and serializes
the envelope in `content` for older clients. Input-schema failures that occur
inside FastMCP are normalized at the same adapter boundary.

Clients should check `isError` first, then inspect `structuredContent.error`
for a failed call. If `isError` is false, consumers may still need to check
`verification_status` and aggregate `errors`; partial data remains useful and
must not be discarded as a complete failure.

Successful response:

```json
{
  "isError": false,
  "content": [
    {
      "type": "text",
      "text": "{\"package\":\"ggplot2\",\"verification_status\":\"verified\"}"
    }
  ],
  "structuredContent": {
    "package": "ggplot2",
    "verification_status": "verified"
  }
}
```

Failed response:

```json
{
  "isError": true,
  "content": [
    {
      "type": "text",
      "text": "{\"package\":\"MissingPkg\",\"verification_status\":\"failed\",\"error\":{\"code\":\"package_not_found\",\"message\":\"Package is not in the selected repository index\"}}"
    }
  ],
  "structuredContent": {
    "package": "MissingPkg",
    "verification_status": "failed",
    "error": {
      "code": "package_not_found",
      "message": "Package is not in the selected repository index"
    }
  }
}
```

Partial response:

```json
{
  "isError": false,
  "content": [
    {
      "type": "text",
      "text": "{\"repository\":\"all\",\"verification_status\":\"partial\",\"results\":[{\"repository\":\"cran\"}],\"errors\":[{\"repository\":\"bioconductor\"}]}"
    }
  ],
  "structuredContent": {
    "repository": "all",
    "verification_status": "partial",
    "results": [{"repository": "cran"}],
    "errors": [{"repository": "bioconductor"}]
  }
}
```

This changes the previous behavior for complete application failures: clients
that only inspected the JSON envelope continue to find `error.code`, while MCP
clients can now correctly branch on `isError`. MCP Prompt request failures
remain SDK protocol errors; this document covers tool calls.

SDK references:

- [Python SDK FastMCP server implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/fastmcp/server.py)
- [Python SDK low-level tool result handling](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/lowlevel/server.py)
- [MCP tool result specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
