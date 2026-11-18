"""Rotas de Machine Learning: treino, previsão temporal e comparação de execuções."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..services import forecasting, ml_models
from ..services.alerts import invalidate_cache
from ..store import store
from .deps import check_equipment, get_dataset, public_run

router = APIRouter(prefix="/api/ml", tags=["ml"])


def _equipments(ds, equipamentos: list[str]) -> list[str]:
    if not equipamentos or equipamentos == ["*"]:
        return ds.equipment
    for e in equipamentos:
        check_equipment(ds, e)
    return equipamentos


@router.get("/models")
def models():
    return {"classificacao_anomalia": ml_models.available_models(), "previsao": forecasting.FORECAST_MODELS}


class ClassifierRequest(BaseModel):
    modelo: Literal["random_forest", "xgboost", "baseline"] = "random_forest"
    equipamentos: list[str] = ["*"]
    horizonte_h: float = Field(24, gt=0, le=24 * 14)
    fracao_teste: float = Field(0.3, ge=0.1, le=0.6)
    limiar: float = Field(0.5, gt=0, lt=1)
    semente: int = 42
    parametros: dict = {}


@router.post("/{dataset_id}/classification")
async def train_classifier(dataset_id: str, req: ClassifierRequest):
    ds = get_dataset(dataset_id)
    eqs = _equipments(ds, req.equipamentos)
    try:
        run = await run_in_threadpool(ml_models.train_classifier, ds, eqs, req.modelo, req.horizonte_h,
                                      req.fracao_teste, req.limiar, req.parametros, req.semente)
    except (ml_models.MLError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    store.add_run(run)
    invalidate_cache()
    return public_run(run)


class AnomalyRequest(BaseModel):
    equipamentos: list[str] = ["*"]
    contaminacao: float = Field(0.02, gt=0, le=0.3)
    horizonte_h: float = Field(24, gt=0, le=24 * 14)
    fracao_teste: float = Field(0.3, ge=0.1, le=0.6)
    semente: int = 42


@router.post("/{dataset_id}/anomaly")
async def train_anomaly(dataset_id: str, req: AnomalyRequest):
    ds = get_dataset(dataset_id)
    eqs = _equipments(ds, req.equipamentos)
    try:
        run = await run_in_threadpool(ml_models.train_isolation_forest, ds, eqs, req.contaminacao,
                                      req.horizonte_h, req.fracao_teste, req.semente)
    except (ml_models.MLError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    store.add_run(run)
    invalidate_cache()
    return public_run(run)


class ForecastRequest(BaseModel):
    equipamento: str
    variavel: str
    modelos: list[str] = list(forecasting.FORECAST_MODELS)
    horizonte_h: int = Field(48, ge=1, le=24 * 14)
    holdout_h: int = Field(168, ge=24, le=24 * 30)
    periodo_h: int = Field(24, ge=2, le=24 * 7)


@router.post("/{dataset_id}/forecast")
async def forecast(dataset_id: str, req: ForecastRequest):
    ds = get_dataset(dataset_id)
    check_equipment(ds, req.equipamento)
    try:
        run = await run_in_threadpool(forecasting.run_forecast, ds, req.equipamento, req.variavel, req.modelos,
                                      req.horizonte_h, req.holdout_h, req.periodo_h)
    except forecasting.ForecastError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.add_run(run)
    invalidate_cache()
    return public_run(run)


@router.get("/runs")
def list_runs(dataset_id: str | None = None):
    out = []
    for r in store.list_runs(dataset_id):
        out.append({k: r.get(k) for k in ("id", "created_at", "tipo", "modelo", "modelo_nome", "dataset_id",
                                          "dataset_sintetico", "equipamentos", "variavel", "parametros",
                                          "metricas", "melhor_modelo", "duracao_s", "avisos")}
                   | ({"resultados": [{k: x.get(k) for k in ("modelo", "nome", "metricas_holdout", "erro")}
                                      for x in r["resultados"]]} if r["tipo"] == "previsao" else {}))
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Execução não encontrada.")
    return public_run(run)


@router.delete("/runs/{run_id}")
def delete_run(run_id: str):
    if not store.delete_run(run_id):
        raise HTTPException(404, "Execução não encontrada.")
    invalidate_cache()
    return {"ok": True}
