"""Indicadores de manutenção: MTBF, MTTR, disponibilidade e histórico de falhas.

Definições adotadas (documentadas também em ``docs/METODOLOGIA.md``):

* **Tempo de cada amostra** = intervalo até a próxima amostra do mesmo
  equipamento, limitado a 3x o intervalo de amostragem mediano. Intervalos
  maiores são contabilizados como "sem dados", e não como operação.
* **Episódio de falha (corretiva)** = sequência contínua de amostras em
  ``falha``, incluindo a ``manutencao`` imediatamente posterior (reparo).
  Episódios de ``manutencao`` que não começam com ``falha`` são preventivos e
  não entram no MTTR.
* **MTBF** = tempo em operação (``operando``) / número de falhas.
* **MTTR** = média da duração dos episódios de falha completos (episódios
  truncados no início ou no fim do dataset ficam fora da média).
* **Disponibilidade intrínseca** = MTBF / (MTBF + MTTR).
* **Disponibilidade observada** = 1 - (tempo em falha + manutenção) /
  tempo observado com dados.

Os indicadores só são calculados quando há dados suficientes; caso contrário
o resultado traz ``status = "insuficiente"`` e o motivo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import COL_EQUIPMENT, COL_STATUS, COL_TIMESTAMP
from ..store import Dataset
from .quality import clean_float, median_interval

DEFAULT_MIN_FAILURES = 2
DEFAULT_MIN_DAYS = 7.0


def _indicator(value, unit: str, ok: bool, reason: str | None = None, digits: int = 2) -> dict:
    v = clean_float(value)
    return {"valor": round(v, digits) if (ok and v is not None) else None, "unidade": unit,
            "status": "ok" if ok and v is not None else "insuficiente",
            "motivo": None if ok and v is not None else reason}


def _sample_durations(ts: pd.Series) -> tuple[np.ndarray, np.ndarray, pd.Timedelta]:
    """Duração (h) atribuída a cada amostra e duração do 'buraco' após ela."""
    med = median_interval(ts) or pd.Timedelta(minutes=1)
    nxt = ts.shift(-1) - ts
    nxt = nxt.fillna(med)
    cap = 3 * med
    covered = nxt.clip(upper=cap)
    gap = (nxt - cap).clip(lower=pd.Timedelta(0))
    return covered.dt.total_seconds().to_numpy() / 3600, gap.dt.total_seconds().to_numpy() / 3600, med


def _episodes(states: np.ndarray, hours: np.ndarray, ts: pd.Series) -> tuple[list[dict], list[dict]]:
    """Agrupa amostras em episódios de falha (corretiva) e manutenção preventiva."""
    failures, preventive = [], []
    n = len(states)
    i = 0
    while i < n:
        s = states[i]
        if s in ("falha", "manutencao"):
            j = i
            while j + 1 < n and states[j + 1] in ("falha", "manutencao"):
                j += 1
            seg = states[i:j + 1]
            if seg[0] == "falha":
                failures.append({
                    "inicio": ts.iloc[i].isoformat(),
                    "fim": (ts.iloc[j] + pd.Timedelta(hours=float(hours[j]))).isoformat(),
                    "duracao_h": round(float(hours[i:j + 1].sum()), 3),
                    "duracao_falha_h": round(float(hours[i:j + 1][seg == "falha"].sum()), 3),
                    "duracao_reparo_h": round(float(hours[i:j + 1][seg == "manutencao"].sum()), 3),
                    "truncada": bool(i == 0 or j == n - 1),
                    "_i": i, "_j": j,
                })
            else:
                # bloco iniciado por manutenção: preventiva; se contiver falha
                # depois, a parte a partir da falha é tratada como corretiva
                k_fail = next((k for k in range(i, j + 1) if states[k] == "falha"), None)
                end_prev = (k_fail - 1) if k_fail is not None else j
                preventive.append({
                    "inicio": ts.iloc[i].isoformat(),
                    "duracao_h": round(float(hours[i:end_prev + 1].sum()), 3),
                })
                if k_fail is not None:
                    seg2 = states[k_fail:j + 1]
                    failures.append({
                        "inicio": ts.iloc[k_fail].isoformat(),
                        "fim": (ts.iloc[j] + pd.Timedelta(hours=float(hours[j]))).isoformat(),
                        "duracao_h": round(float(hours[k_fail:j + 1].sum()), 3),
                        "duracao_falha_h": round(float(hours[k_fail:j + 1][seg2 == "falha"].sum()), 3),
                        "duracao_reparo_h": round(float(hours[k_fail:j + 1][seg2 == "manutencao"].sum()), 3),
                        "truncada": bool(j == n - 1),
                        "_i": k_fail, "_j": j,
                    })
            i = j + 1
        else:
            i += 1
    return failures, preventive


def equipment_indicators(g: pd.DataFrame, min_falhas: int = DEFAULT_MIN_FAILURES,
                         min_dias: float = DEFAULT_MIN_DAYS) -> dict:
    g = g.sort_values(COL_TIMESTAMP).reset_index(drop=True)
    eq = str(g[COL_EQUIPMENT].iloc[0]) if len(g) else "?"
    base = {"equipamento": eq, "motivos": []}

    if COL_STATUS not in g.columns or g[COL_STATUS].notna().sum() == 0:
        base.update({
            "suficiente": False,
            "motivos": ["O dataset não possui coluna de estado operacional mapeada. "
                        "Sem ela não é possível identificar falhas e reparos."],
            "indicadores": {k: _indicator(None, u, False, "sem coluna de estado")
                            for k, u in (("mtbf", "h"), ("mttr", "h"),
                                         ("disponibilidade_intrinseca", "%"),
                                         ("disponibilidade_observada", "%"),
                                         ("falhas_por_30d", "falhas/30 dias"))},
            "tempos_h": {}, "falhas": [], "preventivas": [], "frequencia_semanal": [],
            "n_falhas": 0, "n_falhas_completas": 0,
        })
        return base

    ts = g[COL_TIMESTAMP]
    hours, gap_h, med = _sample_durations(ts)
    raw_states = g[COL_STATUS].fillna("desconhecido").astype(str).to_numpy()
    known = raw_states != "desconhecido"

    t_total = float(hours.sum() + gap_h.sum())
    t_known = float(hours[known].sum())
    t_unknown = float(hours[~known].sum() + gap_h.sum())
    t_oper = float(hours[raw_states == "operando"].sum())
    t_standby = float(hours[raw_states == "parado"].sum())

    # episódios calculados apenas sobre as amostras com estado conhecido
    idx_known = np.where(known)[0]
    failures, preventive = _episodes(raw_states[idx_known], hours[idx_known], ts.iloc[idx_known].reset_index(drop=True))
    for f in failures:
        f.pop("_i"), f.pop("_j")

    t_fail_total = float(sum(f["duracao_h"] for f in failures))
    t_prev = float(sum(p["duracao_h"] for p in preventive))
    n_fail = len(failures)
    complete = [f for f in failures if not f["truncada"]]
    days_obs = t_known / 24.0

    motivos = []
    if days_obs < min_dias:
        motivos.append(f"Período observado com estado conhecido ({days_obs:.1f} dias) é menor que o mínimo "
                       f"configurado ({min_dias:g} dias).")
    if n_fail < min_falhas:
        motivos.append(f"Foram encontradas {n_fail} falha(s); o mínimo configurado para estimar MTBF/MTTR "
                       f"é {min_falhas}.")
    if len(complete) == 0 and n_fail > 0:
        motivos.append("Todas as falhas estão truncadas pelo início/fim do dataset; a duração real é desconhecida.")
    ok_period = days_obs >= min_dias
    ok_mtbf = ok_period and n_fail >= min_falhas and t_oper > 0
    ok_mttr = ok_period and n_fail >= min_falhas and len(complete) > 0

    mtbf = t_oper / n_fail if n_fail else None
    mttr = float(np.mean([f["duracao_h"] for f in complete])) if complete else None
    a_intr = mtbf / (mtbf + mttr) * 100 if (mtbf and mttr is not None) else None
    a_obs = (1 - (t_fail_total + t_prev) / t_known) * 100 if t_known > 0 else None

    # tempos entre falhas (operação acumulada entre o fim de uma e o início da próxima)
    tbf = []
    if n_fail >= 2:
        oper_mask = raw_states == "operando"
        cum_oper = np.cumsum(np.where(oper_mask, hours, 0.0))
        ts_arr = ts.to_numpy()
        for a, b in zip(failures[:-1], failures[1:]):
            ia = np.searchsorted(ts_arr, np.datetime64(pd.Timestamp(a["fim"])), side="left")
            ib = np.searchsorted(ts_arr, np.datetime64(pd.Timestamp(b["inicio"])), side="left")
            ia, ib = min(ia, len(cum_oper) - 1), min(max(ib - 1, 0), len(cum_oper) - 1)
            tbf.append(round(float(cum_oper[ib] - cum_oper[ia]), 2))

    weekly = []
    if n_fail:
        starts = pd.to_datetime([f["inicio"] for f in failures])
        all_weeks = pd.period_range(ts.min(), ts.max(), freq="W-SUN")
        counts = pd.Series(1, index=starts).groupby(starts.to_period("W-SUN")).sum()
        weekly = [{"semana": str(w.start_time.date()), "falhas": int(counts.get(w, 0))} for w in all_weeks]

    base.update({
        "suficiente": bool(ok_mtbf and ok_mttr),
        "motivos": motivos,
        "intervalo_amostragem_h": round(med.total_seconds() / 3600, 4),
        "tempos_h": {
            "observado": round(t_total, 2), "com_estado": round(t_known, 2),
            "operacao": round(t_oper, 2), "standby": round(t_standby, 2),
            "falha_e_reparo": round(t_fail_total, 2), "manutencao_preventiva": round(t_prev, 2),
            "sem_dados": round(t_unknown, 2),
        },
        "n_falhas": n_fail,
        "n_falhas_completas": len(complete),
        "indicadores": {
            "mtbf": _indicator(mtbf, "h", ok_mtbf, "dados insuficientes (ver motivos)"),
            "mttr": _indicator(mttr, "h", ok_mttr, "dados insuficientes (ver motivos)"),
            "disponibilidade_intrinseca": _indicator(a_intr, "%", ok_mtbf and ok_mttr,
                                                     "depende de MTBF e MTTR"),
            "disponibilidade_observada": _indicator(a_obs, "%", ok_period, "período observado curto"),
            "falhas_por_30d": _indicator(n_fail / days_obs * 30 if days_obs > 0 else None,
                                         "falhas/30 dias", ok_period, "período observado curto"),
        },
        "dispersao": {
            "tbf_h": tbf,
            "tbf_desvio_h": round(float(np.std(tbf, ddof=1)), 2) if len(tbf) >= 2 else None,
            "ttr_desvio_h": round(float(np.std([f["duracao_h"] for f in complete], ddof=1)), 2)
            if len(complete) >= 2 else None,
        },
        "falhas": failures,
        "preventivas": preventive,
        "frequencia_semanal": weekly,
    })
    return base


def compute_indicators(ds: Dataset, equipamento: str | None = None,
                       min_falhas: int = DEFAULT_MIN_FAILURES,
                       min_dias: float = DEFAULT_MIN_DAYS) -> dict:
    equipments = [equipamento] if equipamento and equipamento != "*" else ds.equipment
    results = [equipment_indicators(ds.subset(e), min_falhas, min_dias) for e in equipments]

    # consolidado da frota: soma de tempos e falhas
    fleet = None
    if len(results) > 1 and ds.has_status:
        t_oper = sum(r["tempos_h"].get("operacao", 0) for r in results)
        t_known = sum(r["tempos_h"].get("com_estado", 0) for r in results)
        n_fail = sum(r["n_falhas"] for r in results)
        durations = [f["duracao_h"] for r in results for f in r["falhas"] if not f["truncada"]]
        t_down = sum(r["tempos_h"].get("falha_e_reparo", 0) + r["tempos_h"].get("manutencao_preventiva", 0)
                     for r in results)
        ok = n_fail >= min_falhas and len(durations) > 0
        mtbf = t_oper / n_fail if n_fail else None
        mttr = float(np.mean(durations)) if durations else None
        fleet = {
            "n_falhas": n_fail,
            "indicadores": {
                "mtbf": _indicator(mtbf, "h", ok, "falhas insuficientes na frota"),
                "mttr": _indicator(mttr, "h", ok, "falhas insuficientes na frota"),
                "disponibilidade_intrinseca": _indicator(
                    mtbf / (mtbf + mttr) * 100 if (mtbf and mttr) else None, "%", ok, "depende de MTBF e MTTR"),
                "disponibilidade_observada": _indicator(
                    (1 - t_down / t_known) * 100 if t_known else None, "%", t_known > 0, "sem dados"),
            },
        }
    return {
        "parametros": {"min_falhas": min_falhas, "min_dias": min_dias},
        "possui_estado": ds.has_status,
        "equipamentos": results,
        "frota": fleet,
    }
