import { useMemo } from "react";
import type { Data, Layout, Shape } from "plotly.js";
import type { Alert, DatasetMeta, SeriesResp } from "../api/client";
import Plot, { ORIGIN_COLOR, TRACE } from "./Plot";

/** Gráfico de séries com faixas de estado (falha/manutenção/sem dados) e marcadores de alerta por origem. */
export default function TimeSeriesChart({ ds, series, alerts = [], height = 340, varsShown }:
  { ds: DatasetMeta; series: SeriesResp; alerts?: Alert[]; height?: number; varsShown: string[] }) {
  const { data, layout } = useMemo(() => {
    const traces: Data[] = varsShown.filter((k) => series.series[k]).map((k, i) => {
      const v = ds.variables.find((x) => x.key === k);
      return {
        type: "scattergl", mode: "lines", name: v ? `${v.label}${v.unit ? ` (${v.unit})` : ""}` : k,
        x: series.timestamps, y: series.series[k], yaxis: i === 0 ? "y" : "y2",
        line: { width: 1.3, color: TRACE[i % TRACE.length] }, connectgaps: false,
      } as Data;
    });
    const shapes: Partial<Shape>[] = (series.estados ?? []).map((s) => ({
      type: "rect", xref: "x", yref: "paper", x0: s.inicio, x1: s.fim, y0: 0, y1: 1, line: { width: 0 }, layer: "below",
      fillcolor: s.estado === "falha" ? "rgba(200,16,46,.18)" : s.estado === "manutencao" ? "rgba(47,111,176,.16)" : "rgba(102,112,122,.14)",
    }));
    const t0 = series.timestamps[0], t1 = series.timestamps[series.timestamps.length - 1];
    const vis = alerts.filter((a) => a.fim >= t0 && a.inicio <= t1).slice(0, 300);
    for (const o of ["limite", "estatistica", "modelo"] as const) {
      const sel = vis.filter((a) => a.origem === o);
      if (!sel.length) continue;
      traces.push({
        type: "scatter", mode: "markers", name: { limite: "Alerta: limite", estatistica: "Alerta: estatístico", modelo: "Alerta: modelo" }[o],
        x: sel.map((a) => a.inicio), y: sel.map(() => ({ limite: 1.03, estatistica: 1.07, modelo: 1.11 })[o]), yaxis: "y3",
        marker: { color: ORIGIN_COLOR[o], size: 9, symbol: { limite: "triangle-up", estatistica: "diamond", modelo: "circle-dot" }[o] },
        text: sel.map((a) => a.mensagem), hovertemplate: "%{text}<extra></extra>",
      } as Data);
    }
    const two = varsShown.length > 1;
    const lay: Partial<Layout> = {
      shapes,
      margin: { l: 52, r: two ? 52 : 16, t: 8, b: 36 },
      yaxis2: { overlaying: "y", side: "right", showgrid: false, zeroline: false, visible: two },
      yaxis3: { overlaying: "y", range: [0, 1.15], visible: false, fixedrange: true },
      xaxis: { type: "date" },
      hovermode: "closest",
    };
    return { data: traces, layout: lay };
  }, [ds, series, alerts, varsShown]);

  return <Plot data={data} layout={layout} height={height} ariaLabel="Série temporal das variáveis selecionadas" />;
}

export function ChartLegendNote() {
  return (
    <p className="text-[11.5px] text-ink-3 mt-1 flex flex-wrap gap-x-4 gap-y-1">
      <span><span className="inline-block w-3 h-2.5 align-middle mr-1 bg-[rgba(200,16,46,.3)]" />Falha</span>
      <span><span className="inline-block w-3 h-2.5 align-middle mr-1 bg-[rgba(47,111,176,.3)]" />Manutenção</span>
      <span><span className="inline-block w-3 h-2.5 align-middle mr-1 bg-[rgba(102,112,122,.3)]" />Sem dados / estado desconhecido</span>
      <span>Marcadores no topo: ▲ limite, ◆ anomalia estatística, ◉ previsão de modelo</span>
    </p>
  );
}
