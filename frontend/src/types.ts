export type Scenario = "simple" | "general" | "complex" | "mixed" | "dynamic";
export type Comparison = "both" | "classical" | "adaptive";
export type Algorithm = "classical" | "adaptive";

export interface ExperimentRequest {
  scenario: Scenario;
  concurrency: number;
  repetitions: number;
  comparison: Comparison;
  classical_rate_mode?: "paper_preset" | "measured" | "manual";
  classical_rate?: number;
  contention_model?: boolean;
  speedup?: number;
  load_scope?: "process" | "host";
  idle_service_rate_n_override?: number;
}

export interface TrialSummary {
  scenario?: string;
  algorithm?: string;
  concurrency?: number;
  trial?: number;
  completed_tasks?: number;
  failed_tasks?: number;
  timed_out_tasks?: number;
  elapsed_s?: number;
  average_latency_ms?: number;
  p95_latency_ms?: number;
  p90_latency_ms?: number;
  throughput_tasks_per_s?: number;
  average_cpu_utilization?: number;
  average_memory_utilization?: number;
  average_worker_utilization?: number;
  initial_token_rate?: number;
  final_token_rate?: number;
  rate_updates?: number;
  workload_seed?: number;
  workload_id?: string;
  algorithm_order?: string;
  total_tasks?: number;
  worker_count?: number;
  bucket_capacity?: number;
  adaptive_reference_task_cost_ms?: number;
  average_external_arrival_to_submission_ms?: number;
  average_controller_update_ms?: number;
  average_token_admission_wait_ms?: number;
  average_executor_queue_wait_ms?: number;
  average_processing_ms?: number;
  minimum_observed_rate?: number;
  maximum_observed_rate?: number;
  average_observed_rate?: number;
  minimum_rate_clamps?: number;
  maximum_rate_clamps?: number;
  controller_evaluations?: number;
  rate_changes_per_s?: number;
  average_rate_change_magnitude?: number;
  time_at_minimum_rate_s?: number;
  time_at_maximum_rate_s?: number;
  average_arrival_to_admission_ms?: number;
  idle_service_rate_n?: number;
  classical_token_rate?: number;
  load_scope?: string;
  average_host_cpu_utilization?: number;
  average_host_memory_utilization?: number;
  service_memory_budget_bytes?: number;
  contention_model?: boolean;
  effective_parallelism?: number;
  rate_mode?: string;
  dynamic_step?: number;
}

export interface RateDiagnostic {
  scenario?: string;
  algorithm?: string;
  trial?: number;
  task_id?: number;
  elapsed_s?: number;
  applied_rate?: number;
  minimum_rate?: number;
  maximum_rate?: number;
}

export interface DynamicStep {
  step: number;
  concurrency: number;
  algorithm: string;
  mean_latency_ms?: number;
  p90_latency_ms?: number;
  throughput_tasks_per_s?: number;
  classical_rate?: number;
  adaptive_rate_min?: number;
  adaptive_rate_mean?: number;
  adaptive_rate_max?: number;
  adaptive_min_clamp_fraction?: number;
  adaptive_max_clamp_fraction?: number;
}

export interface SweepPoint {
  concurrency: number;
  algorithm: string;
  mean_average_latency_ms?: number;
  std_average_latency_ms?: number;
  mean_p90_latency_ms?: number;
  std_p90_latency_ms?: number;
  mean_throughput_tasks_per_s?: number;
  std_throughput_tasks_per_s?: number;
}

export interface ConcurrencySweepResult {
  scenario: string;
  concurrency_step: number;
  repetitions: number;
  comparison: string;
  estimated_runtime_s: number;
  points: SweepPoint[];
  csv?: string;
}

export interface TaskMeasurement {
  task_id?: number;
  task_type?: string;
  duration_ms?: number;
  scheduled_arrival_offset_s?: number;
  scheduled_arrival_s?: number;
  actual_arrival_s?: number;
  submitted_s?: number;
  admitted_s?: number;
  started_s?: number;
  completed_s?: number;
  admission_delay_ms?: number;
  queue_wait_ms?: number;
  latency_ms?: number;
  processing_ms?: number;
  status?: string;
  error?: string;
  scenario?: string;
  algorithm?: string;
  concurrency?: number;
  trial?: number;
  workload_seed?: number;
  workload_id?: string;
  external_arrival_to_submission_ms?: number;
  token_requested_s?: number;
  controller_update_ms?: number;
  token_admission_wait_ms?: number;
}

export interface ExperimentResult {
  scenario: string;
  concurrency: number;
  repetitions: number;
  algorithms: string[];
  summaries: TrialSummary[];
  task_results: TaskMeasurement[];
  task_csv?: string;
  summary_csv?: string;
  task_csv_url?: string;
  summary_csv_url?: string;
  diagnostic_csv_url?: string;
  dynamic_steps_csv_url?: string;
  rate_diagnostics_count?: number;
  rate_diagnostics?: RateDiagnostic[];
  dynamic_steps?: DynamicStep[];
  dynamic_relative_differences?: {
    mean_latency_relative_difference?: number;
    mean_p90_relative_difference?: number;
    mean_throughput_relative_difference?: number;
  } | null;
  classical_rate_mode?: string;
  classical_rate?: number;
  contention_model?: boolean;
  load_scope?: string;
}

export interface SavedExperiment {
  id: number;
  completedAt: string;
  request: ExperimentRequest;
  result: ExperimentResult;
}
