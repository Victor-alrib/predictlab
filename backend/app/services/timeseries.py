"""Análise temporal: tendência, médias móveis, sazonalidade, perfil e comparação."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.stattools import acf

from ..config import COL_STATUS, COL_TIMESTAMP
from ..store import Dataset
from .quality import clean_float, downsample, resample_equipment, series_to_list, ts_to_list


class AnalysisError(ValueError):
    pass


def _check_var(ds: Dataset, equipamento: str, variavel: str) -> pd.DataFrame:
    if equipamento not in ds.equipment:
        raise AnalysisError(f"Equipamento '{equipamento}' não encontrado.")
    if variavel not in ds.variable_keys():
        raise AnalysisError(f"Variável '{variavel}' não encontrada.")
    g = ds.subset(equipamento)
    if g[variavel].notna().sum() < 10:
        raise AnalysisError(f"A variável '{variavel}' tem menos de 10 leituras para {equipamento}.")
    return g


def _window_steps(window: str, freq: str) -> int:
    return max(1, int(round(pd.Timedelta(window) / pd.Timedelta(freq))))


def trend(ds: Dataset, equipamento: str, variavel: str, janelas: list[str] | None = None,
          freq: str = "auto", apenas_operando: bool = False, max_points: int = 3000) -> dict:
    g = _check_var(ds, equipamento, variavel)
    if apenas_operando and COL_STATUS in g.columns:
        g = g[g[COL_STATUS] == "operando"]
    tmp = ds.__class__(**{**ds.__dict__, "df": g})  # visão filtrada com a mesma interface
    r, freq = resample_equipment(tmp, equipamento, [variavel], freq)
    s = r[variavel]
    janelas = janelas or ["6h", "24h", "7D"]

    # tendência linear (mínimos quadrados) em unidades por dia
    valid = s.dropna()
    x_days = (valid.index - valid.index[0]).total_seconds() / 86400
    slope = intercept = r_value = p_value = None
    if len(valid) >= 3 and np.ptp(x_days) > 0:
        lr = stats.linregress(x_days, valid.to_numpy())
        slope, intercept, r_value, p_value = lr.slope, lr.intercept, lr.rvalue, lr.pvalue
    # Mann-Kendall simplificado (tau de Kendall vs. tempo) — robusto a não linearidade
    tau = tau_p = None
    if len(valid) >= 10:
        sub = valid.iloc[:: max(1, len(valid) // 2000)]
        kt = stats.kendalltau(np.arange(len(sub)), sub.to_numpy())
        tau, tau_p = kt.statistic, kt.pvalue

    rolling = {}
    for w in janelas:
        steps = _window_steps(w, freq)
        rolling[w] = s.rolling(steps, min_periods=max(1, steps // 2)).mean()

    frame = pd.DataFrame({"valor": s, **{f"mm_{w}": v for w, v in rolling.items()}})
    frame = frame.reset_index().rename(columns={"index": COL_TIMESTAMP})
    frame = downsample(frame, [c for c in frame.columns if c != COL_TIMESTAMP], max_points)

    meta = ds.variable(variavel) or {}
    trend_line = None
    if slope is not None:
        xd = (pd.DatetimeIndex(frame[COL_TIMESTAMP]) - valid.index[0]).total_seconds() / 86400
        trend_line = series_to_list(pd.Series(intercept + slope * np.asarray(xd)))

    direction = "estável"
    if tau_p is not None and tau_p < 0.01 and abs(tau) > 0.1:
        direction = "crescente" if tau > 0 else "decrescente"

    return {
        "equipamento": equipamento, "variavel": variavel, "rotulo": meta.get("label", variavel),
        "unidade": meta.get("unit", ""), "frequencia": freq,
        "timestamps": ts_to_list(frame[COL_TIMESTAMP]),
        "valor": series_to_list(frame["valor"]),
        "medias_moveis": {w: series_to_list(frame[f"mm_{w}"]) for w in janelas},
        "linha_tendencia": trend_line,
        "estatisticas": {
            "inclinacao_por_dia": clean_float(slope),
            "r2": clean_float(r_value ** 2) if r_value is not None else None,
            "p_valor_regressao": clean_float(p_value),
            "kendall_tau": clean_float(tau),
            "kendall_p": clean_float(tau_p),
            "direcao": direction,
            "media": clean_float(valid.mean()), "desvio": clean_float(valid.std()),
            "minimo": clean_float(valid.min()), "maximo": clean_float(valid.max()),
            "n": int(len(valid)),
        },
        "apenas_operando": apenas_operando,
    }


CANDIDATE_PERIODS_H = {"diária (24 h)": 24, "semanal (168 h)": 168, "turno (8 h)": 8, "12 h": 12}


def seasonality(ds: Dataset, equipamento: str, variavel: str, max_points: int = 3000) -> dict:
    g = _check_var(ds, equipamento, variavel)
    tmp = ds.__class__(**{**ds.__dict__, "df": g})
    r, _ = resample_equipment(tmp, equipamento, [variavel], "1h")
    s = r[variavel]
    n_valid = int(s.notna().sum())
    span_h = len(s)
    if n_valid < 48:
        raise AnalysisError("São necessárias pelo menos 48 horas de dados para analisar sazonalidade.")
    filled = s.interpolate(limit=6).ffill().bfill()

    # autocorrelação nos períodos candidatos
    nlags = min(span_h // 2, 24 * 8)
    ac = acf(filled.to_numpy(), nlags=nlags, fft=True, missing="conservative")
    candidates = []
    for name, p in CANDIDATE_PERIODS_H.items():
        if p < nlags and span_h >= 2 * p:
            candidates.append({"periodo": name, "horas": p, "acf": round(float(ac[p]), 4)})
    candidates.sort(key=lambda c: c["acf"], reverse=True)
    # limiar de significância aproximado (±1.96/sqrt(n))
    sig = 1.96 / np.sqrt(len(filled))
    best = next((c for c in candidates if c["acf"] > max(0.3, sig)), None)

    out = {
        "equipamento": equipamento, "variavel": variavel,
        "acf": {"lags_h": list(range(len(ac))), "valores": [round(float(v), 4) for v in ac],
                "limiar_significancia": round(float(sig), 4)},
        "candidatos": candidates, "periodo_detectado": best,
        "decomposicao": None, "forca_sazonal": None, "forca_tendencia": None,
    }
    if best:
        period = best["horas"]
        res = STL(filled, period=period, robust=True).fit()
        var_r = np.var(res.resid)
        fs = max(0.0, 1 - var_r / np.var(res.seasonal + res.resid))
        ft = max(0.0, 1 - var_r / np.var(res.trend + res.resid))
        dec = pd.DataFrame({"observado": filled, "tendencia": res.trend, "sazonal": res.seasonal,
                            "residuo": res.resid}).reset_index().rename(columns={"index": COL_TIMESTAMP})
        dec = downsample(dec, ["observado", "tendencia", "sazonal", "residuo"], max_points)
        out["decomposicao"] = {
            "timestamps": ts_to_list(dec[COL_TIMESTAMP]),
            **{k: series_to_list(dec[k]) for k in ("observado", "tendencia", "sazonal", "residuo")},
        }
        out["forca_sazonal"] = round(float(fs), 4)
        out["forca_tendencia"] = round(float(ft), 4)
    out["interpolacao"] = ("Lacunas de até 6 h foram interpoladas linearmente apenas para a decomposição; "
                           "a série original não é alterada.")
    return out


def profile(ds: Dataset, equipamento: str, variavel: str) -> dict:
    """Comportamento histórico: perfil horário, perfil por dia da semana e distribuição."""
    g = _check_var(ds, equipamento, variavel)
    s = g.set_index(COL_TIMESTAMP)[variavel].dropna()
    by_hour = s.groupby(s.index.hour).agg(["mean", "std", lambda x: x.quantile(0.1), lambda x: x.quantile(0.9)])
    by_hour.columns = ["media", "desvio", "p10", "p90"]
    by_dow = s.groupby(s.index.dayofweek).mean()
    dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    counts, edges = np.histogram(s.to_numpy(), bins=40)
    daily = s.resample("1D").agg(["mean", "min", "max"])
    by_status = None
    if COL_STATUS in g.columns and g[COL_STATUS].notna().any():
        by_status = {str(k): {"media": clean_float(v.mean()), "n": int(v.notna().sum())}
                     for k, v in g.groupby(COL_STATUS)[variavel]}
    return {
        "equipamento": equipamento, "variavel": variavel,
        "perfil_horario": {"hora": by_hour.index.tolist(), **{c: series_to_list(by_hour[c]) for c in by_hour.columns}},
        "perfil_semanal": {"dia": [dias[i] for i in by_dow.index], "media": series_to_list(by_dow)},
        "histograma": {"contagem": counts.tolist(), "bordas": [round(float(e), 4) for e in edges]},
        "diario": {"data": [d.date().isoformat() for d in daily.index],
                   **{c: series_to_list(daily[c]) for c in daily.columns}},
        "por_estado": by_status,
        "quantis": {q: clean_float(s.quantile(float(q))) for q in ("0.01", "0.05", "0.25", "0.5", "0.75", "0.95", "0.99")},
    }


def _period_stats(s: pd.Series) -> dict:
    return {"n": int(s.notna().sum()), "media": clean_float(s.mean()), "desvio": clean_float(s.std()),
            "minimo": clean_float(s.min()), "maximo": clean_float(s.max()),
            "mediana": clean_float(s.median()), "p95": clean_float(s.quantile(0.95))}


def compare_periods(ds: Dataset, equipamento: str, variavel: str,
                    periodo_a: tuple[str, str], periodo_b: tuple[str, str],
                    apenas_operando: bool = True) -> dict:
    g = _check_var(ds, equipamento, variavel)
    if apenas_operando and COL_STATUS in g.columns and g[COL_STATUS].notna().any():
        g = g[g[COL_STATUS] == "operando"]
    s = g.set_index(COL_TIMESTAMP)[variavel]

    def cut(p):
        a, b = pd.Timestamp(p[0]), pd.Timestamp(p[1])
        if b <= a:
            raise AnalysisError("O fim do período deve ser posterior ao início.")
        return s[(s.index >= a) & (s.index < b)].dropna()

    sa, sb = cut(periodo_a), cut(periodo_b)
    if len(sa) < 5 or len(sb) < 5:
        raise AnalysisError("Cada período precisa de ao menos 5 leituras válidas.")
    mw = stats.mannwhitneyu(sa, sb, alternative="two-sided")
    # tamanho de efeito: d de Cohen (com desvio combinado)
    pooled = np.sqrt(((len(sa) - 1) * sa.var() + (len(sb) - 1) * sb.var()) / (len(sa) + len(sb) - 2))
    d = (sb.mean() - sa.mean()) / pooled if pooled > 0 else None
    delta_pct = (sb.mean() - sa.mean()) / abs(sa.mean()) * 100 if sa.mean() else None

    # perfis horários sobrepostos para visualização
    pa = sa.groupby(sa.index.hour).mean()
    pb = sb.groupby(sb.index.hour).mean()
    bins = np.histogram_bin_edges(pd.concat([sa, sb]).to_numpy(), bins=30)
    return {
        "equipamento": equipamento, "variavel": variavel, "apenas_operando": apenas_operando,
        "periodo_a": {"inicio": periodo_a[0], "fim": periodo_a[1], **_period_stats(sa)},
        "periodo_b": {"inicio": periodo_b[0], "fim": periodo_b[1], **_period_stats(sb)},
        "diferenca_media": clean_float(sb.mean() - sa.mean()),
        "diferenca_pct": clean_float(delta_pct),
        "cohen_d": clean_float(d),
        "mann_whitney_p": clean_float(mw.pvalue),
        "significativo_5pct": bool(mw.pvalue < 0.05),
        "interpretacao": _interpret(d, mw.pvalue),
        "perfil_horario": {"hora": list(range(24)),
                           "a": [clean_float(pa.get(h)) for h in range(24)],
                           "b": [clean_float(pb.get(h)) for h in range(24)]},
        "histograma": {"bordas": [round(float(e), 4) for e in bins],
                       "a": np.histogram(sa, bins=bins)[0].tolist(),
                       "b": np.histogram(sb, bins=bins)[0].tolist()},
    }


def _interpret(d, p) -> str:
    if p >= 0.05:
        return "Sem evidência estatística de diferença entre os períodos (p ≥ 0,05)."
    if d is None:
        return "Diferença estatisticamente significativa."
    mag = abs(d)
    size = "desprezível" if mag < 0.2 else "pequena" if mag < 0.5 else "média" if mag < 0.8 else "grande"
    sentido = "maior" if d > 0 else "menor"
    return (f"O período B tem valores {sentido}s que o A, com diferença {size} (d de Cohen = {d:.2f}). "
            "Com muitas amostras, até diferenças pequenas ficam significativas — avalie o tamanho do efeito.")
