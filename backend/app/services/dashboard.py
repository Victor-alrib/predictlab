"""Agregações para o dashboard industrial (visão estilo SCADA)."""

from __future__ import annotations

import pandas as pd

from ..config import COL_STATUS, COL_TIMESTAMP, STATUS_CATEGORIES
from ..store import Dataset
from .alerts import compute_alerts, summarize, thresholds_for
from .maintenance import compute_indicators
from .quality import clean_float, downsample, equipment_variables, median_interval, series_to_list, ts_to_list

SPARK_HOURS = 48


def _monitor_state(last_state: str | None, active_alerts: list[dict], stale: bool) -> dict:
    """Estado de monitoramento mostrado no card do equipamento."""
    if stale:
        return {"codigo": "sem_dados", "rotulo": "Sem dados recentes"}
    if last_state == "falha":
        return {"codigo": "falha", "rotulo": "Em falha"}
    if last_state == "manutencao":
        return {"codigo": "manutencao", "rotulo": "Em manutenção"}
    if any(a["severidade"] == "alta" for a in active_alerts):
        return {"codigo": "alarme", "rotulo": "Alarme ativo"}
    if active_alerts:
        return {"codigo": "atencao", "rotulo": "Atenção"}
    if last_state == "parado":
        return {"codigo": "parado", "rotulo": "Parado / standby"}
    if last_state == "operando":
        return {"codigo": "normal", "rotulo": "Normal"}
    return {"codigo": "indefinido", "rotulo": "Estado não informado"}


def build_dashboard(ds: Dataset, referencia: str | None = None) -> dict:
    """Monta o painel. ``referencia`` permite a *reprodução histórica*: o painel é
    reconstruído como estaria naquele instante, usando apenas dados anteriores a ele."""
    full_alerts = compute_alerts(ds)
    t_min, t_max = ds.df[COL_TIMESTAMP].min(), ds.df[COL_TIMESTAMP].max()
    ref = t_max
    if referencia:
        ref = min(max(pd.Timestamp(referencia), t_min), t_max)
    if ref < t_max:
        view = Dataset(**{**ds.__dict__, "df": ds.df[ds.df[COL_TIMESTAMP] <= ref]})
        alerts = [dict(a, fim=min(a["fim"], ref.isoformat())) for a in full_alerts if pd.Timestamp(a["inicio"]) <= ref]
    else:
        view, alerts = ds, full_alerts
    ds = view
    maint = compute_indicators(ds)
    maint_by_eq = {m["equipamento"]: m for m in maint["equipamentos"]}
    t_end_global = ref

    cards = []
    for eq in ds.equipment:
        g = ds.subset(eq).sort_values(COL_TIMESTAMP)
        vars_eq = equipment_variables(ds, eq)
        med = median_interval(g[COL_TIMESTAMP]) or pd.Timedelta("15min")
        last_ts = g[COL_TIMESTAMP].max()
        # último registro com leitura válida
        valid = g.dropna(subset=vars_eq, how="all")
        last_valid = valid.iloc[-1] if len(valid) else None
        stale = last_valid is None or (t_end_global - last_valid[COL_TIMESTAMP]) > 6 * med
        last_state = None
        if COL_STATUS in g.columns and g[COL_STATUS].notna().any():
            last_state = g[COL_STATUS].dropna().iloc[-1]
        # alertas "ativos" = episódios que terminam no último registro do equipamento
        active = [a for a in alerts if a["equipamento"] == eq
                  and pd.Timestamp(a["inicio"]) <= last_ts <= pd.Timestamp(a["fim"])]
        thr = thresholds_for(ds, eq)
        last_values = []
        for v in vars_eq:
            meta = ds.variable(v) or {}
            val = last_valid[v] if last_valid is not None else None
            lim = thr.get(v) or {}
            out_of = None
            if val is not None and pd.notna(val):
                if lim.get("max") is not None and val > lim["max"]:
                    out_of = "max"
                elif lim.get("min") is not None and val < lim["min"]:
                    out_of = "min"
            last_values.append({"variavel": v, "rotulo": meta.get("label", v), "unidade": meta.get("unit", ""),
                                "valor": clean_float(val), "limite": lim or None, "fora_do_limite": out_of})
        # sparkline das últimas 48 h para até 3 variáveis
        recent = g[g[COL_TIMESTAMP] >= last_ts - pd.Timedelta(hours=SPARK_HOURS)]
        spark_vars = vars_eq[:3]
        sp = downsample(recent, spark_vars, 120) if spark_vars else recent[[COL_TIMESTAMP]]
        m = maint_by_eq.get(eq, {})
        state_dist = {}
        if COL_STATUS in g.columns:
            vc = g[COL_STATUS].fillna("desconhecido").value_counts(normalize=True)
            state_dist = {k: round(float(vc.get(k, 0)) * 100, 2) for k in STATUS_CATEGORIES}
        cards.append({
            "equipamento": eq,
            "alertas_ativos_detalhe": [{k: a[k] for k in ("origem", "severidade", "mensagem", "variavel")}
                                       for a in active][:5],
            "descricao": (ds.provenance.get("equipamentos") or {}).get(eq),
            "estado_operacional": last_state,
            "monitoramento": _monitor_state(last_state, active, stale),
            "ultimo_registro": last_ts.isoformat(),
            "ultima_leitura_valida": last_valid[COL_TIMESTAMP].isoformat() if last_valid is not None else None,
            "intervalo_amostragem_s": med.total_seconds(),
            "valores": last_values,
            "alertas_ativos": len(active),
            "alertas_total": sum(1 for a in alerts if a["equipamento"] == eq),
            "n_falhas": m.get("n_falhas", 0),
            "disponibilidade_observada": (m.get("indicadores") or {}).get("disponibilidade_observada"),
            "distribuicao_estados_pct": state_dist,
            "sparkline": {"timestamps": ts_to_list(sp[COL_TIMESTAMP]),
                          **{v: series_to_list(sp[v], 3) for v in spark_vars}},
        })

    summary = summarize(alerts)
    fleet = maint.get("frota") or {}
    single = maint["equipamentos"][0] if len(maint["equipamentos"]) == 1 else None
    avail = (fleet.get("indicadores") or {}).get("disponibilidade_observada") if fleet else \
        (single["indicadores"]["disponibilidade_observada"] if single else None)
    last7 = [a for a in alerts if pd.Timestamp(a["inicio"]) >= t_end_global - pd.Timedelta(days=7)]
    return {
        "dataset": ds.meta() | {"start": t_min.isoformat(), "end": t_max.isoformat()},
        "referencia_temporal": t_end_global.isoformat(),
        "reproducao_historica": bool(ref < t_max),
        "kpis": {
            "equipamentos": len(ds.equipment),
            "em_alarme": sum(1 for c in cards if c["monitoramento"]["codigo"] in ("alarme", "falha")),
            "alertas_ultimos_7d": len(last7),
            "alertas_total": summary["total"],
            "falhas_registradas": sum(m.get("n_falhas", 0) for m in maint["equipamentos"]),
            "disponibilidade_observada": avail,
            "mtbf_frota": (fleet.get("indicadores") or {}).get("mtbf") if fleet else None,
            "possui_estado": ds.has_status,
        },
        "equipamentos": cards,
        "alarmes_recentes": alerts[:25],
        "resumo_alertas": summary,
    }
