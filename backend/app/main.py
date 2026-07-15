"""FastAPI application entry point.

Run with: uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.api.redesign import router as redesign_router
from app.logging_config import configure_logging

configure_logging()

app = FastAPI(title="BPO Redesign Engine")
app.include_router(redesign_router)


@app.get("/")
def health_check() -> dict:
    """Basic health check."""
    return {"status": "running"}
