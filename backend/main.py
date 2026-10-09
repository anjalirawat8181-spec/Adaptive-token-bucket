
from fastapi import FastAPI

app = FastAPI(
    title="Adaptive GIS Traffic Shaping",
    version="1.0.0",
)


@app.get("/")
def home():
    return {
        "project": "Adaptive GIS Traffic Shaping",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
