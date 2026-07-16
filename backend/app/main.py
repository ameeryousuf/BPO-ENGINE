from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.redesign import router as redesign_router
from app.logging_config import configure_logging

configure_logging()

app = FastAPI(title="BPO Redesign Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(redesign_router)


@app.get("/")
def health_check() -> dict:
    """Basic health check."""
    return {"status": "running"}
