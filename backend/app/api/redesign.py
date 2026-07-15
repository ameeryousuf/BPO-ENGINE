"""HTTP layer for the redesign endpoint.

Translates between HTTP concerns (file upload, status codes) and the
domain-level ``redesign_service``, which knows nothing about FastAPI.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.exceptions import InvalidProcessDefinitionError, RedesignIntegrityError
from app.services import redesign_service
from app.models.response import RedesignResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard ceiling on wall-clock time for a single redesign request. RL training
# runs a fixed episode count but a much larger-than-expected process (bigger
# state/action space per episode) could still blow past what's reasonable
# for a synchronous HTTP request; this guarantees the client gets a prompt
# error instead of a hung connection.
TRAINING_TIMEOUT_SECONDS = 45


@router.post("/redesign", response_model=RedesignResponse)
async def redesign(file: UploadFile = File(...)) -> dict:
    """Upload a BPMN process JSON file and receive the redesigned process.

    Runs the complete pipeline (parse, train, replay, verify, serialize)
    entirely in memory and returns before/after metrics, the improvement
    percentages, the applied heuristic sequence, and the redesigned process.

    The pipeline is CPU-bound and synchronous, so it is offloaded to a
    worker thread via ``run_in_threadpool``: this lets the event loop serve
    other requests concurrently instead of blocking on one client's
    training run, and lets ``asyncio.wait_for`` enforce a hard timeout.
    """
    raw = await file.read()
    try:
        process_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    try:
        return await asyncio.wait_for(
            run_in_threadpool(redesign_service.redesign, process_data),
            timeout=TRAINING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        logger.error("Redesign training exceeded the %ss time limit", TRAINING_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=500,
            detail=f"Training exceeded time limit ({TRAINING_TIMEOUT_SECONDS}s). Try a smaller process.",
        ) from exc
    except InvalidProcessDefinitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RedesignIntegrityError as exc:
        logger.exception("Redesign integrity check failed")
        raise HTTPException(status_code=500, detail="Internal redesign integrity error.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during redesign")
        raise HTTPException(status_code=500, detail="Unexpected internal error.") from exc
