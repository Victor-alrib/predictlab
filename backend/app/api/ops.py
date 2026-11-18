"""Rotas de dashboard, alertas/limites e relatórios."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from ..services import alerts as alerts_svc
from ..services import dashboard, reports
from ..store import store
from .deps import check_equipment, get_dataset

router = APIRouter(prefix="/api", tags=["operacao"])


@router.get("/dashboard/{dataset_id}")
async def get_dashboard(dataset_id: str, referencia: str | None = None):
    ds = get_dataset(dataset_id)
    return await run_in_threadpool(dashboard.build_dashboard, ds, referencia)


@router.get("/alerts/{dataset_id}")
async def get_alerts(dataset_id: str, equipamento: str | None = None, origens: str | None = None,
                     severidade: str | None = None, limite: int = 500, k: float = 4.0):
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    ors = [o for o in (origens or "").split(",") if o in alerts_svc.ORIGINS] or None
    items = await run_in_threadpool(alerts_svc.compute_alerts, ds, equipamento, ors, k)
    if severidade:
        items = [a for a in items if a["severidade"] == severidade]
    return {"resumo": alerts_svc.summarize(items), "alertas": items[:limite], "origens": alerts_svc.ORIGINS,
            "parametros": {"k_zscore": k}}


class Threshold(BaseModel):
    min: float | None = None
    max: float | None = None
    severidade: Literal["baixa", "media", "alta"] = "media"
    duracao_min_min: float = Field(0, ge=0)

    @model_validator(mode="after")
    def check(self):
        if self.min is None and self.max is None:
            raise ValueError("Informe ao menos um limite (mín. ou máx.).")
        if self.min is not None and self.max is not None and self.min >= self.max:
            raise ValueError("O limite mínimo deve ser menor que o máximo.")
        return self


@router.get("/alerts/{dataset_id}/thresholds")
def get_thresholds(dataset_id: str):
    ds = get_dataset(dataset_id)
    return {"limites": ds.thresholds,
            "efetivos": {eq: alerts_svc.thresholds_for(ds, eq) for eq in ds.equipment}}


@router.put("/alerts/{dataset_id}/thresholds/{equipamento}/{variavel}")
def set_threshold(dataset_id: str, equipamento: str, variavel: str, body: Threshold):
    ds = get_dataset(dataset_id)
    if equipamento != "*":
        check_equipment(ds, equipamento)
    if variavel not in ds.variable_keys():
        raise HTTPException(404, f"Variável '{variavel}' não encontrada.")
    ds.thresholds.setdefault(equipamento, {})[variavel] = body.model_dump()
    store.save(ds)
    alerts_svc.invalidate_cache()
    return {"limites": ds.thresholds}


@router.delete("/alerts/{dataset_id}/thresholds/{equipamento}/{variavel}")
def delete_threshold(dataset_id: str, equipamento: str, variavel: str):
    ds = get_dataset(dataset_id)
    eqd = ds.thresholds.get(equipamento) or {}
    if variavel not in eqd:
        raise HTTPException(404, "Limite não configurado.")
    eqd.pop(variavel)
    if not eqd:
        ds.thresholds.pop(equipamento, None)
    store.save(ds)
    alerts_svc.invalidate_cache()
    return {"limites": ds.thresholds}


@router.get("/alerts/{dataset_id}/thresholds/suggest")
def suggest_thresholds(dataset_id: str, equipamento: str, variavel: str):
    """Sugestão baseada em percentis da operação — é só um ponto de partida e é rotulada como tal."""
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    g = ds.subset(equipamento)
    if variavel not in g.columns:
        raise HTTPException(404, "Variável não encontrada.")
    s = g[g["estado"] == "operando"][variavel] if ds.has_status else g[variavel]
    s = s.dropna()
    if len(s) < 30:
        raise HTTPException(422, "Leituras insuficientes para sugerir limites.")
    p01, p99 = float(s.quantile(0.005)), float(s.quantile(0.995))
    span = p99 - p01
    return {"min": round(p01 - 0.1 * span, 3), "max": round(p99 + 0.1 * span, 3),
            "base": "percentis 0,5% e 99,5% da operação ± 10% da faixa",
            "aviso": "Sugestão estatística. Limites de alarme reais devem vir de especificação do fabricante ou "
                     "da engenharia de processo."}


class ReportRequest(BaseModel):
    equipamento: str | None = None
    secoes: list[str] = reports.SECTIONS
    run_ids: list[str] | None = None
    titulo: str | None = None
    autor: str | None = None
    embutir_plotly: bool = True  # relatório funciona offline; False usa CDN (arquivo ~3,5 MB menor)


@router.post("/reports/{dataset_id}", response_class=HTMLResponse)
async def build_report(dataset_id: str, req: ReportRequest):
    ds = get_dataset(dataset_id)
    check_equipment(ds, req.equipamento)
    html = await run_in_threadpool(reports.build_report, ds, req.equipamento,
                                   [s for s in req.secoes if s in reports.SECTIONS], req.run_ids,
                                   req.titulo, req.autor, req.embutir_plotly)
    fname = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"relatorio_{ds.name}")[:60] + ".html"
    return HTMLResponse(html, headers={"Content-Disposition": f'inline; filename="{fname}"'})
