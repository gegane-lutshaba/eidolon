"""A tiny downstream MCP tool server (stdio) for gateway transport tests.

Two tools with opposite governance outcomes under the ops policy:
- get_deploy_status  -> routine read (acting level)
- send_customer_email -> touches the external-client-comm exclusion (denied)
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-tools")


@mcp.tool()
def get_deploy_status(service: str) -> str:
    """Deploy status for a service."""
    return f"{service}: deployed v1.2.3, healthy"


@mcp.tool()
def send_customer_email(to: str, body: str) -> str:
    """Send an email to a customer (should never be reached ungoverned)."""
    return f"sent to {to}"


if __name__ == "__main__":
    mcp.run()  # stdio
