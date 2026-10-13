"""Role-based access control for agent tools."""

ROLE_TOOLS = {
    "customer": {"lookup_order"},
    "support_agent": {"lookup_order", "issue_refund"},
}


def is_allowed(role: str, tool: str) -> bool:
    return tool in ROLE_TOOLS.get(role, set())
