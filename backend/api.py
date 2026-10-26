from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from experiments.benchmark import (
    CLASSICAL_RATE_CACHE_PATH,
    find_optimal_classical_rate,
    load_optimal_classical_rates,
    run_benchmark,
    run_concurrency_sweep,
)


router = APIRouter(prefix="/api", tags=["experiments"])
RESULTS_DIR = Path(__file__).resolve().parent / "experiments" / "results"
RESULT_FILES = {
    "task_results.csv",
    "benchmark_summary.csv",
    "rate_diagnostics.csv",
    "dynamic_steps.csv",
    "concurrency_sweep.csv",
}


class ExperimentRequest(BaseModel):
    scenario: Literal["simple", "general", "complex", "mixed", "dynamic"] = "mixed"
    concurrency: int = Field(default=20, ge=1, le=200)
    repetitions: int = Field(default=3, ge=1, le=20)
    comparison: Literal["both", "classical", "adaptive"] = "both"
    classical_rate_mode: Literal["paper_preset", "measured", "manual"] | None = None
    classical_rate: float | None = Field(default=None, gt=0)
    contention_model: bool = True
    speedup: float = Field(default=1.0, gt=0)
    load_scope: Literal["process", "host"] = "process"
    idle_service_rate_n_override: float | None = Field(default=None, gt=0)


class OptimalRateRequest(BaseModel):
    scenario: Literal["simple", "general", "complex", "mixed", "dynamic"]
    candidate_rates: list[float] | None = None
    concurrency_levels: list[int] = Field(default_factory=lambda: [50, 150])
    repetitions: int = Field(default=5, ge=1, le=20)


class SweepRequest(BaseModel):
    scenario: Literal["simple", "general", "complex", "mixed"] = "mixed"
    concurrency_step: int = Field(default=5, ge=1, le=200)
    repetitions: int = Field(default=20, ge=1, le=20)
    comparison: Literal["both", "classical", "adaptive"] = "both"


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/experiments/run")
def run_experiment(request: ExperimentRequest):
    try:
        result = run_benchmark(
            scenario=request.scenario,
            concurrency=request.concurrency,
            repetitions=request.repetitions,
            comparison=request.comparison,
            output_dir=RESULTS_DIR,
            classical_rate_mode=request.classical_rate_mode,
            classical_rate=request.classical_rate,
            contention_model=request.contention_model,
            speedup=request.speedup,
            load_scope=request.load_scope,
            idle_service_rate_n_override=request.idle_service_rate_n_override,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    result["rate_diagnostics_count"] = len(result.get("rate_diagnostics", []))
    result["task_csv_url"] = "/api/experiments/download/task_results.csv"
    result["summary_csv_url"] = "/api/experiments/download/benchmark_summary.csv"
    result["diagnostic_csv_url"] = "/api/experiments/download/rate_diagnostics.csv"
    if request.scenario == "dynamic":
        result["dynamic_steps_csv_url"] = (
            "/api/experiments/download/dynamic_steps.csv"
        )
    return result


@router.post("/experiments/optimal-rate")
def probe_optimal_rate(request: OptimalRateRequest):
    try:
        return find_optimal_classical_rate(
            scenario=request.scenario,
            candidate_rates=request.candidate_rates,
            concurrency_levels=request.concurrency_levels,
            repetitions=request.repetitions,
            cache_path=CLASSICAL_RATE_CACHE_PATH,
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/experiments/optimal-rate/{scenario}")
def get_optimal_rate(scenario: str):
    if scenario not in {"simple", "general", "complex", "mixed", "dynamic"}:
        raise HTTPException(status_code=404, detail="Scenario not found")
    result = load_optimal_classical_rates(CLASSICAL_RATE_CACHE_PATH).get(scenario)
    if result is None:
        raise HTTPException(status_code=404, detail="No measured rate is cached")
    return result


@router.post("/experiments/sweep")
def concurrency_sweep(request: SweepRequest):
    try:
        return run_concurrency_sweep(
            scenario=request.scenario,
            concurrency_step=request.concurrency_step,
            repetitions=request.repetitions,
            comparison=request.comparison,
            output_dir=RESULTS_DIR / "sweeps" / request.scenario,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/experiments/download/{filename}")
def download_experiment_result(filename: str):
    if filename not in RESULT_FILES:
        raise HTTPException(status_code=404, detail="Result file not found")

    file_path = RESULTS_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Result file not found")

    return FileResponse(
        path=file_path,
        media_type="text/csv",
        filename=filename,
    )
