# mcpd

MCP server exposing firnline to external AI agents via the
[Model Context Protocol](https://modelcontextprotocol.io/) (streamable HTTP).
Wraps `queryd` and `captured` over HTTP — no direct database access — and
presents their endpoints as MCP tools and resources. Default port: **8090**.

## Full documentation

- [mcpd API reference](../../docs/reference/api/mcpd.md)
- [Configuration reference](../../docs/reference/configuration.md)
