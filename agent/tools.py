"""Agent tools. `RISKY` tools need human approval before they run."""

ORDERS = {
    "ORD-1001": {"status": "shipped", "carrier": "UPS", "eta": "2026-10-15"},
    "ORD-1002": {"status": "processing", "carrier": None, "eta": None},
    "ORD-1003": {"status": "delivered", "carrier": "FedEx", "eta": "2026-10-05"},
}

RISKY = {"issue_refund"}


def lookup_order(order_id: str) -> dict:
    o = ORDERS.get(order_id)
    if not o:
        return {"status": "not_found", "order_id": order_id}
    return {"status": "ok", "order_id": order_id, **{"order_status": o["status"], "carrier": o["carrier"], "eta": o["eta"]}}


def issue_refund(order_id: str) -> dict:
    return {"status": "refunded", "order_id": order_id}


TOOLS = {"lookup_order": lookup_order, "issue_refund": issue_refund}
