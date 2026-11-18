"""Sistema de alertas com três origens claramente separadas.

1. ``limite`` — **Alertas por limite configurado**: a variável ultrapassou um
   valor mínimo/máximo definido pelo usuário (equivalente ao alarme clássico
   de um SCADA). Determinístico e auditável.
2. ``estatistica`` — **Anomalias estatísticas**: a leitura se afasta muito do
   comportamento recente do próprio equipamento (z-score robusto) ou foi
   considerada atípica por um Isolation Forest. Não implica falha.
3. ``modelo`` — **Previsões de modelos**: um classificador treinado estimou
   probabilidade alta de falha iminente, ou uma previsão temporal projeta o
   cruzamento de um limite configurado. São estimativas, sujeitas a erro.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from ..config import COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP
from ..store import Dataset, store
from .quality import clean_float, equipment_variables, median_interval

ORIGINS = {
    "limite": "Limite configurado",
    "estatistica": "Anomalia estatística",
    "modelo": "Previsão de modelo",
}
SEVERITIES = ("baixa", "media", "alta")

_cache: dict[str, list[dict]] = {}


def thresholds_for(ds: Dataset, equipamento: str) -> dict:
    """Limites efetivos: específicos do equipamento sobrescrevem os globais ('*')."""
    out = {k: dict(v) for k, v in (ds.thresholds.get("*") or {}).items()}
    for k, v in (ds.thresholds.get(equipamento) or {}).items():
        out[k] = {**out.get(k, {}), **v}
    return out


def _episodes(ts: pd.Series, mask: np.ndarray, max_gap: pd.Timedelta) -> list[tuple[int, int]]:
    idx = np.where(mask)[0]
    if not len(idx):
        return []
    tvals = ts.to_numpy()
    eps, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if (tvals[i] - tvals[prev]) > max_gap:
            eps.append((start, prev))
            start = i
        prev = i
    eps.append((start, prev))
    return eps


def br(x: float, spec: str = ".2f") -> str:
    """Formata número no padrão brasileiro (vírgula decimal)."""
    return format(x, spec).replace(".", ",")


def _fmt_dur(h: float) -> str:
    return f"{h * 60:.0f} min" if h < 1 else f"{br(h, '.1f')} h"


def threshold_alerts(ds: Dataset, equipamento: str, min_duracao_min: float = 0) -> list[dict]:
    g = ds.subset(equipamento).sort_values(COL_TIMESTAMP)
    ts = g[COL_TIMESTAMP].reset_index(drop=True)
    med = median_interval(ts) or pd.Timedelta("15min")
    alerts = []
    for var, lim in thresholds_for(ds, equipamento).items():
        if var not in g.columns:
            continue
        x = g[var].to_numpy(dtype=float)
        meta = ds.variable(var) or {"label": var, "unit": ""}
        for kind, cmp in (("max", np.greater), ("min", np.less)):
            ref = lim.get(kind)
            if ref is None:
                continue
            with np.errstate(invalid="ignore"):
                mask = cmp(x, float(ref)) & ~np.isnan(x)
            for a, b in _episodes(ts, mask, max(2 * med, pd.Timedelta("1h"))):  # agrupa oscilações em torno do limite
                dur_h = ((ts[b] - ts[a]) + med).total_seconds() / 3600
                if dur_h * 60 < (lim.get("duracao_min_min") or min_duracao_min):
                    continue
                seg = x[a:b + 1]
                peak = np.nanmax(seg) if kind == "max" else np.nanmin(seg)
                word = "acima do máximo" if kind == "max" else "abaixo do mínimo"
                alerts.append({
                    "origem": "limite", "metodo": f"Limite {'máx.' if kind == 'max' else 'mín.'} = {br(ref, 'g')} {meta['unit']}".strip(),
                    "equipamento": equipamento, "variavel": var,
                    "inicio": ts[a].isoformat(), "fim": (ts[b] + med).isoformat(), "duracao_h": round(dur_h, 3),
                    "severidade": lim.get("severidade", "media"),
                    "valor": clean_float(round(float(peak), 3)), "referencia": float(ref),
                    "mensagem": f"{meta['label']} {word} ({br(peak)} {meta['unit']} vs. limite {br(ref, 'g')}) "
                                f"por {_fmt_dur(dur_h)}.",
                })
    return alerts


def _seasonal_daily(x: pd.Series) -> bool:
    h = x.resample("1h").mean().interpolate(limit=6).dropna()
    if len(h) < 24 * 4:
        return False
    return bool(h.autocorr(24) > 0.5)


def statistical_alerts(ds: Dataset, equipamento: str, k: float = 4.0, janela: str = "7D",
                       min_amostras: int = 3) -> list[dict]:
    """z-score robusto: (x − mediana) / (1,4826·MAD), com linha de base só do passado.

    Para variáveis com ciclo diário forte, a linha de base é calculada por hora
    do dia (compara 12h de hoje com 12h dos dias anteriores).
    """
    g = ds.subset(equipamento).sort_values(COL_TIMESTAMP).reset_index(drop=True)
    ts = g[COL_TIMESTAMP]
    med_dt = median_interval(ts) or pd.Timedelta("15min")
    operating = (g[COL_STATUS] == "operando").to_numpy() if (COL_STATUS in g.columns and g[COL_STATUS].notna().any()) \
        else np.ones(len(g), dtype=bool)
    alerts = []
    for var in equipment_variables(ds, equipamento):
        x = pd.Series(g[var].to_numpy(dtype=float), index=pd.DatetimeIndex(ts))
        x_op = x.where(operating)
        if x_op.notna().sum() < 50:
            continue
        hourly = _seasonal_daily(x_op)
        if hourly:
            med = pd.Series(np.nan, index=x.index)
            mad = pd.Series(np.nan, index=x.index)
            for _, xs in x_op.groupby(x_op.index.hour):
                m = xs.rolling(janela, min_periods=5).median().shift(1)
                d = (xs - m).abs().rolling(janela, min_periods=5).median().shift(1)
                med.loc[xs.index] = m.values
                mad.loc[xs.index] = d.values
        else:
            med = x_op.rolling(janela, min_periods=20).median().shift(1)
            mad = (x_op - med).abs().rolling(janela, min_periods=20).median().shift(1)
        scale = 1.4826 * mad
        floor = 0.01 * np.nanmedian(np.abs(x_op.to_numpy())) + 1e-9  # evita divisão por ~0
        z = (x_op - med) / np.maximum(scale.to_numpy(), floor)
        zv = z.to_numpy()
        with np.errstate(invalid="ignore"):
            mask = np.abs(zv) > k
        meta = ds.variable(var) or {"label": var, "unit": ""}
        for a, b in _episodes(ts, mask, 4 * med_dt):
            n = int(mask[a:b + 1].sum())
            if n < min_amostras:
                continue
            seg = zv[a:b + 1]
            i_peak = int(np.nanargmax(np.abs(seg)))
            zpk = float(seg[i_peak])
            dur_h = ((ts[b] - ts[a]) + med_dt).total_seconds() / 3600
            val = float(x.iloc[a + i_peak])
            base = float(med.iloc[a + i_peak])
            alerts.append({
                "origem": "estatistica",
                "metodo": "z-score robusto" + (" (perfil horário)" if hourly else ""),
                "equipamento": equipamento, "variavel": var,
                "inicio": ts[a].isoformat(), "fim": (ts[b] + med_dt).isoformat(), "duracao_h": round(dur_h, 3),
                "severidade": "alta" if abs(zpk) > 2 * k else "media",
                "valor": clean_float(round(val, 3)), "referencia": clean_float(round(base, 3)),
                "score": round(zpk, 2),
                "mensagem": f"{meta['label']} {'acima' if zpk > 0 else 'abaixo'} do comportamento recente "
                            f"(z = {br(zpk, '+.1f')}; {br(val)} vs. mediana {br(base)} {meta['unit']}).",
            })
    return alerts


def _model_alerts_from_run(run: dict, ds: Dataset) -> list[dict]:
    alerts = []
    if run["tipo"] in ("classificacao", "anomalia"):
        thr = run["parametros"].get("limiar", 0.5) if run["tipo"] == "classificacao" else run.get("limiar_exibicao")
        if thr is None:
            return []
        origem = "modelo" if run["tipo"] == "classificacao" else "estatistica"
        for eq, s in run["series"].items():
            ts = pd.Series(pd.to_datetime(s["timestamps"]))
            sc = np.array([np.nan if v is None else v for v in s["score"]], dtype=float)
            with np.errstate(invalid="ignore"):
                mask = sc >= thr
            step = ts.diff().median() if len(ts) > 1 else pd.Timedelta("1h")
            for a, b in _episodes(ts, mask, 2 * step):
                peak = float(np.nanmax(sc[a:b + 1]))
                dur_h = ((ts[b] - ts[a]) + step).total_seconds() / 3600
                if run["tipo"] == "classificacao":
                    msg = (f"{run['modelo_nome']} estima probabilidade de falha em até "
                           f"{br(run['parametros']['horizonte_h'], 'g')} h de {peak:.0%} (limiar {thr:.0%}).")
                else:
                    msg = f"Isolation Forest classificou o comportamento como atípico (escore {br(peak)})."
                alerts.append({
                    "origem": origem, "metodo": run["modelo_nome"], "run_id": run["id"],
                    "equipamento": eq, "variavel": None,
                    "inicio": ts[a].isoformat(), "fim": (ts[b] + step).isoformat(), "duracao_h": round(dur_h, 3),
                    "severidade": "alta" if peak >= max(0.8, thr) else "media",
                    "valor": round(peak, 4), "referencia": thr,
                    "mensagem": msg + " Período de teste (fora da amostra de treino).",
                })
    elif run["tipo"] == "previsao":
        eq, var = run["equipamentos"][0], run["variavel"]
        lim = thresholds_for(ds, eq).get(var) or {}
        best = next((r for r in run["resultados"] if r["modelo"] == run.get("melhor_modelo")), None)
        if best and "erro" not in best and (lim.get("max") is not None or lim.get("min") is not None):
            fut = np.array([np.nan if v is None else v for v in best["futuro"]["previsto"]], dtype=float)
            tfut = pd.to_datetime(run["futuro_timestamps"])
            for kind in ("max", "min"):
                ref = lim.get(kind)
                if ref is None:
                    continue
                cross = np.where(fut > ref)[0] if kind == "max" else np.where(fut < ref)[0]
                if len(cross):
                    i = int(cross[0])
                    alerts.append({
                        "origem": "modelo", "metodo": f"Previsão: {best['nome']}", "run_id": run["id"],
                        "equipamento": eq, "variavel": var,
                        "inicio": tfut[i].isoformat(), "fim": tfut[cross[-1]].isoformat(),
                        "duracao_h": float(len(cross)), "severidade": lim.get("severidade", "media"),
                        "valor": clean_float(round(float(fut[i]), 3)), "referencia": float(ref),
                        "mensagem": f"A previsão projeta {var} {'acima' if kind == 'max' else 'abaixo'} do limite "
                                    f"{br(ref, 'g')} em {i + 1} h após o fim dos dados.",
                    })
    return alerts


def compute_alerts(ds: Dataset, equipamento: str | None = None, origens: list[str] | None = None,
                   k: float = 4.0) -> list[dict]:
    runs = store.list_runs(ds.id)
    key_src = json.dumps({"ds": ds.id, "rows": len(ds.df), "thr": ds.thresholds, "k": k,
                          "runs": [r["id"] for r in runs]}, sort_keys=True, default=str)
    key = hashlib.md5(key_src.encode()).hexdigest()
    if key not in _cache:
        alerts: list[dict] = []
        for eq in ds.equipment:
            alerts += threshold_alerts(ds, eq)
            alerts += statistical_alerts(ds, eq, k=k)
        # apenas a execução mais recente de cada (tipo, modelo, equipamentos)
        seen = set()
        for r in runs:
            sig = (r["tipo"], r["modelo"], tuple(r["equipamentos"]), r.get("variavel"))
            if sig in seen:
                continue
            seen.add(sig)
            alerts += _model_alerts_from_run(r, ds)
        alerts.sort(key=lambda a: a["inicio"], reverse=True)
        for i, a in enumerate(alerts):
            a["id"] = f"AL-{len(alerts) - i:05d}"
        if len(_cache) > 32:
            _cache.clear()
        _cache[key] = alerts
    out = _cache[key]
    if equipamento and equipamento != "*":
        out = [a for a in out if a["equipamento"] == equipamento]
    if origens:
        out = [a for a in out if a["origem"] in origens]
    return out


def summarize(alerts: list[dict]) -> dict:
    by_origin = {o: sum(1 for a in alerts if a["origem"] == o) for o in ORIGINS}
    by_sev = {s: sum(1 for a in alerts if a["severidade"] == s) for s in SEVERITIES}
    by_eq: dict[str, dict] = {}
    for a in alerts:
        d = by_eq.setdefault(a["equipamento"], {o: 0 for o in ORIGINS})
        d[a["origem"]] += 1
    return {"total": len(alerts), "por_origem": by_origin, "por_severidade": by_sev, "por_equipamento": by_eq}


def invalidate_cache() -> None:
    _cache.clear()
