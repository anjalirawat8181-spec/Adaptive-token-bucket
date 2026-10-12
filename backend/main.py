
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import router

app = FastAPI(
    title="Adaptive GIS Traffic Shaping",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://adaptive-token-bucket.vercel.app",
        "https://adaptive-token-bucket-6sglc5bfe-anjalis-projects-caff9985.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def home():
    return {
        "project": "Adaptive GIS Traffic Shaping",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
