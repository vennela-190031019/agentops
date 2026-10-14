export interface Span {
  name: string;
  latency_ms: number;
  tokens: number;
  error: string | null;
}

export interface TraceRun {
  run_id: string;
  question: string;
  role: string;
  status: string;
  answer: string;
  created_at: number;
  latency_ms: number;
  tokens: number;
  errors: number;
  spans: Span[];
}

export interface PendingApproval {
  run_id: string;
  question: string;
  role: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface ApprovalResult {
  status: string;
  run_id: string;
  answer: string;
  tool_results: Array<{
    tool: string;
    args: Record<string, unknown>;
    status: string;
    output: Record<string, unknown>;
    reviewer?: string;
  }>;
}

export interface EvalMetrics {
  groundedness: number;
  tool_accuracy: number;
  correctness: number;
  pass_rate: number;
  p95_latency_ms: number;
  avg_tokens: number;
}

export interface EvalHistoryEntry {
  timestamp: string;
  pass_rate: number;
  metrics: EvalMetrics;
  regressed: boolean;
}
