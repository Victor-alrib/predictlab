from __future__ import annotations

from fastapi import HTTPException

from ..store import Dataset, store


def get_dataset(dataset_id: str) -> Dataset:
    ds = store.get(dataset_id)
    if ds is None:
        raise HTTPException(404, f"Dataset '{dataset_id}' não encontrado.")
    return ds


def check_equipment(ds: Dataset, equipamento: str | None) -> str | None:
    if equipamento and equipamento != "*" and equipamento not in ds.equipment:
        raise HTTPException(404, f"Equipamento '{equipamento}' não encontrado no dataset.")
    return equipamento


def public_run(run: dict) -> dict:
    """Remove objetos internos (modelo treinado etc.) antes de serializar."""
    return {k: v for k, v in run.items() if not k.startswith("_")}
