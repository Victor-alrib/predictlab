"""Rotas de datasets: listagem, upload/mapeamento, qualidade e séries."""

from __future__ import annotations

import uuid
from typing import Literal

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..config import (CANONICAL_VARIABLES, COL_STATUS, COL_TIMESTAMP, DATA_ORIGINS, MAX_UPLOAD_BYTES,
                      STATUS_CATEGORIES)
from ..services import ingestion
from ..services.alerts import invalidate_cache
from ..services.quality import downsample, equipment_variables, quality_report, series_to_list, ts_to_list
from ..store import Dataset, store
from .deps import check_equipment, get_dataset

router = APIRouter(prefix="/api", tags=["datasets"])


@router.get("/meta")
def meta():
    return {
        "variaveis_canonicas": {k: {"label": v["label"], "unit": v["unit"]} for k, v in CANONICAL_VARIABLES.items()},
        "categorias_estado": STATUS_CATEGORIES,
        "origens_dado": DATA_ORIGINS,
    }


@router.get("/datasets")
def list_datasets():
    return [d.meta() for d in store.list()]


@router.get("/datasets/{dataset_id}")
def dataset_detail(dataset_id: str):
    return get_dataset(dataset_id).meta()


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    ds = get_dataset(dataset_id)
    if ds.is_demo:
        raise HTTPException(400, "O dataset de demonstração não pode ser removido.")
    store.delete(dataset_id)
    invalidate_cache()
    return {"ok": True}


@router.post("/datasets/upload")
async def upload_csv(file: UploadFile = File(...)):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Arquivo maior que {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        df_str, info = ingestion.parse_csv(raw)
    except ingestion.IngestionError as exc:
        raise HTTPException(422, str(exc)) from exc
    suggestion = ingestion.suggest_mapping(df_str, info)
    upload_id = store.stage_upload({"df": df_str, "info": info, "filename": file.filename})
    preview = df_str.head(12).where(df_str.head(12).notna(), None).to_dict(orient="records")
    return {"upload_id": upload_id, "arquivo": file.filename, "info": info,
            "previa": preview, "sugestao": suggestion}


@router.get("/datasets/upload/{upload_id}/status-values")
def upload_status_values(upload_id: str, coluna: str):
    up = store.get_upload(upload_id)
    if up is None:
        raise HTTPException(404, "Upload expirado ou inexistente. Envie o arquivo novamente.")
    if coluna not in up["df"].columns:
        raise HTTPException(404, f"Coluna '{coluna}' não existe.")
    vals = ingestion.describe_status_values(up["df"], coluna)
    return {"valores": vals, "sugestao": ingestion.suggest_status_map(vals)}


class VariableMap(BaseModel):
    column: str
    action: Literal["canonica", "personalizada", "ignorar"]
    key: str | None = None
    label: str | None = None
    unit: str | None = None


class ImportRequest(BaseModel):
    upload_id: str
    nome: str = Field(min_length=1, max_length=120)
    descricao: str = ""
    origem: Literal["medicao_real", "dataset_publico", "simulado"]
    roles: dict[str, str | None]
    variables: list[VariableMap]
    status_map: dict[str, str] = {}
    equipamento_padrao: str = "EQ-01"
    timestamp_format: str | None = None
    decimal: Literal[".", ","] | None = None


@router.post("/datasets/import")
def import_dataset(req: ImportRequest):
    up = store.get_upload(req.upload_id)
    if up is None:
        raise HTTPException(404, "Upload expirado ou inexistente. Envie o arquivo novamente.")
    mapping = req.model_dump()
    try:
        df, variables, report = ingestion.apply_mapping(up["df"], up["info"], mapping)
    except ingestion.IngestionError as exc:
        raise HTTPException(422, str(exc)) from exc
    ds = Dataset(
        id=f"ds-{uuid.uuid4().hex[:8]}", name=req.nome.strip(), description=req.descricao.strip(),
        data_origin=req.origem, df=df, variables=variables, mapping=mapping,
        provenance={"arquivo": up.get("filename"), "leitura": up["info"], "conversao": report},
    )
    store.add(ds)
    store.pop_upload(req.upload_id)
    return {"dataset": ds.meta(), "relatorio_importacao": report, "qualidade": quality_report(ds)}


@router.get("/datasets/{dataset_id}/quality")
def dataset_quality(dataset_id: str):
    return quality_report(get_dataset(dataset_id))


@router.get("/datasets/{dataset_id}/series")
def dataset_series(dataset_id: str, equipamento: str, variaveis: str | None = None,
                   inicio: str | None = None, fim: str | None = None,
                   max_points: int = Query(2000, ge=50, le=20000)):
    ds = get_dataset(dataset_id)
    check_equipment(ds, equipamento)
    g = ds.subset(equipamento).sort_values(COL_TIMESTAMP)
    if inicio:
        g = g[g[COL_TIMESTAMP] >= pd.Timestamp(inicio)]
    if fim:
        g = g[g[COL_TIMESTAMP] <= pd.Timestamp(fim)]
    available = equipment_variables(ds, equipamento)
    keys = [v for v in (variaveis.split(",") if variaveis else available) if v in available]
    d = downsample(g, keys, max_points) if keys else g[[COL_TIMESTAMP]]
    out = {"equipamento": equipamento, "timestamps": ts_to_list(d[COL_TIMESTAMP]),
           "series": {k: series_to_list(d[k]) for k in keys}, "pontos_originais": int(len(g)),
           "reamostrado": len(d) < len(g)}
    # faixas de estado (para colorir o fundo do gráfico)
    if COL_STATUS in g.columns and g[COL_STATUS].notna().any():
        st = g[[COL_TIMESTAMP, COL_STATUS]].copy()
        st[COL_STATUS] = st[COL_STATUS].fillna("desconhecido")
        change = st[COL_STATUS] != st[COL_STATUS].shift()
        blocks = st[change].copy()
        blocks["fim"] = blocks[COL_TIMESTAMP].shift(-1).fillna(st[COL_TIMESTAMP].iloc[-1])
        out["estados"] = [{"estado": r[COL_STATUS], "inicio": r[COL_TIMESTAMP].isoformat(), "fim": r["fim"].isoformat()}
                          for _, r in blocks.iterrows() if r[COL_STATUS] in ("falha", "manutencao", "desconhecido")]
    return out
