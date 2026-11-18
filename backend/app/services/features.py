"""Engenharia de atributos e rótulos para modelos de falha.

Rótulo supervisionado ("falha iminente"):
    y(t) = 1 se uma falha começa no intervalo (t, t + H], com H = horizonte.
Amostras em que o equipamento já está em falha ou manutenção são excluídas —
o objetivo é antecipar a falha, não reconhecê-la depois que aconteceu.

Atributos (por variável, calculados apenas com dados passados — janelas
"para trás", sem vazamento de informação futura):
    valor atual, média/desvio em 1 h, 6 h e 24 h, mínimo/máximo em 24 h,
    diferença média 6 h − média 24 h (tendência curta) e desvio em relação à
    linha de base robusta de 7 dias (mediana e MAD).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP
from ..store import Dataset
from .quality import equipment_variables

WINDOWS = ("1h", "6h", "24h")


def failure_starts(g: pd.DataFrame) -> pd.DatetimeIndex:
    """Instantes de início de falha (transição de outro estado conhecido → falha)."""
    if COL_STATUS not in g.columns:
        return pd.DatetimeIndex([])
    st = g[COL_STATUS].fillna("desconhecido")
    known = st[st != "desconhecido"]
    is_fail = known == "falha"
    prev = known.shift(1).fillna("")
    starts = is_fail & (prev != "falha") & (prev != "manutencao")
    # falha logo após manutenção preventiva também é início
    starts |= is_fail & (prev == "manutencao") & (known.shift(2).fillna("") != "falha")
    return pd.DatetimeIndex(g.loc[starts[starts].index, COL_TIMESTAMP])


def variables_for(ds: Dataset, equipamentos: list[str]) -> list[str]:
    sets = [set(equipment_variables(ds, e)) for e in equipamentos]
    common = set.intersection(*sets) if sets else set()
    return [k for k in ds.variable_keys() if k in common]


def _features_one(g: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    g = g.sort_values(COL_TIMESTAMP)
    s = g.set_index(COL_TIMESTAMP)[variables]
    # amostras fora de operação normal não devem contaminar a linha de base
    feats = {}
    for v in variables:
        x = s[v]
        feats[f"{v}"] = x
        for w in WINDOWS:
            roll = x.rolling(w, min_periods=1)
            feats[f"{v}__media_{w}"] = roll.mean()
            feats[f"{v}__desvio_{w}"] = roll.std()
        r24 = x.rolling("24h", min_periods=1)
        feats[f"{v}__min_24h"] = r24.min()
        feats[f"{v}__max_24h"] = r24.max()
        feats[f"{v}__tend_6h_24h"] = feats[f"{v}__media_6h"] - feats[f"{v}__media_24h"]
        med7 = x.rolling("7D", min_periods=12).median()
        mad7 = (x - med7).abs().rolling("7D", min_periods=12).median()
        feats[f"{v}__desvio_base_7d"] = (feats[f"{v}__media_6h"] - med7) / (1.4826 * mad7 + 1e-6)
    f = pd.DataFrame(feats)
    f.index.name = COL_TIMESTAMP
    return f.reset_index()


def build_dataset(ds: Dataset, equipamentos: list[str], horizonte_h: float = 24.0,
                  variables: list[str] | None = None) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, list[str]]:
    """Retorna X, y, meta (timestamp, equipamento, estado, horas_ate_falha) e lista de atributos."""
    variables = variables or variables_for(ds, equipamentos)
    if not variables:
        raise ValueError("Os equipamentos selecionados não têm variáveis numéricas em comum.")
    H = pd.Timedelta(hours=horizonte_h)
    X_parts, meta_parts = [], []
    for eq in equipamentos:
        g = ds.subset(eq).sort_values(COL_TIMESTAMP).reset_index(drop=True)
        f = _features_one(g, variables)
        starts = failure_starts(g)
        ts = g[COL_TIMESTAMP]
        if len(starts):
            pos = np.searchsorted(starts.values, ts.values, side="right")
            nxt = np.where(pos < len(starts), starts.values[np.minimum(pos, len(starts) - 1)], np.datetime64("NaT", "ns"))
            ttf = (pd.Series(nxt) - ts).dt.total_seconds() / 3600
            event_id = np.where(pos < len(starts), pos, -1)
        else:
            ttf = pd.Series(np.nan, index=ts.index)
            event_id = np.full(len(ts), -1)
        state = g[COL_STATUS] if COL_STATUS in g.columns else pd.Series(None, index=g.index)
        meta = pd.DataFrame({
            COL_TIMESTAMP: ts, COL_EQUIPMENT: eq, COL_STATUS: state.values,
            "horas_ate_falha": ttf.values,
            "evento": [f"{eq}#{i}" if i >= 0 else None for i in event_id],
        })
        X_parts.append(f.drop(columns=[COL_TIMESTAMP]))
        meta_parts.append(meta)
    X = pd.concat(X_parts, ignore_index=True)
    meta = pd.concat(meta_parts, ignore_index=True)
    y = ((meta["horas_ate_falha"] > 0) & (meta["horas_ate_falha"] <= H.total_seconds() / 3600)).astype(int)

    keep = ~meta[COL_STATUS].isin(["falha", "manutencao"])
    keep &= X[[v for v in variables]].notna().any(axis=1)
    X, y, meta = X[keep].reset_index(drop=True), y[keep].reset_index(drop=True), meta[keep].reset_index(drop=True)
    meta.loc[y == 0, "evento"] = None
    return X, y, meta, list(X.columns)
