export interface LocalModelActivityV1 {
  model_ref: string | null;
  succeeded: number;
  failed: number;
  active: number;
  cancelled: number;
  blocked: number;
  skipped: number;
  success_rate: number | null;
  mean_success_seconds: number | null;
  duration_samples: number;
  error_codes: Record<string, number>;
}

export interface LocalRuntimeStatisticsV1 {
  generated_at: string;
  period_days: number;
  sampled_members: number;
  truncated: boolean;
  cost_available: boolean;
  items: LocalModelActivityV1[];
}
