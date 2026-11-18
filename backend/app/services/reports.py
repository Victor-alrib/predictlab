"""Geração de relatório técnico em HTML (autocontido, pronto para imprimir em PDF).

O relatório é montado no servidor com Plotly (gráficos interativos) e inclui
procedência dos dados, qualidade, indicadores, alertas, resultados de modelos,
metodologia e limitações. Se o dataset for simulado, o aviso de simulação
aparece no cabeçalho, no rodapé e em marca d'água.
"""

from __future__ import annotations

import html
import platform
from datetime import datetime

import numpy as np
import pandas as pd
import plotly
import plotly.graph_objects as go
import sklearn

from ..config import APP_NAME, APP_VERSION, COL_STATUS, COL_TIMESTAMP, DATA_ORIGINS
from ..store import Dataset, store
from .alerts import ORIGINS, compute_alerts, summarize, thresholds_for
from .maintenance import compute_indicators
from .quality import downsample, equipment_variables, quality_report

COLORS = {"limite": "#f59e0b", "estatistica": "#a855f7", "modelo": "#06b6d4"}
SERIES_COLORS = ["#38bdf8", "#f97316", "#22c55e", "#e879f9", "#facc15", "#f43f5e"]
SECTIONS = ["resumo", "qualidade", "series", "manutencao", "alertas", "modelos", "metodologia"]


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def fmt(v, digits: int = 2, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if isinstance(v, (int, np.integer)):
        s = f"{v:,}".replace(",", ".")
    else:
        s = f"{v:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {unit}".strip()


def _layout(fig: go.Figure, title: str, height: int = 320) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 14}}, height=height, template="plotly_white",
        margin={"l": 50, "r": 20, "t": 45, "b": 40}, legend={"orientation": "h", "y": -0.2},
        font={"family": "Inter, Segoe UI, sans-serif", "size": 11},
    )
    return fig


class _FigWriter:
    def __init__(self, embed_js: bool):
        self.first = True
        self.embed_js = embed_js

    def __call__(self, fig: go.Figure) -> str:
        inc = ("cdn" if not self.embed_js else True) if self.first else False
        self.first = False
        return fig.to_html(full_html=False, include_plotlyjs=inc, config={"displaylogo": False, "responsive": True})


def _table(headers: list[str], rows: list[list], cls: str = "") -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def _ind_cell(ind: dict | None, digits: int = 1) -> str:
    if not ind:
        return "—"
    if ind["status"] != "ok":
        return f'<span class="muted" title="{esc(ind.get("motivo"))}">insuficiente</span>'
    return fmt(ind["valor"], digits, ind["unidade"])


def _section_series(ds: Dataset, equipments: list[str], alerts: list[dict], figw: _FigWriter) -> str:
    parts = []
    for eq in equipments:
        g = ds.subset(eq).sort_values(COL_TIMESTAMP)
        vars_eq = equipment_variables(ds, eq)
        if not vars_eq:
            continue
        d = downsample(g, vars_eq, 1500)
        fig = go.Figure()
        for i, v in enumerate(vars_eq):
            meta = ds.variable(v) or {}
            fig.add_trace(go.Scatter(x=d[COL_TIMESTAMP], y=d[v], name=f"{meta.get('label', v)} ({meta.get('unit', '')})",
                                     line={"width": 1.2, "color": SERIES_COLORS[i % len(SERIES_COLORS)]},
                                     yaxis="y" if i == 0 else f"y{i + 1}", visible=True if i < 2 else "legendonly"))
        layout_axes = {}
        for i in range(1, len(vars_eq)):
            layout_axes[f"yaxis{i + 1}"] = {"overlaying": "y", "side": "right", "showgrid": False,
                                            "showticklabels": i == 1}
        fig.update_layout(**layout_axes)
        for a in [a for a in alerts if a["equipamento"] == eq][:150]:
            fig.add_vrect(x0=a["inicio"], x1=a["fim"], fillcolor=COLORS[a["origem"]], opacity=0.12, line_width=0)
        if COL_STATUS in g.columns:
            fails = g[g[COL_STATUS] == "falha"]
            if len(fails):
                fig.add_trace(go.Scatter(x=fails[COL_TIMESTAMP], y=[0] * len(fails), mode="markers",
                                         marker={"color": "#dc2626", "size": 5, "symbol": "x"}, name="Estado = falha"))
        _layout(fig, f"{eq} — séries temporais (faixas coloridas = alertas)", 360)
        parts.append(figw(fig))
    return "".join(parts) or "<p class='muted'>Sem variáveis para exibir.</p>"


def _section_maintenance(maint: dict, figw: _FigWriter) -> str:
    if not maint["possui_estado"]:
        return ("<p class='warn'>O dataset não possui coluna de estado operacional mapeada; MTBF, MTTR e "
                "disponibilidade não podem ser calculados.</p>")
    rows = []
    for m in maint["equipamentos"]:
        ind = m["indicadores"]
        rows.append([esc(m["equipamento"]), str(m["n_falhas"]), _ind_cell(ind["mtbf"]), _ind_cell(ind["mttr"]),
                     _ind_cell(ind["disponibilidade_intrinseca"], 2), _ind_cell(ind["disponibilidade_observada"], 2),
                     _ind_cell(ind["falhas_por_30d"], 2)])
    if maint.get("frota"):
        f = maint["frota"]["indicadores"]
        rows.append(["<b>Frota</b>", str(maint["frota"]["n_falhas"]), _ind_cell(f["mtbf"]), _ind_cell(f["mttr"]),
                     _ind_cell(f["disponibilidade_intrinseca"], 2), _ind_cell(f["disponibilidade_observada"], 2), "—"])
    html_out = _table(["Equipamento", "Falhas", "MTBF", "MTTR", "Disp. intrínseca", "Disp. observada",
                       "Frequência"], rows)
    motivos = [(m["equipamento"], r) for m in maint["equipamentos"] for r in m["motivos"]]
    if motivos:
        html_out += "<ul class='muted'>" + "".join(f"<li><b>{esc(e)}:</b> {esc(r)}</li>" for e, r in motivos) + "</ul>"
    # linha do tempo de falhas
    fig = go.Figure()
    for i, m in enumerate(maint["equipamentos"]):
        for f in m["falhas"]:
            fig.add_trace(go.Scatter(x=[f["inicio"], f["fim"]], y=[m["equipamento"]] * 2, mode="lines",
                                     line={"color": "#dc2626", "width": 10}, showlegend=False,
                                     hovertext=f"Falha: {f['duracao_h']:.1f} h", hoverinfo="text"))
        for p in m["preventivas"]:
            end = pd.Timestamp(p["inicio"]) + pd.Timedelta(hours=p["duracao_h"])
            fig.add_trace(go.Scatter(x=[p["inicio"], end], y=[m["equipamento"]] * 2, mode="lines",
                                     line={"color": "#2563eb", "width": 10}, showlegend=False,
                                     hovertext=f"Preventiva: {p['duracao_h']:.1f} h", hoverinfo="text"))
    if fig.data:
        _layout(fig, "Linha do tempo de falhas (vermelho) e manutenções preventivas (azul)",
                140 + 40 * len(maint["equipamentos"]))
        html_out += figw(fig)
    hist = []
    for m in maint["equipamentos"]:
        for f in m["falhas"]:
            hist.append([esc(m["equipamento"]), esc(f["inicio"].replace("T", " ")), fmt(f["duracao_h"], 1, "h"),
                         "sim" if f["truncada"] else "não"])
    if hist:
        html_out += "<h3>Histórico de falhas</h3>" + _table(["Equipamento", "Início", "Duração (falha + reparo)",
                                                             "Truncada"], hist, "compact")
    return html_out


def _section_alerts(alerts: list[dict]) -> str:
    s = summarize(alerts)
    cards = "".join(
        f'<div class="kpi" style="border-color:{COLORS[o]}"><div class="kpi-l">{esc(lbl)}</div>'
        f'<div class="kpi-v">{s["por_origem"][o]}</div></div>' for o, lbl in ORIGINS.items())
    rows = [[f'<span class="tag" style="background:{COLORS[a["origem"]]}">{esc(ORIGINS[a["origem"]])}</span>',
             esc(a["equipamento"]), esc(a["inicio"].replace("T", " ")), fmt(a["duracao_h"], 2, "h"),
             esc(a["severidade"]), esc(a["mensagem"])] for a in alerts[:60]]
    note = ("<p class='muted'>As três origens são independentes: <b>limites</b> são regras configuradas; "
            "<b>anomalias estatísticas</b> indicam desvio do comportamento recente (não necessariamente falha); "
            "<b>previsões de modelo</b> são estimativas probabilísticas sujeitas a erro.</p>")
    more = f"<p class='muted'>Exibindo 60 de {len(alerts)} alertas.</p>" if len(alerts) > 60 else ""
    return f'<div class="kpis">{cards}</div>{note}' + _table(
        ["Origem", "Equip.", "Início", "Duração", "Sev.", "Descrição"], rows, "compact") + more


def _section_models(ds: Dataset, run_ids: list[str] | None, figw: _FigWriter) -> str:
    runs = [r for r in store.list_runs(ds.id) if not run_ids or r["id"] in run_ids]
    if not runs:
        return "<p class='muted'>Nenhum modelo foi executado para este dataset.</p>"
    out = []
    cls = [r for r in runs if r["tipo"] in ("classificacao", "anomalia")]
    if cls:
        rows = []
        for r in cls:
            t = r["metricas"].get("teste") or {}
            e = r["metricas"].get("eventos") or {}
            rows.append([esc(r["modelo_nome"]), esc(", ".join(r["equipamentos"])),
                         fmt(r["parametros"].get("horizonte_h") or r["parametros"].get("horizonte_h_referencia"), 0, "h"),
                         fmt(t.get("precisao"), 3), fmt(t.get("recall"), 3), fmt(t.get("f1"), 3),
                         fmt(t.get("pr_auc"), 3),
                         f'{e.get("falhas_antecipadas", "—")}/{e.get("falhas_no_teste", "—")}' if e else "—",
                         fmt(e.get("alarmes_falsos_por_30d"), 1) if e else "—"])
        out.append("<h3>Detecção / previsão de falha</h3>" + _table(
            ["Modelo", "Equipamentos", "Horizonte", "Precisão", "Recall", "F1", "PR-AUC",
             "Falhas antecipadas", "Alarmes falsos/30d"], rows))
        out.append("<p class='muted'>Métricas calculadas no período de teste (divisão temporal: treino no passado, "
                   "teste no futuro). Para Isolation Forest, a comparação com rótulos é apenas referência.</p>")
        fig = go.Figure()
        for r in cls:
            if r.get("curva_pr"):
                fig.add_trace(go.Scatter(x=r["curva_pr"]["recall"], y=r["curva_pr"]["precisao"], mode="lines",
                                         name=f"{r['modelo_nome']} ({', '.join(r['equipamentos'])})"))
        if fig.data:
            fig.update_xaxes(title="Recall", range=[0, 1.02])
            fig.update_yaxes(title="Precisão", range=[0, 1.02])
            out.append(figw(_layout(fig, "Curvas precisão × recall (teste)", 340)))
        for r in cls:
            if r.get("importancias"):
                imp = r["importancias"][:12][::-1]
                fig = go.Figure(go.Bar(x=[i["importancia"] for i in imp], y=[i["atributo"] for i in imp],
                                       orientation="h", marker_color="#0ea5e9"))
                out.append(figw(_layout(fig, f"Importância de atributos — {r['modelo_nome']} "
                                             f"({', '.join(r['equipamentos'])})", 360)))
                break
        for r in cls:
            for a in r.get("avisos", []):
                out.append(f"<p class='warn'>⚠ {esc(r['modelo_nome'])}: {esc(a)}</p>")
    for r in [r for r in runs if r["tipo"] == "previsao"][:4]:
        rows = []
        for res in r["resultados"]:
            if "erro" in res:
                rows.append([esc(res["nome"]), "erro", "—", "—", "—", esc(res["erro"][:80])])
                continue
            mh = res["metricas_holdout"]
            rows.append([esc(res["nome"]) + (" ★" if res["modelo"] == r["melhor_modelo"] else ""),
                         fmt(mh["mae"], 3), fmt(mh["rmse"], 3), fmt(mh["wape_pct"], 1, "%"),
                         fmt(mh["cobertura_ic95"] * 100 if mh["cobertura_ic95"] is not None else None, 0, "%"),
                         fmt(mh.get("ganho_vs_base_pct"), 1, "%")])
        out.append(f"<h3>Previsão temporal — {esc(r['equipamentos'][0])} / {esc(r['rotulo'])}</h3>")
        out.append(_table(["Modelo", "MAE", "RMSE", "WAPE", "Cobertura IC95", "Ganho vs. ingênuo"], rows))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=r["historico"]["timestamps"], y=r["historico"]["valor"], name="Histórico",
                                 line={"color": "#64748b", "width": 1}))
        best = next((x for x in r["resultados"] if x["modelo"] == r["melhor_modelo"]), None)
        if best:
            fig.add_trace(go.Scatter(x=r["holdout_timestamps"], y=best["holdout"]["previsto"],
                                     name=f"{best['nome']} (holdout)", line={"color": "#f97316", "dash": "dot"}))
            fig.add_trace(go.Scatter(x=r["futuro_timestamps"], y=best["futuro"]["superior"], line={"width": 0},
                                     showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=r["futuro_timestamps"], y=best["futuro"]["inferior"], fill="tonexty",
                                     fillcolor="rgba(14,165,233,0.18)", line={"width": 0}, name="IC 95%"))
            fig.add_trace(go.Scatter(x=r["futuro_timestamps"], y=best["futuro"]["previsto"], name="Previsão",
                                     line={"color": "#0ea5e9"}))
        out.append(figw(_layout(fig, f"Previsão de {r['rotulo']} ({r['unidade']})", 340)))
    return "".join(out)


METHODOLOGY = """
<h3>Pré-processamento</h3>
<p>Os dados são convertidos para um esquema interno (timestamp, equipamento, estado e variáveis) por meio do
mapeamento definido na importação. Nenhum valor é alterado silenciosamente: leituras não numéricas viram vazio e
são contabilizadas no relatório de qualidade. Interpolações (até 6–12 h) são aplicadas apenas dentro da
decomposição sazonal e da previsão temporal, e são declaradas nos resultados.</p>
<h3>Indicadores de manutenção</h3>
<p>Cada amostra recebe a duração até a amostra seguinte, limitada a 3× o intervalo mediano de amostragem
(intervalos maiores contam como "sem dados"). Uma falha é uma sequência contínua de estados <i>falha</i> (incluindo a
manutenção corretiva imediatamente posterior). MTBF = tempo em operação / nº de falhas; MTTR = média das durações
de falhas completas; disponibilidade intrínseca = MTBF / (MTBF + MTTR). Os indicadores só são exibidos quando há
número mínimo de falhas e de dias observados.</p>
<h3>Alertas</h3>
<p><b>Limites:</b> episódios contínuos acima/abaixo de valores configurados. <b>Anomalias estatísticas:</b> z-score
robusto (mediana e MAD de uma janela móvel passada de 7 dias; por hora do dia quando há ciclo diário), considerando
apenas períodos em operação. <b>Previsões:</b> probabilidade de falha estimada por classificador no período de teste, ou
cruzamento de limite projetado por modelo de previsão.</p>
<h3>Modelos de falha</h3>
<p>Rótulo: falha iniciando nas próximas <i>H</i> horas. Atributos calculados só com dados passados (janelas
móveis de 1 h, 6 h, 24 h e linha de base de 7 dias). Divisão temporal treino/teste (sem embaralhamento), validação
cruzada temporal no treino e comparação com linha de base aleatória estratificada. Métricas por amostra e por evento
(falhas antecipadas, antecedência e alarmes falsos por 30 dias).</p>
<h3>Previsão temporal</h3>
<p>Série reamostrada por hora; avaliação em holdout final (últimos dias) com MAE, RMSE, WAPE e cobertura do intervalo
de 95%; comparação obrigatória com o modelo ingênuo sazonal.</p>
"""


def build_report(ds: Dataset, equipamento: str | None = None, secoes: list[str] | None = None,
                 run_ids: list[str] | None = None, titulo: str | None = None, autor: str | None = None,
                 embutir_plotly: bool = False) -> str:
    secoes = secoes or SECTIONS
    equipments = [equipamento] if equipamento and equipamento != "*" else ds.equipment
    figw = _FigWriter(embutir_plotly)
    alerts = compute_alerts(ds, equipamento)
    maint = compute_indicators(ds, equipamento)
    meta = ds.meta()
    synthetic = ds.is_synthetic
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    title = titulo or f"Relatório técnico — {ds.name}"

    body = []
    n = 0

    def section(key: str, name: str, content: str):
        nonlocal n
        if key in secoes:
            n += 1
            body.append(f"<section><h2>{n}. {esc(name)}</h2>{content}</section>")

    vars_html = ", ".join(f"{esc(v['label'])} ({esc(v['unit'])})" if v.get("unit") else esc(v["label"])
                          for v in ds.variables)
    resumo = _table(["Campo", "Valor"], [
        ["Dataset", esc(ds.name)],
        ["Origem declarada dos dados", f"<b>{esc(DATA_ORIGINS.get(ds.data_origin, ds.data_origin))}</b>"],
        ["Período", f"{esc(meta['start'][:16].replace('T', ' '))} a {esc(meta['end'][:16].replace('T', ' '))}"],
        ["Equipamentos", esc(", ".join(equipments))],
        ["Variáveis", vars_html],
        ["Registros", fmt(meta["rows"])],
        ["Estado operacional", "mapeado" if ds.has_status else "não disponível"],
        ["Arquivo de origem", esc(ds.provenance.get("arquivo", "gerado pelo PredictLab" if ds.is_demo else "—"))],
    ])
    if ds.description:
        resumo += f"<p>{esc(ds.description)}</p>"
    section("resumo", "Resumo do dataset", resumo)

    q = quality_report(ds)
    qrows = []
    for e in q["equipamentos"]:
        if e["equipamento"] not in equipments:
            continue
        miss = ", ".join(f"{k}: {v:.1f}%" for k, v in e["faltantes_pct"].items() if v)
        qrows.append([esc(e["equipamento"]), fmt(e["linhas"]), esc(e["intervalo_amostragem"]),
                      str(e["lacunas_temporais"]), esc(e["maior_lacuna"]), str(e["linhas_sem_leitura"]),
                      esc(miss or "—")])
    section("qualidade", "Qualidade dos dados", _table(
        ["Equipamento", "Linhas", "Amostragem", "Lacunas", "Maior lacuna", "Linhas sem leitura", "Faltantes"], qrows))
    if "series" in secoes:
        thr_rows = []
        for eq in equipments:
            for v, lim in thresholds_for(ds, eq).items():
                thr_rows.append([esc(eq), esc(v), fmt(lim.get("min")), fmt(lim.get("max")), esc(lim.get("severidade"))])
        thr_html = ("<h3>Limites de alarme configurados</h3>" + _table(["Equip.", "Variável", "Mín.", "Máx.", "Severidade"],
                                                                       thr_rows, "compact")) if thr_rows else \
            "<p class='muted'>Nenhum limite de alarme configurado.</p>"
        section("series", "Séries temporais", _section_series(ds, equipments, alerts, figw) + thr_html)
    section("manutencao", "Indicadores de manutenção", _section_maintenance(maint, figw) if "manutencao" in secoes else "")
    section("alertas", "Alertas", _section_alerts(alerts) if "alertas" in secoes else "")
    section("modelos", "Modelos e resultados", _section_models(ds, run_ids, figw) if "modelos" in secoes else "")
    limits = ("<h3>Limitações</h3><ul>"
              "<li>Resultados de modelos dependem do número de falhas disponíveis; com poucos eventos, as métricas têm "
              "alta incerteza.</li>"
              "<li>A qualidade do rótulo de falha depende da coluna de estado informada no dataset.</li>"
              "<li>Este relatório é gerado por uma plataforma educacional/experimental e não substitui análise de "
              "engenharia de confiabilidade.</li>")
    if synthetic:
        limits += ("<li><b>Os dados deste relatório são simulados.</b> O desempenho de modelos em dados sintéticos "
                   "tende a ser otimista, pois os padrões de degradação foram injetados de forma limpa.</li>")
    limits += "</ul>"
    repro = (f"<h3>Reprodutibilidade</h3><p class='muted'>{APP_NAME} {APP_VERSION} · Python {platform.python_version()} · "
             f"pandas {pd.__version__} · scikit-learn {sklearn.__version__} · plotly {plotly.__version__}</p>")
    section("metodologia", "Metodologia, limitações e reprodutibilidade", METHODOLOGY + limits + repro)

    banner = ""
    watermark = ""
    if synthetic:
        banner = ('<div class="sim">SIMULAÇÃO — este relatório usa dados sintéticos. Nenhum valor aqui representa '
                  'medição de equipamento industrial real.</div>')
        watermark = '<div class="wm">SIMULAÇÃO</div>'

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root{{--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--acc:#0369a1}}
*{{box-sizing:border-box}} body{{font-family:Inter,'Segoe UI',Roboto,sans-serif;color:var(--ink);margin:0;background:#f8fafc}}
.page{{max-width:1080px;margin:0 auto;padding:32px 28px;background:#fff;min-height:100vh}}
header{{border-bottom:3px solid var(--acc);padding-bottom:14px;margin-bottom:18px}}
header .brand{{font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;letter-spacing:.12em;color:var(--acc);text-transform:uppercase}}
h1{{font-size:24px;margin:6px 0}} h2{{font-size:18px;border-left:4px solid var(--acc);padding-left:10px;margin-top:34px}}
h3{{font-size:14px;margin:20px 0 8px;color:#334155}} p{{line-height:1.55;font-size:13.5px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0 14px}}
th{{background:#f1f5f9;text-align:left;font-weight:600;color:#334155}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
table.compact td{{padding:4px 8px;font-size:11.5px}}
.muted{{color:var(--mut);font-size:12.5px}} .warn{{color:#b45309;font-size:12.5px}}
.sim{{background:#fef3c7;border:2px dashed #d97706;color:#92400e;padding:10px 14px;font-weight:700;margin:12px 0;border-radius:4px}}
.wm{{position:fixed;top:45%;left:50%;transform:translate(-50%,-50%) rotate(-28deg);font-size:110px;font-weight:900;color:rgba(217,119,6,.07);pointer-events:none;z-index:0}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap}} .kpi{{border-left:5px solid;padding:8px 14px;background:#f8fafc;min-width:180px}}
.kpi-l{{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}} .kpi-v{{font-size:22px;font-weight:700}}
.tag{{color:#fff;font-size:10.5px;padding:2px 6px;border-radius:3px;white-space:nowrap}}
footer{{margin-top:40px;border-top:1px solid var(--line);padding-top:10px;font-size:11px;color:var(--mut)}}
@media print{{body{{background:#fff}} .page{{padding:0}} section{{break-inside:avoid-page}} .wm{{position:fixed}}}}
</style></head>
<body>{watermark}<div class="page">
<header><div class="brand">{APP_NAME} · relatório técnico</div><h1>{esc(title)}</h1>
<div class="muted">Gerado em {now}{(' · ' + esc(autor)) if autor else ''} · Origem dos dados: <b>{esc(DATA_ORIGINS.get(ds.data_origin, ds.data_origin))}</b></div>
{banner}</header>
{''.join(body)}
<footer>{APP_NAME} {APP_VERSION} — plataforma educacional e experimental de monitoramento e manutenção preditiva.
{'<b>Dados simulados.</b>' if synthetic else ''}</footer>
</div></body></html>"""
