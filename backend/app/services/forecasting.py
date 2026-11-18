"""Modelos de previsão temporal (forecasting) de variáveis de processo.

A série é reamostrada para uma grade horária (média), lacunas curtas são
interpoladas e os modelos são avaliados em um **holdout final** (os últimos
dias da série), simulando o uso real: prever o futuro a partir do passado.

Modelos:
* ``ingenuo_sazonal`` — repete o valor do mesmo horário do ciclo anterior
  (linha de base obrigatória: um modelo que não supera isso não agrega valor).
* ``holt_winters`` — suavização exponencial com tendência amortecida e
  sazonalidade aditiva.
* ``sarimax_fourier`` — ARIMA com termos de Fourier como regressores para a
  sazonalidade (mais leve que um SARIMA sazonal completo em dados horários).
"""

from __future__ import annotations

import time
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

from ..store import Dataset
from .quality import clean_float, resample_equipment, series_to_list, ts_to_list

FORECAST_MODELS = {
    "ingenuo_sazonal": "Ingênuo sazonal (linha de base)",
    "holt_winters": "Holt-Winters (suavização exponencial)",
    "sarimax_fourier": "ARIMA + termos de Fourier",
}


class ForecastError(ValueError):
    pass


def _fourier(index: pd.DatetimeIndex, period_h: int, K: int) -> pd.DataFrame:
    t = (index - pd.Timestamp("2000-01-01")).total_seconds() / 3600
    cols = {}
    for k in range(1, K + 1):
        cols[f"s{k}"] = np.sin(2 * np.pi * k * t / period_h)
        cols[f"c{k}"] = np.cos(2 * np.pi * k * t / period_h)
    return pd.DataFrame(cols, index=index)


def _fit_predict(name: str, train: pd.Series, steps: int, period: int, future_index: pd.DatetimeIndex):
    """Retorna (previsão, limite_inferior, limite_superior) como arrays."""
    if name == "ingenuo_sazonal":
        last = train.iloc[-period:].to_numpy()
        reps = int(np.ceil(steps / period))
        pred = np.tile(last, reps)[:steps]
        resid = (train - train.shift(period)).dropna()
        sd = resid.std() if len(resid) else 0.0
        k = np.sqrt(np.arange(1, steps + 1) / period + 1)  # cresce a cada ciclo
        return pred, pred - 1.96 * sd * k, pred + 1.96 * sd * k
    if name == "holt_winters":
        use_season = len(train) >= 2 * period
        m = ExponentialSmoothing(train, trend="add", damped_trend=True,
                                 seasonal="add" if use_season else None,
                                 seasonal_periods=period if use_season else None,
                                 initialization_method="estimated").fit(optimized=True)
        pred = m.forecast(steps).to_numpy()
        sd = np.std(m.resid)
        k = np.sqrt(np.arange(1, steps + 1))
        k = np.minimum(k, np.sqrt(period))
        return pred, pred - 1.96 * sd * k, pred + 1.96 * sd * k
    if name == "sarimax_fourier":
        ex_tr = _fourier(train.index, period, 3)
        ex_fu = _fourier(future_index, period, 3)
        m = SARIMAX(train, exog=ex_tr, order=(2, 0, 1), trend="c",
                    enforce_stationarity=False, enforce_invertibility=False).fit(disp=False, maxiter=60)
        fc = m.get_forecast(steps, exog=ex_fu)
        ci = fc.conf_int(alpha=0.05).to_numpy()
        return fc.predicted_mean.to_numpy(), ci[:, 0], ci[:, 1]
    raise ForecastError(f"Modelo de previsão desconhecido: {name}")


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    e = y - p
    denom = np.abs(y).sum()
    return {"mae": clean_float(np.mean(np.abs(e))), "rmse": clean_float(np.sqrt(np.mean(e ** 2))),
            "wape_pct": clean_float(np.abs(e).sum() / denom * 100) if denom > 0 else None,
            "vies": clean_float(np.mean(p - y))}


def run_forecast(ds: Dataset, equipamento: str, variavel: str, modelos: list[str] | None = None,
                 horizonte_h: int = 48, holdout_h: int = 168, periodo_h: int = 24,
                 historico_h: int = 24 * 30) -> dict:
    t_start = time.time()
    modelos = modelos or list(FORECAST_MODELS)
    if equipamento not in ds.equipment:
        raise ForecastError(f"Equipamento '{equipamento}' não encontrado.")
    if variavel not in ds.variable_keys():
        raise ForecastError(f"Variável '{variavel}' não encontrada.")
    r, _ = resample_equipment(ds, equipamento, [variavel], "1h")
    s = r[variavel]
    # usa só o histórico recente (custo computacional e relevância)
    s = s.iloc[-(historico_h + holdout_h):]
    n_nan = int(s.isna().sum())
    s = s.interpolate(limit=12).ffill().bfill()
    if s.isna().any() or len(s) < holdout_h + 3 * periodo_h:
        raise ForecastError(f"Série curta demais: são necessárias ao menos {holdout_h + 3 * periodo_h} horas "
                            f"de dados (holdout de {holdout_h} h + 3 ciclos de {periodo_h} h).")
    train, test = s.iloc[:-holdout_h], s.iloc[-holdout_h:]

    results, avisos = [], []
    if n_nan:
        avisos.append(f"{n_nan} hora(s) sem dados foram interpoladas (até 12 h consecutivas).")
    future_idx = pd.date_range(s.index[-1] + pd.Timedelta("1h"), periods=horizonte_h, freq="1h")
    for name in modelos:
        if name not in FORECAST_MODELS:
            raise ForecastError(f"Modelo de previsão desconhecido: {name}")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                p_test, lo_t, hi_t = _fit_predict(name, train, holdout_h, periodo_h, test.index)
                p_fut, lo_f, hi_f = _fit_predict(name, s, horizonte_h, periodo_h, future_idx)
            cover = float(np.mean((test.to_numpy() >= lo_t) & (test.to_numpy() <= hi_t)))
            results.append({
                "modelo": name, "nome": FORECAST_MODELS[name],
                "metricas_holdout": {**_metrics(test.to_numpy(), p_test), "cobertura_ic95": clean_float(cover)},
                "holdout": {"previsto": series_to_list(pd.Series(p_test)),
                            "inferior": series_to_list(pd.Series(lo_t)), "superior": series_to_list(pd.Series(hi_t))},
                "futuro": {"previsto": series_to_list(pd.Series(p_fut)),
                           "inferior": series_to_list(pd.Series(lo_f)), "superior": series_to_list(pd.Series(hi_f))},
            })
        except Exception as exc:  # um modelo que falha não derruba os demais
            results.append({"modelo": name, "nome": FORECAST_MODELS[name], "erro": str(exc)[:300]})

    base = next((r_ for r_ in results if r_["modelo"] == "ingenuo_sazonal" and "erro" not in r_), None)
    if base:
        for r_ in results:
            if "erro" in r_ or r_ is base:
                continue
            b, m = base["metricas_holdout"]["mae"], r_["metricas_holdout"]["mae"]
            r_["metricas_holdout"]["ganho_vs_base_pct"] = clean_float((b - m) / b * 100) if b else None
    ok = [r_ for r_ in results if "erro" not in r_]
    best = min(ok, key=lambda r_: r_["metricas_holdout"]["mae"])["modelo"] if ok else None

    meta = ds.variable(variavel) or {}
    hist = s.iloc[-(holdout_h + 24 * 7):]
    return {
        "tipo": "previsao", "modelo": "comparacao_previsao", "modelo_nome": "Previsão temporal",
        "dataset_id": ds.id, "dataset_sintetico": ds.is_synthetic, "dataset_origem": ds.data_origin,
        "equipamentos": [equipamento], "variavel": variavel,
        "rotulo": meta.get("label", variavel), "unidade": meta.get("unit", ""),
        "parametros": {"horizonte_h": horizonte_h, "holdout_h": holdout_h, "periodo_h": periodo_h,
                       "historico_h": historico_h, "modelos": modelos},
        "historico": {"timestamps": ts_to_list(hist.index), "valor": series_to_list(hist)},
        "holdout_timestamps": ts_to_list(test.index),
        "holdout_real": series_to_list(test),
        "futuro_timestamps": ts_to_list(future_idx),
        "resultados": results, "melhor_modelo": best,
        "avisos": avisos, "duracao_s": round(time.time() - t_start, 2),
    }
