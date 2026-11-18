"""Qualidade de dados e utilitários de série temporal compartilhados."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP
from ..store import Dataset


def clean_float(x) -> float | None:
    """Converte para float serializável em JSON (NaN/inf viram None)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def series_to_list(s: pd.Series, digits: int = 4) -> list:
    arr = s.to_numpy(dtype=float, na_value=np.nan)
    return [None if np.isnan(v) or np.isinf(v) else round(float(v), digits) for v in arr]


def ts_to_list(s: pd.Series | pd.DatetimeIndex) -> list[str]:
    idx = pd.DatetimeIndex(s)
    return [t.isoformat() for t in idx]


def median_interval(ts: pd.Series) -> pd.Timedelta | None:
    d = pd.Series(ts).sort_values().diff().dropna()
    d = d[d > pd.Timedelta(0)]
    return d.median() if len(d) else None


def human_td(td: pd.Timedelta | None) -> str:
    if td is None or pd.isna(td):
        return "—"
    s = td.total_seconds()
    if s < 60:
        return f"{s:.0f} s"
    if s < 3600:
        return f"{s / 60:.0f} min"
    if s < 86400:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} dias"


def pandas_freq(td: pd.Timedelta | None) -> str:
    """Frequência pandas para reamostragem, arredondada para um valor 'redondo'."""
    if td is None:
        return "1h"
    s = max(1, int(round(td.total_seconds())))
    for cand in (1, 5, 10, 15, 30, 60, 300, 600, 900, 1800, 3600, 7200, 21600, 86400):
        if s <= cand:
            return f"{cand}s"
    return "1D"


def quality_report(ds: Dataset) -> dict:
    out = []
    for eq, g in ds.df.groupby(COL_EQUIPMENT):
        g = g.sort_values(COL_TIMESTAMP)
        ts = g[COL_TIMESTAMP]
        med = median_interval(ts)
        gaps = []
        if med is not None:
            diffs = ts.diff()
            mask = diffs > 3 * med
            for t_end, d in zip(ts[mask], diffs[mask]):
                gaps.append({"fim": t_end.isoformat(), "duracao": human_td(d), "duracao_s": d.total_seconds()})
        # linhas com todas as variáveis vazias também contam como lacuna (perda de comunicação)
        keys = [k for k in ds.variable_keys() if k in g.columns]
        all_nan = g[keys].isna().all(axis=1) if keys else pd.Series(False, index=g.index)
        missing = {}
        for k in keys:
            present = g[k].notna().any()
            missing[k] = None if not present else round(float(g[k].isna().mean() * 100), 2)
        out.append({
            "equipamento": eq,
            "linhas": int(len(g)),
            "inicio": ts.min().isoformat(),
            "fim": ts.max().isoformat(),
            "intervalo_amostragem": human_td(med),
            "intervalo_amostragem_s": med.total_seconds() if med is not None else None,
            "lacunas_temporais": len(gaps),
            "maior_lacuna": human_td(pd.Timedelta(seconds=max(g_["duracao_s"] for g_ in gaps))) if gaps else "—",
            "linhas_sem_leitura": int(all_nan.sum()),
            "faltantes_pct": missing,  # None = variável inexistente para o equipamento
            "possui_estado": bool(COL_STATUS in g.columns and g[COL_STATUS].notna().any()),
        })
    return {"equipamentos": out}


def equipment_variables(ds: Dataset, equipamento: str) -> list[str]:
    g = ds.subset(equipamento)
    return [k for k in ds.variable_keys() if k in g.columns and g[k].notna().any()]


def downsample(g: pd.DataFrame, cols: list[str], max_points: int) -> pd.DataFrame:
    """Reduz o número de pontos por média em janelas de tempo (para gráficos)."""
    if len(g) <= max_points:
        return g[[COL_TIMESTAMP] + cols]
    span = (g[COL_TIMESTAMP].max() - g[COL_TIMESTAMP].min()).total_seconds()
    bin_s = max(1, int(math.ceil(span / max_points)))
    r = g.set_index(COL_TIMESTAMP)[cols].resample(f"{bin_s}s").mean()
    return r.reset_index()


def resample_equipment(ds: Dataset, equipamento: str, cols: list[str], freq: str | None = None,
                       agg: str = "mean") -> tuple[pd.DataFrame, str]:
    g = ds.subset(equipamento).sort_values(COL_TIMESTAMP)
    if freq is None or freq == "auto":
        freq = pandas_freq(median_interval(g[COL_TIMESTAMP]))
    r = g.set_index(COL_TIMESTAMP)[cols].resample(freq).agg(agg)
    return r, freq
