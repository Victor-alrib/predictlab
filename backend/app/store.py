"""Armazenamento de datasets e execuções de modelos.

Implementação propositalmente simples (memória + pickle em disco), adequada a
uma plataforma educacional rodando localmente. Para produção, a interface
``DatasetStore`` poderia ser reimplementada sobre um banco de séries temporais
(ex.: TimescaleDB) ou um historian industrial, sem mudar os serviços.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP, DATASETS_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Dataset:
    id: str
    name: str
    data_origin: str  # medicao_real | dataset_publico | simulado
    df: pd.DataFrame
    variables: list[dict]  # [{key, label, unit, canonical, source_column}]
    created_at: str = field(default_factory=now_iso)
    description: str = ""
    mapping: dict | None = None
    is_demo: bool = False
    thresholds: dict = field(default_factory=dict)  # {equip|*: {var: {min,max,severidade}}}
    provenance: dict = field(default_factory=dict)  # arquivo de origem, eventos simulados etc.

    @property
    def is_synthetic(self) -> bool:
        return self.data_origin == "simulado"

    @property
    def has_status(self) -> bool:
        return bool(COL_STATUS in self.df.columns and self.df[COL_STATUS].notna().any())

    @property
    def equipment(self) -> list[str]:
        return sorted(self.df[COL_EQUIPMENT].astype(str).unique().tolist())

    def variable_keys(self) -> list[str]:
        return [v["key"] for v in self.variables]

    def variable(self, key: str) -> dict | None:
        return next((v for v in self.variables if v["key"] == key), None)

    def subset(self, equipamento: str | None = None) -> pd.DataFrame:
        df = self.df
        if equipamento and equipamento != "*":
            df = df[df[COL_EQUIPMENT] == equipamento]
        return df

    def meta(self) -> dict[str, Any]:
        ts = self.df[COL_TIMESTAMP]
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "data_origin": self.data_origin,
            "is_synthetic": self.is_synthetic,
            "is_demo": self.is_demo,
            "created_at": self.created_at,
            "rows": int(len(self.df)),
            "equipment": self.equipment,
            "variables": self.variables,
            "has_status": self.has_status,
            "provenance": self.provenance,
            "start": ts.min().isoformat() if len(ts) else None,
            "end": ts.max().isoformat() if len(ts) else None,
        }


class DatasetStore:
    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}
        self._uploads: dict[str, dict] = {}  # staging de CSVs antes do mapeamento
        self._runs: dict[str, dict] = {}  # execuções de ML
        self._lock = threading.Lock()

    # --- datasets -----------------------------------------------------------
    def add(self, ds: Dataset, persist: bool = True) -> Dataset:
        ds.df = ds.df.sort_values([COL_EQUIPMENT, COL_TIMESTAMP]).reset_index(drop=True)
        with self._lock:
            self._datasets[ds.id] = ds
        if persist and not ds.is_demo:
            pd.to_pickle(ds, DATASETS_DIR / f"{ds.id}.pkl")
        return ds

    def get(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)

    def list(self) -> list[Dataset]:
        return sorted(self._datasets.values(), key=lambda d: (not d.is_demo, d.created_at))

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            ds = self._datasets.pop(dataset_id, None)
            self._runs = {k: r for k, r in self._runs.items() if r["dataset_id"] != dataset_id}
        path = DATASETS_DIR / f"{dataset_id}.pkl"
        if path.exists():
            path.unlink()
        return ds is not None

    def save(self, ds: Dataset) -> None:
        if not ds.is_demo:
            pd.to_pickle(ds, DATASETS_DIR / f"{ds.id}.pkl")

    def load_persisted(self) -> None:
        for path in DATASETS_DIR.glob("*.pkl"):
            try:
                ds = pd.read_pickle(path)
                if isinstance(ds, Dataset):
                    self._datasets[ds.id] = ds
            except Exception:  # arquivo corrompido ou de versão antiga
                continue

    # --- uploads ------------------------------------------------------------
    def stage_upload(self, payload: dict) -> str:
        upload_id = uuid.uuid4().hex[:12]
        with self._lock:
            # mantém no máximo 10 uploads pendentes
            if len(self._uploads) >= 10:
                self._uploads.pop(next(iter(self._uploads)))
            self._uploads[upload_id] = payload
        return upload_id

    def get_upload(self, upload_id: str) -> dict | None:
        return self._uploads.get(upload_id)

    def pop_upload(self, upload_id: str) -> dict | None:
        with self._lock:
            return self._uploads.pop(upload_id, None)

    # --- execuções de ML ----------------------------------------------------
    def add_run(self, run: dict) -> dict:
        run.setdefault("id", uuid.uuid4().hex[:10])
        run.setdefault("created_at", now_iso())
        with self._lock:
            self._runs[run["id"]] = run
        return run

    def get_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    def list_runs(self, dataset_id: str | None = None) -> list[dict]:
        runs = [r for r in self._runs.values() if dataset_id is None or r["dataset_id"] == dataset_id]
        return sorted(runs, key=lambda r: r["created_at"], reverse=True)

    def delete_run(self, run_id: str) -> bool:
        with self._lock:
            return self._runs.pop(run_id, None) is not None


store = DatasetStore()
