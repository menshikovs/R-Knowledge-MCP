# Example report shape

[`tool-value-example.json`](tool-value-example.json) records one successful
`analyze_r_source` call captured by the local MCP server regression test. It is
not an agent run: there is no OpenAI session, model usage, or cost. The server
logged one tool call, 78 request bytes, 1,817 result bytes, and a 455-token
byte-based estimate. The estimate is not billed usage. No `tools/list` or
agent-side `tool_search` happened in this test; the one rejected request was a
deliberately cross-origin transport probe.

A real paired run writes this same per-call and per-tool shape to
`mcp_calls.csv` and `mcp_tool_aggregates.csv`, alongside `results.csv` and
`results.json`. Actual Agents API usage and cost are null when the API does not
return them.
