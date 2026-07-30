# Legacy Embedded EcoTaxa MCP

The standalone EcoTaxa MCP, its Docker deployment, agent setup instructions, and
user-facing documentation now live in the public
[\`TidianeCisse777/mcp-ecotaxa\`](https://github.com/TidianeCisse777/mcp-ecotaxa)
repository.

IDEA does **not** consume the MCP HTTP server. Its agent calls the shared
EcoTaxa Python functions directly, using its own workspace cache. This
directory remains only for legacy compatibility code inside IDEA; do not use it
as the setup or capability reference for external MCP clients.
