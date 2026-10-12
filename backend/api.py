from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from experiments.benchmark import run_benchmark


router = APIRouter(prefix="/api", tags=["experiments"])
RESULTS_DIR = Path(__file__).resolve().parent / "experiments" / "results"
RESULT_FILES = {
    "task_results.csv",
    "benchmark_summary.csv",
}


class ExperimentRequest(BaseModel):
    scenario: Literal["simple", "general", "complex", "mixed", "dynamic"] = "mixed"
    concurrency: int = Field(default=20, ge=1, le=200)
    repetitions: int = Field(default=3, ge=1, le=20)
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
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    result["task_csv_url"] = "/api/experiments/download/task_results.csv"
    result["summary_csv_url"] = "/api/experiments/download/benchmark_summary.csv"
    return result


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
