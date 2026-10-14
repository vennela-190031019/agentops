const STATUS_CLASS: Record<string, string> = {
  ok: "badge badge-good",
  ran: "badge badge-good",
  refunded: "badge badge-good",
  pending_approval: "badge badge-warning",
  blocked: "badge badge-critical",
  denied: "badge badge-critical",
  rejected: "badge badge-critical",
  not_found: "badge badge-muted",
};

export function StatusBadge({ status }: { status: string }) {
  const className = STATUS_CLASS[status] ?? "badge badge-muted";
  return <span className={className}>{status.replace(/_/g, " ")}</span>;
}
