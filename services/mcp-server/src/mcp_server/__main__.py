"""Entry point: `uv run edi-mcp-server` starts the stdio MCP server."""

from mcp_server.server import server


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
