"""API-key authentication.

Keys map to a role via the `AGENTOPS_API_KEYS` env var (a JSON object, e.g.
`{"cust-key": "customer", "agent-key": "support_agent", "reviewer-key": "reviewer"}`).
The caller's role is always derived from the key on the server -- an
endpoint never trusts a role (or reviewer identity) supplied in the request
body, which is what stops a client from spoofing a higher-privilege role.

The keys are re-read from the env var on every call (not cached at import
time) so tests can point `AGENTOPS_API_KEYS` at a fixture map regardless of
module import order, mirroring `api/store.py`'s `_db_path()`.
"""
import json
import logging
import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException

logger = logging.getLogger("agentops.auth")

ROLES = {"customer", "support_agent", "reviewer"}

# Used only when AGENTOPS_API_KEYS isn't set -- clearly-named so nobody mistakes
# them for real secrets, and a warning is logged every time they're used.
DEV_KEYS = {
    "dev-customer-key": "customer",
    "dev-support-agent-key": "support_agent",
    "dev-reviewer-key": "reviewer",
}


def _load_keys() -> dict[str, str]:
    raw = os.environ.get("AGENTOPS_API_KEYS")
    if not raw:
        logger.warning(
            "AGENTOPS_API_KEYS is not set -- using insecure dev API keys (%s). "
            "Set AGENTOPS_API_KEYS to a JSON {key: role} map before deploying.",
            ", ".join(DEV_KEYS),
        )
        return DEV_KEYS
    return json.loads(raw)


def require_role(*allowed_roles: str):
    """FastAPI dependency factory. 401 on a missing/invalid key. 403 if the
    key's role isn't in `allowed_roles` (no roles given = any valid key is
    fine). Returns (role, api_key) so the endpoint can record who acted
    without trusting anything the client put in the request body.
    """

    def dependency(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> tuple[str, str]:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing X-API-Key header")
        role = _load_keys().get(x_api_key)
        if role is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if allowed_roles and role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Role '{role}' may not access this endpoint")
        return role, x_api_key

    return dependency


Auth = Annotated[tuple[str, str], Depends(require_role())]
ChatAuth = Annotated[tuple[str, str], Depends(require_role("customer", "support_agent"))]
ReviewerAuth = Annotated[tuple[str, str], Depends(require_role("reviewer"))]
