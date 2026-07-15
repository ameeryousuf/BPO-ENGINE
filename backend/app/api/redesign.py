"""HTTP layer for the redesign endpoint.

Translates between HTTP concerns (file upload, status codes) and the
domain-level ``redesign_service``, which knows nothing about FastAPI.
"""

import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.exceptions import InvalidProcessDefinitionError, RedesignIntegrityError
from app.models.response import RedesignResponse
from app.services import redesign_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/redesign", response_model=RedesignResponse)
async def redesign(file: UploadFile = File(...)) -> dict:
    """Upload a BPMN process JSON file and receive the redesigned process.

    Runs the complete pipeline (parse, train, replay, verify, serialize)
    entirely in memory and returns before/after metrics, the improvement
    percentages, the applied heuristic sequence, and the redesigned process.
    """
    raw = await file.read()
    try:
        process_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    try:
        return redesign_service.redesign(process_data)
    except InvalidProcessDefinitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RedesignIntegrityError as exc:
        logger.exception("Redesign integrity check failed")
        raise HTTPException(status_code=500, detail="Internal redesign integrity error.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during redesign")
        raise HTTPException(status_code=500, detail="Unexpected internal error.") from exc
