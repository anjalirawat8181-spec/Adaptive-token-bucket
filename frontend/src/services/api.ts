import type {
  ExperimentRequest,
  ExperimentResult,
  TaskMeasurement,
  TrialSummary,
} from "../types";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");
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
    elapsed_s: optionalNumber(value, "elapsed_s"),
    average_latency_ms: optionalNumber(value, "average_latency_ms"),
    throughput_tasks_per_s: optionalNumber(value, "throughput_tasks_per_s"),
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
    submitted_s: optionalNumber(value, "submitted_s"),
    admitted_s: optionalNumber(value, "admitted_s"),
    started_s: optionalNumber(value, "started_s"),
    completed_s: optionalNumber(value, "completed_s"),
    queue_wait_ms: optionalNumber(value, "queue_wait_ms"),
    latency_ms: optionalNumber(value, "latency_ms"),
    processing_ms: optionalNumber(value, "processing_ms"),
    scenario: optionalString(value, "scenario"),
    algorithm: optionalString(value, "algorithm"),
    concurrency: optionalNumber(value, "concurrency"),
    trial: optionalNumber(value, "trial"),
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
        `Could not reach the API at ${API_BASE_URL}. Start the FastAPI backend and check its CORS settings.`,
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
  };
}

export async function downloadCsv(url: string): Promise<void> {
  if (
    url !== "/api/experiments/download/task_results.csv" &&
    url !== "/api/experiments/download/benchmark_summary.csv"
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
    : "benchmark_summary.csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}
