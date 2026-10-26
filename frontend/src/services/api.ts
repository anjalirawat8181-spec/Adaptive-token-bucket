import type {
  ExperimentRequest,
  ExperimentResult,
  ConcurrencySweepResult,
  DynamicStep,
  RateDiagnostic,
  SweepPoint,
  TaskMeasurement,
  TrialSummary,
} from "../types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(
  /\/+$/,
  "",
);
const REQUEST_TIMEOUT_MS = 900_000;

export interface HealthStatus {
  status: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function optionalNumber(
  record: Record<string, unknown>,
  key: string,
): number | undefined {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function optionalString(
  record: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}

function parseSummary(value: unknown): TrialSummary {
  if (!isRecord(value)) {
    throw new Error("The benchmark response contains an invalid trial summary.");
  }
  return {
    scenario: optionalString(value, "scenario"),
    algorithm: optionalString(value, "algorithm"),
    concurrency: optionalNumber(value, "concurrency"),
    trial: optionalNumber(value, "trial"),
    completed_tasks: optionalNumber(value, "completed_tasks"),
    failed_tasks: optionalNumber(value, "failed_tasks"),
    timed_out_tasks: optionalNumber(value, "timed_out_tasks"),
    elapsed_s: optionalNumber(value, "elapsed_s"),
    average_latency_ms: optionalNumber(value, "average_latency_ms"),
    p95_latency_ms: optionalNumber(value, "p95_latency_ms"),
    p90_latency_ms: optionalNumber(value, "p90_latency_ms"),
    throughput_tasks_per_s: optionalNumber(value, "throughput_tasks_per_s"),
    average_cpu_utilization: optionalNumber(value, "average_cpu_utilization"),
    average_memory_utilization: optionalNumber(
      value,
      "average_memory_utilization",
    ),
    average_worker_utilization: optionalNumber(
      value,
      "average_worker_utilization",
    ),
    initial_token_rate: optionalNumber(value, "initial_token_rate"),
    final_token_rate: optionalNumber(value, "final_token_rate"),
    rate_updates: optionalNumber(value, "rate_updates"),
    workload_seed: optionalNumber(value, "workload_seed"),
    workload_id: optionalString(value, "workload_id"),
    algorithm_order: optionalString(value, "algorithm_order"),
    total_tasks: optionalNumber(value, "total_tasks"),
    worker_count: optionalNumber(value, "worker_count"),
    bucket_capacity: optionalNumber(value, "bucket_capacity"),
    adaptive_reference_task_cost_ms: optionalNumber(
      value,
      "adaptive_reference_task_cost_ms",
    ),
    average_external_arrival_to_submission_ms: optionalNumber(
      value,
      "average_external_arrival_to_submission_ms",
    ),
    average_arrival_to_admission_ms: optionalNumber(
      value,
      "average_arrival_to_admission_ms",
    ),
    average_controller_update_ms: optionalNumber(
      value,
      "average_controller_update_ms",
    ),
    average_token_admission_wait_ms: optionalNumber(
      value,
      "average_token_admission_wait_ms",
    ),
    average_executor_queue_wait_ms: optionalNumber(
      value,
      "average_executor_queue_wait_ms",
    ),
    average_processing_ms: optionalNumber(value, "average_processing_ms"),
    minimum_observed_rate: optionalNumber(value, "minimum_observed_rate"),
    maximum_observed_rate: optionalNumber(value, "maximum_observed_rate"),
    average_observed_rate: optionalNumber(value, "average_observed_rate"),
    minimum_rate_clamps: optionalNumber(value, "minimum_rate_clamps"),
    maximum_rate_clamps: optionalNumber(value, "maximum_rate_clamps"),
    controller_evaluations: optionalNumber(value, "controller_evaluations"),
    rate_changes_per_s: optionalNumber(value, "rate_changes_per_s"),
    average_rate_change_magnitude: optionalNumber(
      value,
      "average_rate_change_magnitude",
    ),
    time_at_minimum_rate_s: optionalNumber(value, "time_at_minimum_rate_s"),
    time_at_maximum_rate_s: optionalNumber(value, "time_at_maximum_rate_s"),
    idle_service_rate_n: optionalNumber(value, "idle_service_rate_n"),
    classical_token_rate: optionalNumber(value, "classical_token_rate"),
    load_scope: optionalString(value, "load_scope"),
    average_host_cpu_utilization: optionalNumber(value, "average_host_cpu_utilization"),
    average_host_memory_utilization: optionalNumber(value, "average_host_memory_utilization"),
    service_memory_budget_bytes: optionalNumber(value, "service_memory_budget_bytes"),
    contention_model: typeof value.contention_model === "boolean" ? value.contention_model : undefined,
    effective_parallelism: optionalNumber(value, "effective_parallelism"),
    rate_mode: optionalString(value, "rate_mode"),
    dynamic_step: optionalNumber(value, "dynamic_step"),
  };
}

function parseTask(value: unknown): TaskMeasurement {
  if (!isRecord(value)) {
    throw new Error("The benchmark response contains an invalid task record.");
  }
  return {
    task_id: optionalNumber(value, "task_id"),
    task_type: optionalString(value, "task_type"),
    duration_ms: optionalNumber(value, "duration_ms"),
    scheduled_arrival_offset_s: optionalNumber(
      value,
      "scheduled_arrival_offset_s",
    ),
    scheduled_arrival_s: optionalNumber(value, "scheduled_arrival_s"),
    actual_arrival_s: optionalNumber(value, "actual_arrival_s"),
    submitted_s: optionalNumber(value, "submitted_s"),
    admitted_s: optionalNumber(value, "admitted_s"),
    started_s: optionalNumber(value, "started_s"),
    completed_s: optionalNumber(value, "completed_s"),
    admission_delay_ms: optionalNumber(value, "admission_delay_ms"),
    queue_wait_ms: optionalNumber(value, "queue_wait_ms"),
    latency_ms: optionalNumber(value, "latency_ms"),
    processing_ms: optionalNumber(value, "processing_ms"),
    status: optionalString(value, "status"),
    error: optionalString(value, "error"),
    scenario: optionalString(value, "scenario"),
    algorithm: optionalString(value, "algorithm"),
    concurrency: optionalNumber(value, "concurrency"),
    trial: optionalNumber(value, "trial"),
    workload_seed: optionalNumber(value, "workload_seed"),
    workload_id: optionalString(value, "workload_id"),
    external_arrival_to_submission_ms: optionalNumber(
      value,
      "external_arrival_to_submission_ms",
    ),
    token_requested_s: optionalNumber(value, "token_requested_s"),
    controller_update_ms: optionalNumber(value, "controller_update_ms"),
    token_admission_wait_ms: optionalNumber(value, "token_admission_wait_ms"),
  };
}

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return `Request failed with status ${response.status}.`;

  try {
    const body: unknown = JSON.parse(text);
    if (isRecord(body) && typeof body.detail === "string") {
      return body.detail;
    }
    if (isRecord(body) && Array.isArray(body.detail)) {
      return body.detail
        .map((item) =>
          isRecord(item) && typeof item.msg === "string" ? item.msg : "",
        )
        .filter(Boolean)
        .join("; ");
    }
    if (isRecord(body) && typeof body.message === "string") {
      return body.message;
    }
  } catch {
    return text;
  }
  return text;
}

async function request(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS,
  );

  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(
        "The request timed out while waiting for the backend. Check the server and try again.",
      );
    }
    if (error instanceof TypeError) {
      throw new Error(
        `Could not reach the API at ${
          API_BASE_URL || `${window.location.origin} (/api proxy)`
        }. Start the FastAPI backend and check its CORS settings.`,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function checkHealth(): Promise<HealthStatus> {
  const response = await request("/api/health");
  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const body: unknown = await response.json();
  if (!isRecord(body) || typeof body.status !== "string") {
    throw new Error("The health endpoint returned an unexpected response.");
  }
  return { status: body.status };
}

export async function runExperiment(
  configuration: ExperimentRequest,
): Promise<ExperimentResult> {
  const response = await request("/api/experiments/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(configuration),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const body: unknown = await response.json();
  if (
    !isRecord(body) ||
    typeof body.scenario !== "string" ||
    typeof body.concurrency !== "number" ||
    typeof body.repetitions !== "number" ||
    !Array.isArray(body.algorithms) ||
    !Array.isArray(body.summaries) ||
    !Array.isArray(body.task_results)
  ) {
    throw new Error("The benchmark endpoint returned an unexpected response.");
  }
  if (!body.algorithms.every((item) => typeof item === "string")) {
    throw new Error("The benchmark response contains invalid algorithm names.");
  }
  const dynamicRelative = isRecord(body.dynamic_relative_differences)
    ? body.dynamic_relative_differences
    : undefined;
  return {
    scenario: body.scenario,
    concurrency: body.concurrency,
    repetitions: body.repetitions,
    algorithms: body.algorithms,
    summaries: body.summaries.map(parseSummary),
    task_results: body.task_results.map(parseTask),
    task_csv: typeof body.task_csv === "string" ? body.task_csv : undefined,
    summary_csv:
      typeof body.summary_csv === "string" ? body.summary_csv : undefined,
    task_csv_url:
      typeof body.task_csv_url === "string" ? body.task_csv_url : undefined,
    summary_csv_url:
      typeof body.summary_csv_url === "string"
        ? body.summary_csv_url
        : undefined,
    diagnostic_csv_url:
      typeof body.diagnostic_csv_url === "string"
        ? body.diagnostic_csv_url
        : undefined,
    rate_diagnostics_count: optionalNumber(body, "rate_diagnostics_count"),
    dynamic_steps_csv_url: optionalString(body, "dynamic_steps_csv_url"),
    rate_diagnostics: Array.isArray(body.rate_diagnostics)
      ? body.rate_diagnostics.filter(isRecord).map((row): RateDiagnostic => ({
          scenario: optionalString(row, "scenario"),
          algorithm: optionalString(row, "algorithm"),
          trial: optionalNumber(row, "trial"),
          task_id: optionalNumber(row, "task_id"),
          elapsed_s: optionalNumber(row, "elapsed_s"),
          applied_rate: optionalNumber(row, "applied_rate"),
          minimum_rate: optionalNumber(row, "minimum_rate"),
          maximum_rate: optionalNumber(row, "maximum_rate"),
        }))
      : [],
    dynamic_steps: Array.isArray(body.dynamic_steps)
      ? body.dynamic_steps.filter(isRecord).map((row): DynamicStep => ({
          step: optionalNumber(row, "step") ?? 0,
          concurrency: optionalNumber(row, "concurrency") ?? 0,
          algorithm: optionalString(row, "algorithm") ?? "",
          mean_latency_ms: optionalNumber(row, "mean_latency_ms"),
          p90_latency_ms: optionalNumber(row, "p90_latency_ms"),
          throughput_tasks_per_s: optionalNumber(row, "throughput_tasks_per_s"),
          classical_rate: optionalNumber(row, "classical_rate"),
          adaptive_rate_min: optionalNumber(row, "adaptive_rate_min"),
          adaptive_rate_mean: optionalNumber(row, "adaptive_rate_mean"),
          adaptive_rate_max: optionalNumber(row, "adaptive_rate_max"),
          adaptive_min_clamp_fraction: optionalNumber(row, "adaptive_min_clamp_fraction"),
          adaptive_max_clamp_fraction: optionalNumber(row, "adaptive_max_clamp_fraction"),
        }))
      : [],
    dynamic_relative_differences: dynamicRelative
      ? {
          mean_latency_relative_difference: optionalNumber(dynamicRelative, "mean_latency_relative_difference"),
          mean_p90_relative_difference: optionalNumber(dynamicRelative, "mean_p90_relative_difference"),
          mean_throughput_relative_difference: optionalNumber(dynamicRelative, "mean_throughput_relative_difference"),
        }
      : null,
    classical_rate_mode: optionalString(body, "classical_rate_mode"),
    classical_rate: optionalNumber(body, "classical_rate"),
    contention_model: typeof body.contention_model === "boolean" ? body.contention_model : undefined,
    load_scope: optionalString(body, "load_scope"),
  };
}

export async function runSweep(configuration: {
  scenario: "simple" | "general" | "complex" | "mixed";
  concurrency_step: number;
  repetitions: number;
  comparison: string;
}): Promise<ConcurrencySweepResult> {
  const response = await request("/api/experiments/sweep", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(configuration),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body: unknown = await response.json();
  if (!isRecord(body) || !Array.isArray(body.points)) {
    throw new Error("The sweep endpoint returned an unexpected response.");
  }
  return {
    scenario: optionalString(body, "scenario") ?? configuration.scenario,
    concurrency_step: optionalNumber(body, "concurrency_step") ?? configuration.concurrency_step,
    repetitions: optionalNumber(body, "repetitions") ?? configuration.repetitions,
    comparison: optionalString(body, "comparison") ?? configuration.comparison,
    estimated_runtime_s: optionalNumber(body, "estimated_runtime_s") ?? 0,
    points: body.points.filter(isRecord).map((point): SweepPoint => ({
      concurrency: optionalNumber(point, "concurrency") ?? 0,
      algorithm: optionalString(point, "algorithm") ?? "",
      mean_average_latency_ms: optionalNumber(point, "mean_average_latency_ms"),
      std_average_latency_ms: optionalNumber(point, "std_average_latency_ms"),
      mean_p90_latency_ms: optionalNumber(point, "mean_p90_latency_ms"),
      std_p90_latency_ms: optionalNumber(point, "std_p90_latency_ms"),
      mean_throughput_tasks_per_s: optionalNumber(point, "mean_throughput_tasks_per_s"),
      std_throughput_tasks_per_s: optionalNumber(point, "std_throughput_tasks_per_s"),
    })),
    csv: optionalString(body, "csv"),
  };
}

export async function downloadCsv(url: string): Promise<void> {
  if (
    url !== "/api/experiments/download/task_results.csv" &&
    url !== "/api/experiments/download/benchmark_summary.csv" &&
    url !== "/api/experiments/download/rate_diagnostics.csv"
    && url !== "/api/experiments/download/dynamic_steps.csv"
    && url !== "/api/experiments/download/concurrency_sweep.csv"
  ) {
    throw new Error("The benchmark response included an invalid CSV download URL.");
  }
  const response = await request(url);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const blob = await response.blob();
  if (blob.size === 0) {
    throw new Error("The server returned an empty CSV file.");
  }

  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = url.endsWith("task_results.csv")
    ? "task_results.csv"
    : url.endsWith("benchmark_summary.csv")
      ? "benchmark_summary.csv"
      : url.endsWith("dynamic_steps.csv")
        ? "dynamic_steps.csv"
        : url.endsWith("concurrency_sweep.csv")
          ? "concurrency_sweep.csv"
          : "rate_diagnostics.csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

export function getApiBaseUrl(): string {
  return API_BASE_URL || `${window.location.origin} (/api proxy)`;
}
