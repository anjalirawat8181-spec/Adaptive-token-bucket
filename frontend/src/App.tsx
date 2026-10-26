import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  Download,
  FlaskConical,
  Gauge,
  Info,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  Menu,
  Play,
  RefreshCw,
  Search,
  Settings2,
  X,
} from "lucide-react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { checkHealth, downloadCsv, getApiBaseUrl, runExperiment, runSweep } from "./services/api";
import type {
  Algorithm,
  ConcurrencySweepResult,
  ExperimentRequest,
  SavedExperiment,
  Scenario,
  TaskMeasurement,
  TrialSummary,
} from "./types";

type Page =
  | "overview"
  | "experiment"
  | "tasks"
  | "insights"
  | "project";
type ConnectionState = "checking" | "connected" | "disconnected";

const navigation: { id: Page; label: string; icon: typeof Activity }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "experiment", label: "Experiment Lab", icon: FlaskConical },
  { id: "tasks", label: "Task Monitor", icon: ListChecks },
  { id: "insights", label: "Algorithm Insights", icon: Activity },
  { id: "project", label: "Project Information", icon: BookOpen },
];

const scenarioLabels: Record<Scenario, string> = {
  simple: "Simple tasks",
  general: "General tasks",
  complex: "Complex tasks",
  mixed: "Mixed workload",
  dynamic: "Dynamic traffic",
};

const scenarioDescriptions: Record<Scenario, string> = {
  simple: "All tasks use the 5 ms simple service time and arrive together.",
  general: "All tasks use the 20 ms general service time and arrive together.",
  complex: "All tasks use the 80 ms complex service time and arrive together.",
  mixed: "Task types are seeded across 5, 20, and 80 ms; all arrive together.",
  dynamic:
    "A 70-step periodic concurrency envelope (20–200 requests) drives paired mixed-workload bursts. The envelope is a documented stand-in for the paper’s cited daily-traffic equation.",
};

const algorithmLabels: Record<Algorithm, string> = {
  classical: "Adaptive",
  adaptive: "Classical",
};

const colors: Record<Algorithm, string> = {
  classical: "#438fc2",
  adaptive: "#718897",
};

const initialForm: ExperimentRequest = {
  scenario: "mixed",
  concurrency: 20,
  repetitions: 3,
  comparison: "both",
  contention_model: true,
  load_scope: "process",
  speedup: 1,
};

function formatNumber(value: number | undefined, digits = 2): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";
}

function ConcurrencySweepPanel({
  scenario,
  repetitions,
  comparison,
  disabled,
}: {
  scenario: Scenario;
  repetitions: number;
  comparison: ExperimentRequest["comparison"];
  disabled: boolean;
}) {
  const [step, setStep] = useState("5");
  const [sweepRepetitions, setSweepRepetitions] = useState("20");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ConcurrencySweepResult | null>(null);

  async function executeSweep() {
    if (scenario === "dynamic") {
      setError("The dynamic scenario runs its own 70-step traffic envelope.");
      return;
    }
    setRunning(true);
    setError("");
    try {
      setResult(await runSweep({
        scenario,
        concurrency_step: Number(step),
        repetitions: Number(sweepRepetitions || repetitions),
        comparison,
      }));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setRunning(false);
    }
  }

  const chartRows = useMemo(() => {
    if (!result) return [];
    const byConcurrency = new Map<number, Record<string, number>>();
    for (const point of result.points) {
      const row = byConcurrency.get(point.concurrency) ?? {
        concurrency: point.concurrency,
      };
      for (const metric of [
        "average_latency_ms",
        "p90_latency_ms",
        "throughput_tasks_per_s",
      ] as const) {
        const value = point[`mean_${metric}`];
        const deviation = point[`std_${metric}`] ?? 0;
        if (typeof value === "number") {
          row[`${point.algorithm}_${metric}`] = value;
          row[`${point.algorithm}_${metric}_low`] = Math.max(0, value - deviation);
          row[`${point.algorithm}_${metric}_band`] = 2 * deviation;
        }
      }
      byConcurrency.set(point.concurrency, row);
    }
    return [...byConcurrency.values()].sort((a, b) => a.concurrency - b.concurrency);
  }, [result]);

  return (
    <section className="panel sweep-panel" aria-label="Concurrency sweep">
      <div className="panel-heading">
        <div className="panel-heading-icon"><Activity size={18} /></div>
        <div>
          <h2>Concurrency sweep</h2>
          <p>Mean and standard deviation across concurrency levels.</p>
        </div>
      </div>
      <div className="sweep-controls">
        <label>Step <input type="number" min={1} max={200} value={step} onChange={(event) => setStep(event.target.value)} /></label>
        <label>Repetitions <input type="number" min={1} max={20} value={sweepRepetitions} onChange={(event) => setSweepRepetitions(event.target.value)} /></label>
        <button className="button button-secondary" type="button" onClick={executeSweep} disabled={disabled || running || scenario === "dynamic"}>
          {running ? "Sweep running…" : "Run concurrency sweep"}
        </button>
      </div>
      <p className="field-hint">Sweeps exceeding the 15-minute estimate are rejected by the API.</p>
      {error && <div className="alert alert-error" role="alert"><AlertCircle size={16} /> {error}</div>}
      {result && (
        <>
          <p className="field-hint">Estimated runtime: {formatNumber(result.estimated_runtime_s / 60, 1)} minutes.</p>
          <div className="chart-grid">
            <SweepChart title="Mean latency" metric="average_latency_ms" rows={chartRows} unit="ms" />
            <SweepChart title="90th percentile latency" metric="p90_latency_ms" rows={chartRows} unit="ms" />
            <SweepChart title="Throughput" metric="throughput_tasks_per_s" rows={chartRows} unit="tasks/s" />
          </div>
        </>
      )}
    </section>
  );
}

function SweepChart({
  title,
  metric,
  rows,
  unit,
}: {
  title: string;
  metric: string;
  rows: Record<string, number>[];
  unit: string;
}) {
  return (
    <ChartPanel title={title} subtitle={`Mean ± standard deviation · ${unit}`}>
      {rows.length ? (
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#e5edf2" vertical={false} />
            <XAxis dataKey="concurrency" />
            <YAxis width={48} />
            <Tooltip formatter={(value) => [`${formatNumber(Number(value))} ${unit}`]} />
            <Legend />
            {(["classical", "adaptive"] as const).map((algorithm) => (
              <Fragment key={algorithm}>
                <Area dataKey={`${algorithm}_${metric}_low`} stackId={`${algorithm}-band`} fill="transparent" stroke="none" legendType="none" />
                <Area dataKey={`${algorithm}_${metric}_band`} stackId={`${algorithm}-band`} fill={colors[algorithm]} fillOpacity={0.13} stroke="none" name={`${algorithmLabels[algorithm]} ± SD`} />
                <Line type="monotone" dataKey={`${algorithm}_${metric}`} name={algorithmLabels[algorithm]} stroke={colors[algorithm]} strokeWidth={2} dot={false} connectNulls />
              </Fragment>
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : <ChartEmpty />}
    </ChartPanel>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function displayAlgorithm(value: string | undefined): string {
  if (value === "classical" || value === "adaptive") {
    return algorithmLabels[value];
  }
  return value || "Unavailable";
}

function summarizeAlgorithms(summaries: TrialSummary[]) {
  return (["classical", "adaptive"] as const)
    .map((algorithm) => {
      const rows = summaries.filter((row) => row.algorithm === algorithm);
      if (rows.length === 0) return null;
      const completed = rows.reduce(
        (total, row) => total + (row.completed_tasks ?? 0),
        0,
      );
      const failed = rows.reduce(
        (total, row) => total + (row.failed_tasks ?? 0),
        0,
      );
      const timedOut = rows.reduce(
        (total, row) => total + (row.timed_out_tasks ?? 0),
        0,
      );
      const elapsed = rows.reduce((total, row) => total + (row.elapsed_s ?? 0), 0);
      const latencies = rows.filter(
        (row) =>
          typeof row.average_latency_ms === "number" &&
          (row.completed_tasks ?? 0) > 0,
      );
      const averageLatency =
        completed > 0
          ? latencies.reduce(
              (total, row) =>
                total +
                (row.average_latency_ms ?? 0) * (row.completed_tasks ?? 0),
              0,
            ) / completed
          : undefined;
      const weightedMetric = (
        key:
          | "average_cpu_utilization"
          | "average_memory_utilization"
          | "average_worker_utilization",
      ) => {
        const measured = rows.filter(
          (row) =>
            typeof row[key] === "number" &&
            typeof row.elapsed_s === "number" &&
            row.elapsed_s > 0,
        );
        const measuredElapsed = measured.reduce(
          (total, row) => total + (row.elapsed_s ?? 0),
          0,
        );
        return measuredElapsed > 0
          ? measured.reduce(
              (total, row) =>
                total + (row[key] ?? 0) * (row.elapsed_s ?? 0),
              0,
            ) / measuredElapsed
          : undefined;
      };
      return {
        algorithm,
        trials: rows.length,
        completed,
        failed,
        timedOut,
        elapsed,
        averageLatency,
        throughput: elapsed > 0 ? completed / elapsed : undefined,
        averageCpuUtilization: weightedMetric("average_cpu_utilization"),
        averageMemoryUtilization: weightedMetric(
          "average_memory_utilization",
        ),
        averageWorkerUtilization: weightedMetric(
          "average_worker_utilization",
        ),
      };
    })
    .filter((summary): summary is NonNullable<typeof summary> => summary !== null);
}

function App() {
  const [page, setPage] = useState<Page>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [lastSuccessfulCheck, setLastSuccessfulCheck] = useState<Date | null>(
    null,
  );
  const [connectionError, setConnectionError] = useState("");
  const [form, setForm] = useState<ExperimentRequest>(initialForm);
  const [formValues, setFormValues] = useState({
    concurrency: String(initialForm.concurrency),
    repetitions: String(initialForm.repetitions),
  });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [latestExperiment, setLatestExperiment] =
    useState<SavedExperiment | null>(null);
  const [history, setHistory] = useState<SavedExperiment[]>([]);
  const healthRequestActive = useRef(false);
  const runRequestActive = useRef(false);

  const refreshHealth = useCallback(async () => {
    if (healthRequestActive.current) return;
    healthRequestActive.current = true;
    try {
      await checkHealth();
      setConnection("connected");
      setConnectionError("");
      setLastSuccessfulCheck(new Date());
    } catch (error) {
      setConnection("disconnected");
      setConnectionError(errorMessage(error));
    } finally {
      healthRequestActive.current = false;
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const interval = window.setInterval(() => void refreshHealth(), 15_000);
    return () => window.clearInterval(interval);
  }, [refreshHealth]);

  function updatePage(nextPage: Page) {
    setPage(nextPage);
    setMobileNavOpen(false);
    setDownloadError("");
  }

  function updateConcurrency(value: string) {
    setFormValues((current) => ({ ...current, concurrency: value }));
    setFormErrors((current) => ({ ...current, concurrency: "" }));
  }

  function updateRepetitions(value: string) {
    setFormValues((current) => ({ ...current, repetitions: value }));
    setFormErrors((current) => ({ ...current, repetitions: "" }));
  }

  function validateForm(): ExperimentRequest | null {
    const errors: Record<string, string> = {};
    const concurrency = Number(formValues.concurrency);
    const repetitions = Number(formValues.repetitions);
    if (
      formValues.concurrency.trim() === "" ||
      !Number.isInteger(concurrency) ||
      concurrency < 1 ||
      concurrency > 200
    ) {
      errors.concurrency = "Enter a whole number from 1 to 200.";
    }
    if (
      formValues.repetitions.trim() === "" ||
      !Number.isInteger(repetitions) ||
      repetitions < 1 ||
      repetitions > 20
    ) {
      errors.repetitions = "Enter a whole number from 1 to 20.";
    }
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return null;
    return { ...form, concurrency, repetitions };
  }

  async function submitExperiment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (runRequestActive.current) return;
    const configuration = validateForm();
    if (!configuration) return;

    runRequestActive.current = true;
    setIsRunning(true);
    setRunError("");
    setDownloadError("");
    try {
      const result = await runExperiment(configuration);
      const saved: SavedExperiment = {
        id: Date.now(),
        completedAt: new Date().toISOString(),
        request: configuration,
        result,
      };
      setLatestExperiment(saved);
      setHistory((current) => [saved, ...current].slice(0, 8));
    } catch (error) {
      setRunError(errorMessage(error));
    } finally {
      runRequestActive.current = false;
      setIsRunning(false);
    }
  }

  async function exportCsv(kind: "tasks" | "summary" | "diagnostics" | "dynamic") {
    if (!latestExperiment) return;
    setDownloadError("");
    const url =
      kind === "tasks"
        ? latestExperiment.result.task_csv_url
        : kind === "summary"
          ? latestExperiment.result.summary_csv_url
          : kind === "diagnostics"
            ? latestExperiment.result.diagnostic_csv_url
            : latestExperiment.result.dynamic_steps_csv_url;
    if (!url) {
      setDownloadError(
        "This backend response did not include a CSV download link.",
      );
      return;
    }
    try {
      await downloadCsv(url);
    } catch (error) {
      setDownloadError(`CSV download failed: ${errorMessage(error)}`);
    }
  }

  const pageTitles: Record<Page, string> = {
    overview: "Research overview",
    experiment: "Experiment lab",
    tasks: "Task monitor",
    insights: "Algorithm insights",
    project: "Project information",
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <Activity size={21} strokeWidth={2.2} />
          </div>
          <div>
            <div className="brand-title">Fieldwork</div>
            <div className="brand-caption">Research workspace</div>
          </div>
          <button
            className="icon-button sidebar-close"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${page === id ? "nav-item-active" : ""}`}
              onClick={() => updatePage(id)}
              aria-current={page === id ? "page" : undefined}
            >
              <Icon size={18} strokeWidth={1.9} />
              <span>{label}</span>
              {id === "experiment" && <span className="nav-badge">LAB</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-note-icon"><Info size={16} /></div>
          <div>
            <strong>Prototype environment</strong>
            <p>Local task processing, not a live GIS service.</p>
          </div>
        </div>
      </aside>

      {mobileNavOpen && (
        <button
          className="mobile-scrim"
          aria-label="Close navigation"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button mobile-menu"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <div className="breadcrumb">
              <span>Adaptive GIS Traffic Shaping</span>
              <span className="breadcrumb-slash">/</span>
              <strong>{pageTitles[page]}</strong>
            </div>
          </div>
          <div className="topbar-right">
            <div
              className={`connection-pill connection-${connection}`}
              role="status"
              aria-live="polite"
              title={
                connection === "disconnected"
                  ? connectionError
                  : `API: ${getApiBaseUrl()}`
              }
            >
              <span className="connection-dot" />
              {connection === "checking"
                ? "Checking API"
                : connection === "connected"
                  ? "API connected"
                  : "API disconnected"}
            </div>
            <span className="last-check">
              {lastSuccessfulCheck
                ? `Checked ${lastSuccessfulCheck.toLocaleTimeString()}`
                : "No successful check yet"}
            </span>
            <button
              className="icon-button refresh-button"
              onClick={() => void refreshHealth()}
              aria-label="Refresh backend connection"
              title="Check backend connection"
              disabled={connection === "checking"}
            >
              <RefreshCw
                size={16}
                className={connection === "checking" ? "spin" : ""}
              />
            </button>
          </div>
        </header>

        {connection === "disconnected" && (
          <div className="connection-banner" role="status">
            <AlertCircle size={17} />
            <div>
              <strong>Backend unavailable.</strong> Start FastAPI from the
              backend folder with{" "}
              <code>uvicorn main:app --reload --port 8000</code>.{" "}
              <span>{connectionError}</span>
            </div>
          </div>
        )}

        <main className="content">
          {page === "overview" && (
            <OverviewPage
              connection={connection}
              history={history}
              latestExperiment={latestExperiment}
              onNavigate={updatePage}
            />
          )}
          {page === "experiment" && (
            <ExperimentPage
              form={form}
              setForm={setForm}
              formValues={formValues}
              formErrors={formErrors}
              updateConcurrency={updateConcurrency}
              updateRepetitions={updateRepetitions}
              onSubmit={submitExperiment}
              isRunning={isRunning}
              runError={runError}
              latestExperiment={latestExperiment}
              onClearResults={() => setLatestExperiment(null)}
              onExport={exportCsv}
              downloadError={downloadError}
            />
          )}
          {page === "tasks" && (
            <TaskMonitorPage experiment={latestExperiment} />
          )}
          {page === "insights" && <InsightsPage />}
          {page === "project" && <ProjectPage />}
        </main>

        <footer className="app-footer">
          <span>Adaptive GIS Traffic Shaping</span>
          <span>Research prototype · measurements are generated on demand</span>
        </footer>
      </div>
    </div>
  );
}

interface OverviewPageProps {
  connection: ConnectionState;
  history: SavedExperiment[];
  latestExperiment: SavedExperiment | null;
  onNavigate: (page: Page) => void;
}

function OverviewPage({
  connection,
  history,
  latestExperiment,
  onNavigate,
}: OverviewPageProps) {
  const executedTasks = latestExperiment
    ? latestExperiment.result.task_results.length
    : undefined;
  const runCompleted =
    latestExperiment?.result.summaries.reduce(
      (total, row) => total + (row.completed_tasks ?? 0),
      0,
    ) ?? 0;
  const runElapsed =
    latestExperiment?.result.summaries.reduce(
      (total, row) => total + (row.elapsed_s ?? 0),
      0,
    ) ?? 0;
  const recentExperiments = history.slice(0, 5);

  return (
    <>
      <PageHeading
        eyebrow="PROTOTYPE STATUS"
        title="Research overview"
        description="A live view of the benchmark service and the most recent measurements from this browser session."
        action={
          <button
            className="button button-primary"
            onClick={() => onNavigate("experiment")}
          >
            <FlaskConical size={17} />
            Open experiment lab
          </button>
        }
      />

      <section className="overview-banner">
        <div className="overview-banner-icon"><Gauge size={22} /></div>
        <div className="overview-banner-copy">
          <span className="eyebrow">CURRENT PROTOTYPE</span>
          <h2>Measure traffic shaping with real benchmark runs</h2>
          <p>
            Configure a workload, run the backend benchmark, and inspect
            measured trial and task data. No live GIS service is connected.
          </p>
        </div>
        <div className="banner-state">
          <span className={`state-dot state-${connection}`} />
          {connection === "connected"
            ? "Benchmark API available"
            : connection === "checking"
              ? "Checking benchmark API"
              : "Waiting for benchmark API"}
        </div>
      </section>

      <div className="section-heading">
        <div>
          <h2>Runtime metrics</h2>
          <p>Only values available from the API or latest completed run.</p>
        </div>
        {latestExperiment && (
          <span className="muted-inline">
            Latest run · {new Date(latestExperiment.completedAt).toLocaleString()}
          </span>
        )}
      </div>

      <section className="metric-grid">
        <MetricCard
          label="CPU utilization"
          value="Unavailable"
          detail="Requires a live system-metrics endpoint."
          icon={Activity}
          unavailable
        />
        <MetricCard
          label="Memory utilization"
          value="Unavailable"
          detail="Requires a live system-metrics endpoint."
          icon={Gauge}
          unavailable
        />
        <MetricCard
          label="Current system load"
          value="Unavailable"
          detail="Not included in the benchmark response."
          icon={Activity}
          unavailable
        />
        <MetricCard
          label="Current adaptive token rate"
          value="Unavailable"
          detail="Controller trace values are not returned."
          icon={Settings2}
          unavailable
        />
        <MetricCard
          label="Current queue length"
          value="Unavailable"
          detail="No live task-queue endpoint is available."
          icon={ListChecks}
          unavailable
        />
        <MetricCard
          label="Task executions"
          value={
            typeof executedTasks === "number"
              ? executedTasks.toLocaleString()
              : "—"
          }
          detail={
            typeof executedTasks === "number"
              ? "Measured in the latest benchmark response."
              : "Run an experiment to populate this metric."
          }
          icon={CheckCircle2}
          unavailable={typeof executedTasks !== "number"}
        />
        <MetricCard
          label="Current HMM RateRank"
          value="Unavailable"
          detail="The API does not expose per-update HMM state."
          icon={Info}
          unavailable
        />
        <MetricCard
          label="Latest run throughput"
          value={
            runElapsed > 0
              ? `${formatNumber(runCompleted / runElapsed)} tasks/s`
              : "—"
          }
          detail="All completed task executions / summed trial elapsed time."
          icon={Activity}
          unavailable={runElapsed <= 0}
        />
      </section>

      <div className="section-heading section-heading-spaced">
        <div>
          <h2>Recent experiments</h2>
          <p>Successful runs stored for this browser session only.</p>
        </div>
        <button
          className="button button-secondary button-small"
          onClick={() => onNavigate("experiment")}
        >
          View experiment lab
        </button>
      </div>
      {recentExperiments.length > 0 ? (
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>Run time</th>
                <th>Scenario</th>
                <th>Concurrency</th>
                <th>Repetitions</th>
                <th>Comparison</th>
                <th>Tasks measured</th>
              </tr>
            </thead>
            <tbody>
              {recentExperiments.map((experiment) => (
                <tr key={experiment.id}>
                  <td>{new Date(experiment.completedAt).toLocaleTimeString()}</td>
                  <td>{scenarioLabels[experiment.request.scenario]}</td>
                  <td>{experiment.request.concurrency}</td>
                  <td>{experiment.request.repetitions}</td>
                  <td>{experiment.request.comparison}</td>
                  <td>{experiment.result.task_results.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon={Clock3}
          title="No experiment runs in this session"
          description="Successful benchmark runs will appear here. This list is not backend-persisted."
          action={
            <button
              className="button button-primary button-small"
              onClick={() => onNavigate("experiment")}
            >
              Configure a run
            </button>
          }
        />
      )}
    </>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  detail: string;
  icon: typeof Activity;
  unavailable?: boolean;
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  unavailable = false,
}: MetricCardProps) {
  return (
    <article className="metric-card">
      <div className="metric-card-top">
        <span>{label}</span>
        <div className="metric-icon"><Icon size={17} /></div>
      </div>
      <strong className={unavailable ? "metric-unavailable" : ""}>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

interface ExperimentPageProps {
  form: ExperimentRequest;
  setForm: React.Dispatch<React.SetStateAction<ExperimentRequest>>;
  formValues: { concurrency: string; repetitions: string };
  formErrors: Record<string, string>;
  updateConcurrency: (value: string) => void;
  updateRepetitions: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  isRunning: boolean;
  runError: string;
  latestExperiment: SavedExperiment | null;
  onClearResults: () => void;
  onExport: (kind: "tasks" | "summary" | "diagnostics" | "dynamic") => void;
  downloadError: string;
}

function ExperimentPage({
  form,
  setForm,
  formValues,
  formErrors,
  updateConcurrency,
  updateRepetitions,
  onSubmit,
  isRunning,
  runError,
  latestExperiment,
  onClearResults,
  onExport,
  downloadError,
}: ExperimentPageProps) {
  return (
    <>
      <PageHeading
        eyebrow="BENCHMARK CONFIGURATION"
        title="Experiment lab"
        description="Set the workload and comparison, then execute the real Python benchmark."
      />

      <div className="experiment-layout">
        <section className="panel configuration-panel">
          <div className="panel-heading">
            <div className="panel-heading-icon"><Settings2 size={18} /></div>
            <div>
              <h2>Run configuration</h2>
              <p>Settings are sent directly to the FastAPI benchmark.</p>
            </div>
          </div>
          <form onSubmit={onSubmit} noValidate>
            <label className="field-label" htmlFor="scenario">
              Workload scenario
            </label>
            <div className="select-wrap">
              <select
                id="scenario"
                value={form.scenario}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    scenario: event.target.value as Scenario,
                  }))
                }
              >
                {Object.entries(scenarioLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </div>
            <p className="field-hint">{scenarioDescriptions[form.scenario]}</p>

            <label className="field-label" htmlFor="concurrency">
              Concurrency
            </label>
            <div className="input-with-suffix">
              <input
                id="concurrency"
                type="number"
                min={1}
                max={200}
                step={1}
                inputMode="numeric"
                value={formValues.concurrency}
                onChange={(event) => updateConcurrency(event.target.value)}
                aria-invalid={Boolean(formErrors.concurrency)}
                aria-describedby={
                  formErrors.concurrency
                    ? "concurrency-error concurrency-hint"
                    : "concurrency-hint"
                }
              />
              <span>requests</span>
            </div>
            <div className="preset-row" aria-label="Concurrency presets">
              <span>Presets</span>
              {[10, 20, 50].map((value) => (
                <button
                  type="button"
                  key={value}
                  className={`preset-button ${
                    formValues.concurrency === String(value)
                      ? "preset-active"
                      : ""
                  }`}
                  onClick={() => updateConcurrency(String(value))}
                >
                  {value}
                </button>
              ))}
            </div>
            {formErrors.concurrency ? (
              <p className="field-error" id="concurrency-error">
                {formErrors.concurrency}
              </p>
            ) : (
              <p className="field-hint" id="concurrency-hint">
                Whole number from 1 to 200.
              </p>
            )}

            <label className="field-label" htmlFor="repetitions">
              Repetitions
            </label>
            <div className="input-with-suffix">
              <input
                id="repetitions"
                type="number"
                min={1}
                max={20}
                step={1}
                inputMode="numeric"
                value={formValues.repetitions}
                onChange={(event) => updateRepetitions(event.target.value)}
                aria-invalid={Boolean(formErrors.repetitions)}
                aria-describedby={
                  formErrors.repetitions ? "repetitions-error" : "repetitions-hint"
                }
              />
              <span>trials / algorithm</span>
            </div>
            {formErrors.repetitions ? (
              <p className="field-error" id="repetitions-error">
                {formErrors.repetitions}
              </p>
            ) : (
              <p className="field-hint" id="repetitions-hint">
                Whole number from 1 to 20.
              </p>
            )}

            <label className="field-label" htmlFor="classical-rate-mode">
              Classical rate selection
            </label>
            <div className="select-wrap">
              <select
                id="classical-rate-mode"
                value={form.classical_rate_mode ?? "auto"}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  classical_rate_mode: event.target.value === "auto"
                    ? undefined
                    : event.target.value as ExperimentRequest["classical_rate_mode"],
                }))}
              >
                <option value="auto">Automatic: cached measurement or paper preset</option>
                <option value="paper_preset">Paper preset</option>
                <option value="measured">Measured optimal rate</option>
                <option value="manual">Manual rate</option>
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </div>
            {form.classical_rate_mode === "manual" && (
              <div className="input-with-suffix">
                <input
                  aria-label="Manual classical token rate"
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.classical_rate ?? 150}
                  onChange={(event) => setForm((current) => ({
                    ...current,
                    classical_rate: Number(event.target.value),
                  }))}
                />
                <span>tokens/s</span>
              </div>
            )}
            <p className="field-hint">
              Measured mode uses the cached result from the optimal-rate probe.
            </p>

            <label className="field-label" htmlFor="load-scope">Load measurement scope</label>
            <div className="select-wrap">
              <select
                id="load-scope"
                value={form.load_scope ?? "process"}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  load_scope: event.target.value as "process" | "host",
                }))}
              >
                <option value="process">Benchmark process (paper prototype default)</option>
                <option value="host">Whole host (diagnostic comparison)</option>
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </div>

            <label className="radio-card">
              <input
                type="checkbox"
                checked={form.contention_model ?? true}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  contention_model: event.target.checked,
                }))}
              />
              <span className="radio-indicator" />
              <span className="radio-copy">
                <strong>Simulated CPU contention</strong>
                <small>{form.contention_model === false ? "Off · plain duration sleeps" : "On · processor-sharing simulation"}</small>
              </span>
            </label>
            {form.scenario === "dynamic" && (
              <label className="field-label" htmlFor="envelope-speedup">
                Daily envelope speedup
                <input
                  id="envelope-speedup"
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.speedup ?? 1}
                  onChange={(event) => setForm((current) => ({
                    ...current,
                    speedup: Number(event.target.value),
                  }))}
                />
              </label>
            )}

            <fieldset className="comparison-fieldset">
              <legend>Algorithm comparison</legend>
              <label className="radio-card">
                <input
                  type="radio"
                  name="comparison"
                  value="both"
                  checked={form.comparison === "both"}
                  onChange={() =>
                    setForm((current) => ({ ...current, comparison: "both" }))
                  }
                />
                <span className="radio-indicator" />
                <span className="radio-copy">
                  <strong>Compare both</strong>
                  <small>Classical and adaptive token buckets</small>
                </span>
                <span className="algorithm-mark both-mark">C + A</span>
              </label>
              <label className="radio-card">
                <input
                  type="radio"
                  name="comparison"
                  value="classical"
                  checked={form.comparison === "classical"}
                  onChange={() =>
                    setForm((current) => ({
                      ...current,
                      comparison: "classical",
                    }))
                  }
                />
                <span className="radio-indicator" />
                <span className="radio-copy">
                  <strong>Classical only</strong>
                  <small>Fixed-rate token bucket baseline</small>
                </span>
                <span className="algorithm-mark classical-mark">C</span>
              </label>
              <label className="radio-card">
                <input
                  type="radio"
                  name="comparison"
                  value="adaptive"
                  checked={form.comparison === "adaptive"}
                  onChange={() =>
                    setForm((current) => ({
                      ...current,
                      comparison: "adaptive",
                    }))
                  }
                />
                <span className="radio-indicator" />
                <span className="radio-copy">
                  <strong>Adaptive only</strong>
                  <small>Load-aware adaptive rate controller</small>
                </span>
                <span className="algorithm-mark adaptive-mark">A</span>
              </label>
            </fieldset>

            <div className="estimate-note">
              <Info size={16} />
              <span>
                A run is synchronous and may take time. Results remain visible
                until the next successful run or you clear them.
              </span>
            </div>

            <button
              className="button button-primary run-button"
              type="submit"
              disabled={isRunning}
            >
              {isRunning ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <Play size={17} fill="currentColor" />
              )}
              {isRunning ? "Benchmark running…" : "Run experiment"}
            </button>
            {isRunning && (
              <div className="running-state" role="status" aria-live="polite">
                <span className="indeterminate-bar" />
                <span>Running benchmark and measuring task execution…</span>
              </div>
            )}
            {runError && (
              <div className="alert alert-error" role="alert">
                <AlertCircle size={17} />
                <span>{runError}</span>
              </div>
            )}
          </form>
        </section>

        <div className="lab-results">
          {latestExperiment ? (
            <ExperimentResults
              experiment={latestExperiment}
              onClear={onClearResults}
              onExport={onExport}
              downloadError={downloadError}
            />
          ) : (
            <EmptyState
              className="lab-empty"
              icon={FlaskConical}
              title="Results will appear here"
              description="Choose the workload and algorithms, then run an experiment to populate trial comparisons and measured task records."
            />
          )}
        </div>
      </div>
      <ConcurrencySweepPanel
        scenario={form.scenario}
        repetitions={form.repetitions}
        comparison={form.comparison}
        disabled={isRunning}
      />
    </>
  );
}

interface ExperimentResultsProps {
  experiment: SavedExperiment;
  onClear: () => void;
  onExport: (kind: "tasks" | "summary" | "diagnostics" | "dynamic") => void;
  downloadError: string;
}

function ExperimentResults({
  experiment,
  onClear,
  onExport,
  downloadError,
}: ExperimentResultsProps) {
  const { result, request } = experiment;
  const algorithmSummaries = summarizeAlgorithms(result.summaries);
  const twoAlgorithms = result.algorithms.includes("classical") &&
    result.algorithms.includes("adaptive");

  return (
    <section className="results-section" aria-label="Experiment results">
      <div className="results-title-row">
        <div>
          <div className="eyebrow">COMPLETED · {new Date(experiment.completedAt).toLocaleTimeString()}</div>
          <h2>Benchmark results</h2>
          <p>
            {scenarioLabels[request.scenario]} · {request.concurrency} requests
            · {request.repetitions} repetitions · {request.comparison}
          </p>
        </div>
        <button
          className="icon-button clear-results-button"
          onClick={onClear}
          aria-label="Clear current results"
          title="Clear current results"
        >
          <X size={17} />
        </button>
      </div>

      <div className="results-toolbar">
        <span>
          <CheckCircle2 size={16} />
          {result.summaries.length} trial summaries · {result.task_results.length} task records
        </span>
        <div className="toolbar-actions">
          <button
            className="button button-secondary button-small"
            onClick={() => onExport("tasks")}
          >
            <Download size={15} /> Task CSV
          </button>
          <button
            className="button button-secondary button-small"
            onClick={() => onExport("summary")}
          >
            <Download size={15} /> Summary CSV
          </button>
          <button
            className="button button-secondary button-small"
            onClick={() => onExport("diagnostics")}
            disabled={!result.diagnostic_csv_url}
          >
            <Download size={15} /> Controller diagnostics
          </button>
          {result.dynamic_steps_csv_url && (
            <button className="button button-secondary button-small" onClick={() => onExport("dynamic")}>
              <Download size={15} /> Dynamic step CSV
            </button>
          )}
        </div>
      </div>
      {downloadError && (
        <div className="alert alert-error compact-alert" role="alert">
          <AlertCircle size={16} /> <span>{downloadError}</span>
        </div>
      )}

      {algorithmSummaries.length > 0 && (
        <section className="summary-cards" aria-label="Measured algorithm summary">
          {algorithmSummaries.map((summary) => (
            <article
              className={`algorithm-summary-card algorithm-${summary.algorithm}`}
              key={summary.algorithm}
            >
              <div className="algorithm-summary-title">
                <span className={`algorithm-dot dot-${summary.algorithm}`} />
                <h3>{algorithmLabels[summary.algorithm]}</h3>
                <span className="trial-count">{summary.trials} trials</span>
              </div>
              <div className="summary-stat-grid">
                <SummaryStat
                  label="Mean trial latency"
                  value={`${formatNumber(summary.averageLatency)} ms`}
                  note="Completion-weighted mean across trials"
                />
                <SummaryStat
                  label="Aggregate throughput"
                  value={`${formatNumber(summary.throughput)} tasks/s`}
                  note="Completed executions / total elapsed"
                />
                <SummaryStat
                  label="Completed tasks"
                  value={summary.completed.toLocaleString()}
                  note="Sum across completed trials"
                />
                <SummaryStat
                  label="Elapsed wall time"
                  value={`${formatNumber(summary.elapsed)} s`}
                  note="Sum of backend trial elapsed times"
                />
                <SummaryStat
                  label="Failed tasks"
                  value={summary.failed.toLocaleString()}
                  note="Not included in completed-task throughput"
                />
                <SummaryStat
                  label="Timed out tasks"
                  value={summary.timedOut.toLocaleString()}
                  note="Admission timeout; not included in throughput"
                />
                <SummaryStat
                  label="Average CPU utilization"
                  value={
                    summary.averageCpuUtilization === undefined
                      ? "Unavailable"
                      : `${formatNumber(summary.averageCpuUtilization * 100)}%`
                  }
                  note="Sampled system CPU; not worker utilization"
                />
                <SummaryStat
                  label="Average memory utilization"
                  value={
                    summary.averageMemoryUtilization === undefined
                      ? "Unavailable"
                      : `${formatNumber(summary.averageMemoryUtilization * 100)}%`
                  }
                  note="Sampled system memory"
                />
                <SummaryStat
                  label="Average worker utilization"
                  value={
                    summary.averageWorkerUtilization === undefined
                      ? "Unavailable"
                      : `${formatNumber(summary.averageWorkerUtilization * 100)}%`
                  }
                  note="Active workers / configured workers"
                />
              </div>
            </article>
          ))}
        </section>
      )}

      {result.summaries.length === 0 ? (
        <EmptyState
          icon={CircleHelp}
          title="No trial summaries returned"
          description="The backend completed the request but provided no summary rows."
        />
      ) : (
        <>
          {twoAlgorithms && (
            <ComparisonCharts summaries={result.summaries} />
          )}
          {result.rate_diagnostics && result.rate_diagnostics.length > 0 && (
            <RateTraceChart diagnostics={result.rate_diagnostics} />
          )}
          {result.dynamic_steps && result.dynamic_steps.length > 0 && (
            <DynamicTrafficCharts
              steps={result.dynamic_steps}
              relative={result.dynamic_relative_differences ?? null}
            />
          )}
          {!twoAlgorithms && (
            <div className="single-algorithm-note">
              <Info size={16} />
              This run includes {displayAlgorithm(result.algorithms[0])} only;
              there is no second algorithm to compare.
            </div>
          )}
          <TrialTable summaries={result.summaries} />
        </>
      )}

      {result.task_results.length > 0 ? (
        <TaskResultsTable
          tasks={result.task_results}
          algorithms={result.algorithms}
        />
      ) : (
        <EmptyState
          icon={ListChecks}
          title="No task measurements returned"
          description="Task-level measurements are empty in this benchmark response."
        />
      )}
    </section>
  );
}

function RateTraceChart({
  diagnostics,
}: {
  diagnostics: NonNullable<SavedExperiment["result"]["rate_diagnostics"]>;
}) {
  const adaptive = diagnostics.filter((row) => row.algorithm === "adaptive");
  const trials = [...new Set(adaptive.map((row) => row.trial).filter((value): value is number => typeof value === "number"))];
  const [trial, setTrial] = useState(trials[0] ?? 1);
  const data = adaptive
    .filter((row) => row.trial === trial)
    .sort((a, b) => (a.elapsed_s ?? 0) - (b.elapsed_s ?? 0));
  return (
    <section className="charts-section">
      <div className="section-heading">
        <div><h3>Adaptive token-rate trace</h3><p>Rate updates with the active minimum and maximum bounds.</p></div>
        {trials.length > 1 && (
          <label>Trial <select value={trial} onChange={(event) => setTrial(Number(event.target.value))}>
            {trials.map((value) => <option key={value} value={value}>{value}</option>)}
          </select></label>
        )}
      </div>
      <ChartPanel title={`Rate trace · trial ${trial}`} subtitle="Tokens per second against elapsed trial time">
        {data.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid stroke="#e5edf2" vertical={false} />
              <XAxis dataKey="elapsed_s" tickFormatter={(value) => `${Number(value).toFixed(1)}s`} />
              <YAxis width={48} />
              <Tooltip formatter={(value) => [`${formatNumber(Number(value))} tokens/s`]} />
              <Legend />
              <Line type="stepAfter" dataKey="applied_rate" name="Applied rate" stroke="#438fc2" strokeWidth={2.5} dot={false} />
              <Line type="stepAfter" dataKey="minimum_rate" name="Minimum rate" stroke="#bc6c55" strokeDasharray="5 4" dot={false} />
              <Line type="stepAfter" dataKey="maximum_rate" name="Maximum rate" stroke="#789781" strokeDasharray="5 4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : <ChartEmpty />}
      </ChartPanel>
    </section>
  );
}

function DynamicTrafficCharts({
  steps,
  relative,
}: {
  steps: NonNullable<SavedExperiment["result"]["dynamic_steps"]>;
  relative: SavedExperiment["result"]["dynamic_relative_differences"];
}) {
  const rows = useMemo(() => {
    const byStep = new Map<number, Record<string, number>>();
    for (const row of steps) {
      const point = byStep.get(row.step) ?? { step: row.step, concurrency: row.concurrency };
      if (row.mean_latency_ms !== undefined) point[`${row.algorithm}_latency`] = row.mean_latency_ms;
      if (row.p90_latency_ms !== undefined) point[`${row.algorithm}_p90`] = row.p90_latency_ms;
      if (row.throughput_tasks_per_s !== undefined) point[`${row.algorithm}_throughput`] = row.throughput_tasks_per_s;
      byStep.set(row.step, point);
    }
    return [...byStep.values()].sort((a, b) => a.step - b.step);
  }, [steps]);
  return (
    <section className="charts-section">
      <div className="section-heading"><div><h3>Dynamic traffic · 70 steps</h3><p>Periodic mixed-workload bursts with a sinusoidal concurrency stand-in.</p></div></div>
      {relative && (
        <div className="summary-cards">
          <SummaryStat label="Latency relative difference" value={`${formatNumber((relative.mean_latency_relative_difference ?? 0) * 100)}%`} note="(classical − adaptive) / classical; positive favors adaptive" />
          <SummaryStat label="P90 relative difference" value={`${formatNumber((relative.mean_p90_relative_difference ?? 0) * 100)}%`} note="Mean of paired step differences" />
          <SummaryStat label="Throughput relative difference" value={`${formatNumber((relative.mean_throughput_relative_difference ?? 0) * 100)}%`} note="(adaptive − classical) / classical; positive favors adaptive" />
        </div>
      )}
      <div className="chart-grid">
        <DynamicMetricChart title="Mean latency" data={rows} suffix="latency" unit="ms" />
        <DynamicMetricChart title="P90 latency" data={rows} suffix="p90" unit="ms" />
        <DynamicMetricChart title="Throughput" data={rows} suffix="throughput" unit="tasks/s" />
      </div>
    </section>
  );
}

function DynamicMetricChart({
  title,
  data,
  suffix,
  unit,
}: {
  title: string;
  data: Record<string, number>[];
  suffix: string;
  unit: string;
}) {
  return (
    <ChartPanel title={title} subtitle={`Per-step measurements · ${unit}`}>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 8, right: 10, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="#e5edf2" vertical={false} />
          <XAxis dataKey="step" />
          <YAxis width={48} />
          <Tooltip formatter={(value) => [`${formatNumber(Number(value))} ${unit}`]} />
          <Legend />
          {(["classical", "adaptive"] as const).map((algorithm) => (
            <Line key={algorithm} type="monotone" dataKey={`${algorithm}_${suffix}`} name={algorithmLabels[algorithm]} stroke={colors[algorithm]} strokeWidth={2} dot={false} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

function SummaryStat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="summary-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

function ComparisonCharts({ summaries }: { summaries: TrialSummary[] }) {
  const chartData = useMemo(() => {
    const byTrial = new Map<number, Record<string, number>>();
    for (const summary of summaries) {
      if (
        typeof summary.trial !== "number" ||
        (summary.algorithm !== "classical" &&
          summary.algorithm !== "adaptive")
      ) {
        continue;
      }
      const point = byTrial.get(summary.trial) ?? { trial: summary.trial };
      if (typeof summary.average_latency_ms === "number") {
        point[`${summary.algorithm}_latency`] = summary.average_latency_ms;
      }
      if (typeof summary.throughput_tasks_per_s === "number") {
        point[`${summary.algorithm}_throughput`] =
          summary.throughput_tasks_per_s;
      }
      byTrial.set(summary.trial, point);
    }
    return [...byTrial.values()].sort((left, right) => left.trial - right.trial);
  }, [summaries]);
  const hasLatency = chartData.some(
    (row) =>
      typeof row.classical_latency === "number" ||
      typeof row.adaptive_latency === "number",
  );
  const hasThroughput = chartData.some(
    (row) =>
      typeof row.classical_throughput === "number" ||
      typeof row.adaptive_throughput === "number",
  );

  return (
    <section className="charts-section">
      <div className="section-heading">
        <div>
          <h3>Trial-by-trial comparison</h3>
          <p>Charts use the measurements returned for each completed trial.</p>
        </div>
      </div>
      <div className="chart-grid">
        <ChartPanel
          title="Average latency by trial"
          subtitle="Measured mean task latency · milliseconds"
        >
          {hasLatency ? (
            <ResponsiveContainer width="100%" height={245}>
              <BarChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 2 }}>
                <CartesianGrid stroke="#e5edf2" vertical={false} />
                <XAxis dataKey="trial" tickFormatter={(value) => `Trial ${value}`} />
                <YAxis width={44} />
                <Tooltip
                  formatter={(value) => [`${formatNumber(Number(value))} ms`]}
                  labelFormatter={(value) => `Trial ${value}`}
                />
                <Legend />
                <Bar
                  dataKey="classical_latency"
                  name="Adaptive"
                  fill={colors.classical}
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="adaptive_latency"
                  name="Classical"
                  fill={colors.adaptive}
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <ChartEmpty />
          )}
        </ChartPanel>
        <ChartPanel
          title="Throughput by trial"
          subtitle="Completed tasks per second · higher is not always lower latency"
        >
          {hasThroughput ? (
            <ResponsiveContainer width="100%" height={245}>
              <BarChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 2 }}>
                <CartesianGrid stroke="#e5edf2" vertical={false} />
                <XAxis dataKey="trial" tickFormatter={(value) => `Trial ${value}`} />
                <YAxis width={44} />
                <Tooltip
                  formatter={(value) => [`${formatNumber(Number(value))} tasks/s`]}
                  labelFormatter={(value) => `Trial ${value}`}
                />
                <Legend />
                <Bar
                  dataKey="classical_throughput"
                  name="Adaptive"
                  fill={colors.classical}
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="adaptive_throughput"
                  name="Classical"
                  fill={colors.adaptive}
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <ChartEmpty />
          )}
        </ChartPanel>
        <ChartPanel
          title="Latency across trials"
          subtitle="Actual per-trial average latency · milliseconds"
        >
          {hasLatency ? (
            <ResponsiveContainer width="100%" height={235}>
              <LineChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 2 }}>
                <CartesianGrid stroke="#e5edf2" vertical={false} />
                <XAxis dataKey="trial" tickFormatter={(value) => `Trial ${value}`} />
                <YAxis width={44} />
                <Tooltip
                  formatter={(value) => [`${formatNumber(Number(value))} ms`]}
                  labelFormatter={(value) => `Trial ${value}`}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="classical_latency"
                  name="Adaptive"
                  stroke={colors.classical}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
                <Line
                  type="monotone"
                  dataKey="adaptive_latency"
                  name="Classical"
                  stroke={colors.adaptive}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <ChartEmpty />
          )}
        </ChartPanel>
        <ChartPanel
          title="Throughput across trials"
          subtitle="Actual per-trial throughput · tasks per second"
        >
          {hasThroughput ? (
            <ResponsiveContainer width="100%" height={235}>
              <LineChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 2 }}>
                <CartesianGrid stroke="#e5edf2" vertical={false} />
                <XAxis dataKey="trial" tickFormatter={(value) => `Trial ${value}`} />
                <YAxis width={44} />
                <Tooltip
                  formatter={(value) => [`${formatNumber(Number(value))} tasks/s`]}
                  labelFormatter={(value) => `Trial ${value}`}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="classical_throughput"
                  name="Adaptive"
                  stroke={colors.classical}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
                <Line
                  type="monotone"
                  dataKey="adaptive_throughput"
                  name="Classical"
                  stroke={colors.adaptive}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <ChartEmpty />
          )}
        </ChartPanel>
      </div>
      <p className="chart-footnote">
        Missing values are left blank; the charts do not interpolate across
        absent trial measurements.
      </p>
    </section>
  );
}

function ChartPanel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <article className="chart-panel">
      <h4>{title}</h4>
      <p>{subtitle}</p>
      {children}
    </article>
  );
}

function ChartEmpty() {
  return (
    <div className="chart-empty">
      <span>Chart unavailable</span>
      <small>No valid measurements were returned for this metric.</small>
    </div>
  );
}

function TrialTable({ summaries }: { summaries: TrialSummary[] }) {
  return (
    <section className="data-section">
      <div className="section-heading">
        <div>
          <h3>Trial summaries</h3>
          <p>One row per algorithm trial; failed tasks are reported separately.</p>
        </div>
      </div>
      <div className="table-shell">
        <table>
          <thead>
            <tr>
              <th>Algorithm</th>
              <th>Trial</th>
              <th>Scenario</th>
              <th>Concurrency</th>
              <th>Completed tasks</th>
              <th>Failed tasks</th>
              <th>Timed out tasks</th>
              <th>Elapsed (s)</th>
              <th>Avg latency (ms)</th>
              <th>p95 latency (ms)</th>
              <th>p90 latency (ms)</th>
              <th>Classical rate</th>
              <th>Rate mode</th>
              <th>Idle rate N</th>
              <th>Throughput (tasks/s)</th>
              <th>Controller update (ms)</th>
              <th>Token wait (ms)</th>
              <th>Executor wait (ms)</th>
              <th>Processing (ms)</th>
              <th>Observed rate range</th>
              <th>Min/max clamps</th>
              <th>CPU utilization</th>
              <th>Memory utilization</th>
              <th>Worker utilization</th>
              <th>Rate updates</th>
              <th>Final token rate</th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((summary, index) => (
              <tr key={`${summary.algorithm}-${summary.trial}-${index}`}>
                <td><AlgorithmBadge algorithm={summary.algorithm} /></td>
                <td>{summary.trial ?? "—"}</td>
                <td>{summary.scenario ?? "—"}</td>
                <td>{summary.concurrency ?? "—"}</td>
                <td>{summary.completed_tasks ?? "—"}</td>
                <td>{summary.failed_tasks ?? "—"}</td>
                <td>{summary.timed_out_tasks ?? "—"}</td>
                <td>{formatNumber(summary.elapsed_s, 3)}</td>
                <td>{formatNumber(summary.average_latency_ms)}</td>
                <td>{formatNumber(summary.p95_latency_ms)}</td>
                <td>{formatNumber(summary.p90_latency_ms)}</td>
                <td>{formatNumber(summary.classical_token_rate)}</td>
                <td>{summary.rate_mode ?? "—"}</td>
                <td>{formatNumber(summary.idle_service_rate_n)}</td>
                <td>{formatNumber(summary.throughput_tasks_per_s)}</td>
                <td>{formatNumber(summary.average_controller_update_ms)}</td>
                <td>{formatNumber(summary.average_token_admission_wait_ms)}</td>
                <td>{formatNumber(summary.average_executor_queue_wait_ms)}</td>
                <td>{formatNumber(summary.average_processing_ms)}</td>
                <td>
                  {summary.minimum_observed_rate === undefined ||
                  summary.maximum_observed_rate === undefined
                    ? "—"
                    : `${formatNumber(summary.minimum_observed_rate)}–${formatNumber(summary.maximum_observed_rate)}`}
                </td>
                <td>
                  {summary.minimum_rate_clamps ?? "—"}/
                  {summary.maximum_rate_clamps ?? "—"}
                </td>
                <td>
                  {typeof summary.average_cpu_utilization === "number"
                    ? `${formatNumber(summary.average_cpu_utilization * 100)}%`
                    : "Unavailable"}
                </td>
                <td>
                  {typeof summary.average_memory_utilization === "number"
                    ? `${formatNumber(summary.average_memory_utilization * 100)}%`
                    : "Unavailable"}
                </td>
                <td>
                  {typeof summary.average_worker_utilization === "number"
                    ? `${formatNumber(summary.average_worker_utilization * 100)}%`
                    : "Unavailable"}
                </td>
                <td>{summary.rate_updates ?? "—"}</td>
                <td>{formatNumber(summary.final_token_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AlgorithmBadge({ algorithm }: { algorithm: string | undefined }) {
  return (
    <span
      className={`algorithm-badge ${
        algorithm === "adaptive"
          ? "badge-adaptive"
          : algorithm === "classical"
            ? "badge-classical"
            : ""
      }`}
    >
      <span />
      {displayAlgorithm(algorithm)}
    </span>
  );
}

interface TaskResultsTableProps {
  tasks: TaskMeasurement[];
  algorithms?: string[];
  compact?: boolean;
}

type SortKey =
  | "algorithm"
  | "trial"
  | "task_id"
  | "task_type"
  | "duration_ms"
  | "admission_delay_ms"
  | "queue_wait_ms"
  | "latency_ms"
  | "processing_ms";

function TaskResultsTable({
  tasks,
  algorithms = [],
  compact = false,
}: TaskResultsTableProps) {
  const [algorithmFilter, setAlgorithmFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [trialFilter, setTrialFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("task_id");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [pageIndex, setPageIndex] = useState(0);
  const pageSize = compact ? 10 : 20;

  const taskTypes = useMemo(
    () =>
      [...new Set(tasks.flatMap((task) => (task.task_type ? [task.task_type] : [])))].sort(),
    [tasks],
  );
  const trials = useMemo(
    () =>
      [...new Set(tasks.flatMap((task) =>
        typeof task.trial === "number" ? [task.trial] : [],
      ))].sort((left, right) => left - right),
    [tasks],
  );
  const firstSubmission = useMemo(() => {
    const values = tasks
      .flatMap((task) =>
        typeof task.submitted_s === "number" ? [task.submitted_s] : [],
      );
    return values.length ? Math.min(...values) : null;
  }, [tasks]);

  const filteredTasks = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    const filtered = tasks.filter((task) => {
      if (algorithmFilter !== "all" && task.algorithm !== algorithmFilter) return false;
      if (typeFilter !== "all" && task.task_type !== typeFilter) return false;
      if (trialFilter !== "all" && String(task.trial) !== trialFilter) return false;
      if (
        normalizedSearch &&
        !String(task.task_id ?? "").toLowerCase().includes(normalizedSearch)
      ) {
        return false;
      }
      return true;
    });
    return filtered.sort((left, right) => {
      const leftValue = left[sortKey];
      const rightValue = right[sortKey];
      if (typeof leftValue === "number" && typeof rightValue === "number") {
        return (leftValue - rightValue) * (sortDirection === "asc" ? 1 : -1);
      }
      return String(leftValue ?? "").localeCompare(String(rightValue ?? "")) *
        (sortDirection === "asc" ? 1 : -1);
    });
  }, [algorithmFilter, search, sortDirection, sortKey, tasks, trialFilter, typeFilter]);
  const pageCount = Math.max(1, Math.ceil(filteredTasks.length / pageSize));
  const visibleTasks = filteredTasks.slice(
    pageIndex * pageSize,
    (pageIndex + 1) * pageSize,
  );

  useEffect(() => {
    setPageIndex(0);
  }, [algorithmFilter, search, trialFilter, typeFilter]);

  function sortBy(key: SortKey) {
    if (sortKey === key) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  function relativeTime(timestamp: number | undefined): string {
    if (typeof timestamp !== "number" || firstSubmission === null) return "—";
    return `${formatNumber((timestamp - firstSubmission) * 1000, 1)} ms`;
  }

  return (
    <section className={`data-section task-table-section ${compact ? "compact-task-table" : ""}`}>
      <div className="section-heading">
        <div>
          <h3>Task-level measurements</h3>
          <p>
            {tasks.length.toLocaleString()} records · timestamps shown as
            milliseconds from the first submitted task (monotonic clock).
          </p>
        </div>
      </div>
      <div className="task-filters" role="group" aria-label="Filter task measurements">
        <label className="search-field">
          <Search size={15} />
          <input
            type="search"
            placeholder="Search task ID"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search task IDs"
          />
        </label>
        <select
          aria-label="Filter by algorithm"
          value={algorithmFilter}
          onChange={(event) => setAlgorithmFilter(event.target.value)}
        >
          <option value="all">All algorithms</option>
          {algorithms.map((algorithm) => (
            <option key={algorithm} value={algorithm}>{displayAlgorithm(algorithm)}</option>
          ))}
        </select>
        <select
          aria-label="Filter by task type"
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)}
        >
          <option value="all">All task types</option>
          {taskTypes.map((taskType) => (
            <option key={taskType} value={taskType}>{taskType}</option>
          ))}
        </select>
        <select
          aria-label="Filter by trial"
          value={trialFilter}
          onChange={(event) => setTrialFilter(event.target.value)}
        >
          <option value="all">All trials</option>
          {trials.map((trial) => (
            <option key={trial} value={trial}>Trial {trial}</option>
          ))}
        </select>
      </div>
      {filteredTasks.length > 0 ? (
        <>
          <div className="table-shell">
            <table>
              <thead>
                <tr>
                  <SortableHeader label="Algorithm" sortKey="algorithm" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <SortableHeader label="Trial" sortKey="trial" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <SortableHeader label="Task ID" sortKey="task_id" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <SortableHeader label="Type" sortKey="task_type" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <SortableHeader label="Duration (ms)" sortKey="duration_ms" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <th>Scheduled*</th>
                  <th>Released*</th>
                  <th>Submitted*</th>
                  <th>Token requested*</th>
                  <th>Admitted*</th>
                  <th>Started*</th>
                  <th>Completed*</th>
                  <SortableHeader label="Admission delay (ms)" sortKey="admission_delay_ms" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <th>Arrival to submit (ms)</th>
                  <th>Controller (ms)</th>
                  <th>Token wait (ms)</th>
                  <SortableHeader label="Queue wait (ms)" sortKey="queue_wait_ms" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <SortableHeader label="Latency (ms)" sortKey="latency_ms" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <SortableHeader label="Processing (ms)" sortKey="processing_ms" active={sortKey} direction={sortDirection} onSort={sortBy} />
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {visibleTasks.map((task, index) => (
                  <tr key={`${task.algorithm}-${task.trial}-${task.task_id}-${index}`}>
                    <td><AlgorithmBadge algorithm={task.algorithm} /></td>
                    <td>{task.trial ?? "—"}</td>
                    <td>{task.task_id ?? "—"}</td>
                    <td>{task.task_type ?? "—"}</td>
                    <td>{formatNumber(task.duration_ms, 1)}</td>
                    <td>{relativeTime(task.scheduled_arrival_s)}</td>
                    <td>{relativeTime(task.actual_arrival_s)}</td>
                    <td>{relativeTime(task.submitted_s)}</td>
                    <td>{relativeTime(task.token_requested_s)}</td>
                    <td>{relativeTime(task.admitted_s)}</td>
                    <td>{relativeTime(task.started_s)}</td>
                    <td>{relativeTime(task.completed_s)}</td>
                    <td>{formatNumber(task.admission_delay_ms, 2)}</td>
                    <td>{formatNumber(task.external_arrival_to_submission_ms, 2)}</td>
                    <td>{formatNumber(task.controller_update_ms, 2)}</td>
                    <td>{formatNumber(task.token_admission_wait_ms, 2)}</td>
                    <td>{formatNumber(task.queue_wait_ms, 2)}</td>
                    <td>{formatNumber(task.latency_ms, 2)}</td>
                    <td>{formatNumber(task.processing_ms, 2)}</td>
                    <td title={task.error}>{task.status ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <span>
              Showing {pageIndex * pageSize + 1}–
              {Math.min((pageIndex + 1) * pageSize, filteredTasks.length)} of{" "}
              {filteredTasks.length.toLocaleString()} tasks
            </span>
            <div>
              <button
                className="button button-secondary button-small"
                disabled={pageIndex === 0}
                onClick={() => setPageIndex((current) => Math.max(0, current - 1))}
              >
                Previous
              </button>
              <span className="page-number">{pageIndex + 1} / {pageCount}</span>
              <button
                className="button button-secondary button-small"
                disabled={pageIndex + 1 >= pageCount}
                onClick={() => setPageIndex((current) => Math.min(pageCount - 1, current + 1))}
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState
          icon={Search}
          title="No tasks match these filters"
          description="Change or clear a filter to view task measurements."
        />
      )}
    </section>
  );
}

function SortableHeader({
  label,
  sortKey,
  active,
  direction,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  active: SortKey;
  direction: "asc" | "desc";
  onSort: (key: SortKey) => void;
}) {
  return (
    <th aria-sort={active === sortKey ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button className="sort-button" onClick={() => onSort(sortKey)}>
        {label}
        <span aria-hidden="true">{active === sortKey ? (direction === "asc" ? " ↑" : " ↓") : " ↕"}</span>
      </button>
    </th>
  );
}

function TaskMonitorPage({ experiment }: { experiment: SavedExperiment | null }) {
  const tasks = experiment?.result.task_results ?? [];
  return (
    <>
      <PageHeading
        eyebrow="TASK EXECUTION"
        title="Task monitor"
        description="Inspect the individual measurements from the latest successful benchmark."
      />
      <div className="notice-card">
        <div className="notice-icon"><Info size={18} /></div>
        <div>
          <strong>Benchmark snapshot, not a live task stream</strong>
          <p>
            The backend exposes task records only after a benchmark completes.
            There is no task-list, queue-state, task-submission, or live update
            endpoint, so this page does not fabricate queued or running tasks.
          </p>
        </div>
      </div>
      {experiment ? (
        <div className="snapshot-label">
          <span className="snapshot-dot" />
          Latest completed run: {scenarioLabels[experiment.request.scenario]} ·{" "}
          {new Date(experiment.completedAt).toLocaleString()}
        </div>
      ) : (
        <EmptyState
          icon={ListChecks}
          title="No benchmark task records yet"
          description="Run an experiment in the Experiment Lab to inspect its measured task records here."
        />
      )}
      {experiment && tasks.length > 0 && (
        <TaskResultsTable
          tasks={tasks}
          algorithms={experiment.result.algorithms}
        />
      )}
      {experiment && tasks.length === 0 && (
        <EmptyState
          icon={ListChecks}
          title="This run returned no task records"
          description="The API response did not include individual task measurements."
        />
      )}
    </>
  );
}

function InsightsPage() {
  const topics = [
    {
      number: "01",
      title: "Classical Token Bucket",
      tag: "TRAFFIC SHAPING",
      body: "A token bucket accumulates permits at a configured rate up to its capacity. A task is admitted only when a token is available, which limits the sustained admission rate while allowing short bursts.",
      detail: "Prototype: fixed initial rate of 50 tokens/s and bucket capacity of 8.",
    },
    {
      number: "02",
      title: "Load calculation",
      tag: "RESOURCE SIGNAL",
      body: "CPU, memory and resource usage are normalized to [0, 1], ranked, and combined with weights that depend on how many signals fall into medium or high load bands.",
      detail: "Used in each adaptive update during a benchmark trial.",
    },
    {
      number: "03",
      title: "M/M/1 queueing model",
      tag: "QUEUEING THEORY",
      body: "The queue model provides theoretical relationships among arrival rate, service rate and traffic intensity for a single-server queue. Its assumptions do not make it a measurement of a production GIS queue.",
      detail: "The adaptive controller includes a mean-task-based capacity adjustment.",
    },
    {
      number: "04",
      title: "Hidden Markov Model",
      tag: "STATE ESTIMATION",
      body: "The rate HMM updates a three-state belief using a transition matrix and observed load rank. The most likely state becomes the controller's RateRank.",
      detail: "Current state probabilities are calculated internally, but are not returned by the benchmark API.",
    },
    {
      number: "05",
      title: "Adaptive rate controller",
      tag: "RATE ADJUSTMENT",
      body: "The controller chooses alpha and beta from the inferred RateRank, estimates remaining service capacity and clamps the resulting rate between configured minimum and maximum bounds.",
      detail: "Live rate, rank, alpha/beta, limits and probability traces need a backend response field or dedicated controller-metrics endpoint.",
    },
  ];

  return (
    <>
      <PageHeading
        eyebrow="METHODS"
        title="Algorithm insights"
        description="Plain-language notes about the implementation currently present in this repository."
      />
      <div className="theory-banner">
        <BookOpen size={19} />
        <p>
          These are descriptions of the implemented methods. No live controller
          values or experimental conclusions are implied unless shown from a
          completed benchmark response.
        </p>
      </div>
      <div className="insight-list">
        {topics.map((topic) => (
          <article className="insight-card" key={topic.number}>
            <div className="insight-number">{topic.number}</div>
            <div className="insight-body">
              <span className="eyebrow">{topic.tag}</span>
              <h2>{topic.title}</h2>
              <p>{topic.body}</p>
              <div className="insight-detail"><Info size={15} />{topic.detail}</div>
            </div>
          </article>
        ))}
      </div>
      <section className="panel controller-state-panel">
        <div className="panel-heading">
          <div className="panel-heading-icon"><Activity size={18} /></div>
          <div>
            <h2>Current adaptive controller state</h2>
            <p>Unavailable from the current API response.</p>
          </div>
          <span className="availability-badge">NOT EXPOSED</span>
        </div>
        <div className="controller-unavailable">
          <AlertCircle size={18} />
          <p>
            The backend currently returns aggregate trial summaries and task
            records only. Exposing token rate, RateRank, alpha, beta, minimum
            and maximum rate, remaining capacity and HMM probabilities requires
            an explicit controller trace in the benchmark response or a
            dedicated metrics endpoint.
          </p>
        </div>
      </section>
    </>
  );
}

function ProjectPage() {
  const sections = [
    {
      title: "Research problem",
      text: "Highly concurrent geographic information system services can experience resource pressure as task arrival rates and task costs vary. Static request admission may not respond to changing capacity.",
    },
    {
      title: "Project objective",
      text: "Explore an adaptive task traffic-shaping method that uses system-load indicators and an HMM-informed rate controller, then compare measured local task-processing behavior against a classical token bucket.",
    },
    {
      title: "Architecture",
      text: "A React and TypeScript browser interface submits configurations to FastAPI. The existing Python benchmark runs token-bucket trials, records task-level timing, returns summaries and writes task and summary CSV files.",
    },
    {
      title: "Experimental methodology",
      text: "Each trial generates a selected workload, creates a fresh worker pool, applies the chosen admission controller and records submitted, admitted, started and completed monotonic-clock times. Repetitions are independent trials.",
    },
    {
      title: "Evaluation metrics",
      text: "The API reports average task latency, completed tasks, elapsed trial time and throughput calculated from completed tasks divided by measured elapsed time. The UI presents the returned values without substituting configured rates for throughput.",
    },
    {
      title: "Prototype limitations",
      text: "This repository prototype processes simulated-duration local tasks; it is not integrated with a live GIS service. Benchmark output is synchronous, and no task queue feed, live metrics route, controller trace or backend-persisted run history is exposed.",
    },
  ];
  return (
    <>
      <PageHeading
        eyebrow="RESEARCH CONTEXT"
        title="Project information"
        description="Scope, methodology and current prototype boundaries for a transparent live demonstration."
      />
      <section className="project-hero">
        <div className="project-mark"><Activity size={26} /></div>
        <div>
          <span className="eyebrow">RESEARCH PROTOTYPE</span>
          <h2>
            An Adaptive Task Traffic Shaping Method for Highly Concurrent
            Geographic Information System Services with Limited Resources
          </h2>
        </div>
      </section>
      <div className="project-info-grid">
        {sections.map((section, index) => (
          <article className="project-info-card" key={section.title}>
            <span className="project-card-number">{String(index + 1).padStart(2, "0")}</span>
            <h3>{section.title}</h3>
            <p>{section.text}</p>
          </article>
        ))}
      </div>
      <div className="disclosure-card">
        <Info size={18} />
        <p>
          Results shown in this application are measurements produced by the
          local backend when an experiment is run. They are not presented as
          published-paper findings. Any claims from the original paper should
          be cited and evaluated separately from this prototype's output.
        </p>
      </div>
    </>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className = "",
}: {
  icon: typeof Activity;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`empty-state ${className}`}>
      <div className="empty-state-icon"><Icon size={21} /></div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

export default App;
