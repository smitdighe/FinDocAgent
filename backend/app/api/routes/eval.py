"""Eval harness endpoints."""

import uuid

from fastapi import APIRouter, HTTPException

from app.deps import SettingsDep
from app.eval import harness
from app.schemas.eval import EvalRunDetail, EvalRunOut, EvalTriggerRequest

router = APIRouter(tags=["eval"])


@router.post("/run", response_model=EvalRunDetail)
async def trigger_eval(request: EvalTriggerRequest, settings: SettingsDep) -> EvalRunDetail:
    try:
        return await harness.run_eval(
            settings, gold_version=request.gold_version, notes=request.notes
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"gold set '{request.gold_version}' not found"
        ) from exc


@router.get("/runs", response_model=list[EvalRunOut])
async def list_runs(settings: SettingsDep) -> list[EvalRunOut]:
    return await harness.list_runs(settings)


@router.get("/runs/{run_id}", response_model=EvalRunDetail)
async def run_detail(run_id: uuid.UUID, settings: SettingsDep) -> EvalRunDetail:
    detail = await harness.get_run(settings, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return detail
