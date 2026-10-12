export type Scenario = "simple" | "general" | "complex" | "mixed" | "dynamic";
export type Comparison = "both" | "classical" | "adaptive";
export type Algorithm = "classical" | "adaptive";

export interface ExperimentRequest {
  scenario: Scenario;
  concurrency: number;
  repetitions: number;
  comparison: Comparison;
}

export interface TrialSummary {
  scenario?: string;
  algorithm?: string;
  concurrency?: number;
  trial?: number;
  completed_tasks?: number;
  elapsed_s?: number;
  average_latency_ms?: number;
  throughput_tasks_per_s?: number;
}

export interface TaskMeasurement {
  task_id?: number;
  task_type?: string;
  duration_ms?: number;
  submitted_s?: number;
  admitted_s?: number;
  started_s?: number;
  completed_s?: number;
  queue_wait_ms?: number;
  latency_ms?: number;
  processing_ms?: number;
  scenario?: string;
  algorithm?: string;
  concurrency?: number;
  trial?: number;
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
}

export interface SavedExperiment {
  id: number;
  completedAt: string;
  request: ExperimentRequest;
  result: ExperimentResult;
}
