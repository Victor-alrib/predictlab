"""Rotas de análise temporal e indicadores de manutenção."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services import maintenance, timeseries
from .deps import check_equipment, get_dataset

router = APIRouter(prefix="/api", tags=["analise"])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except timeseries.AnalysisError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/analysis/{dataset_id}/trend")
def trend(dataset_id: str, equipamento: str, variavel: str, janelas: str = "6h,24h,7D",
          freq: str = "auto", apenas_operando: bool = False):
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    js = [j.strip() for j in janelas.split(",") if j.strip()][:4]
    return _run(timeseries.trend, ds, equipamento, variavel, js, freq, apenas_operando)


@router.get("/analysis/{dataset_id}/seasonality")
def seasonality(dataset_id: str, equipamento: str, variavel: str):
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    return _run(timeseries.seasonality, ds, equipamento, variavel)


@router.get("/analysis/{dataset_id}/profile")
def profile(dataset_id: str, equipamento: str, variavel: str):
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    return _run(timeseries.profile, ds, equipamento, variavel)


class CompareRequest(BaseModel):
    equipamento: str
    variavel: str
    periodo_a: tuple[str, str]
    periodo_b: tuple[str, str]
    apenas_operando: bool = True


@router.post("/analysis/{dataset_id}/compare")
def compare(dataset_id: str, req: CompareRequest):
    ds = get_dataset(dataset_id)
    check_equipment(ds, req.equipamento)
    return _run(timeseries.compare_periods, ds, req.equipamento, req.variavel,
                req.periodo_a, req.periodo_b, req.apenas_operando)


@router.get("/maintenance/{dataset_id}")
def maintenance_indicators(dataset_id: str, equipamento: str | None = None,
                           min_falhas: int = Query(maintenance.DEFAULT_MIN_FAILURES, ge=1, le=50),
                           min_dias: float = Query(maintenance.DEFAULT_MIN_DAYS, ge=0, le=365)):
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    return maintenance.compute_indicators(ds, equipamento, min_falhas, min_dias)
