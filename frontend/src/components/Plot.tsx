import { useEffect, useRef, useState } from "react";
import type { Config, Data, Layout, LayoutAxis } from "plotly.js";

// Plotly é pesado (~3,5 MB); carregado sob demanda e compartilhado entre gráficos.
type PlotlyLib = {
  react: (el: HTMLElement, data: Data[], layout: Partial<Layout>, config?: Partial<Config>) => Promise<unknown>;
  purge: (el: HTMLElement) => void;
  Plots: { resize: (el: HTMLElement) => void };
};
let plotlyPromise: Promise<PlotlyLib> | null = null;
const PT_BR = {
  moduleType: "locale", name: "pt-BR",
  dictionary: { Autoscale: "Escala automática", "Box Select": "Seleção retangular", "Download plot as a png": "Baixar gráfico como PNG",
    "Pan": "Mover", "Reset axes": "Restaurar eixos", "Zoom": "Zoom", "Zoom in": "Aproximar", "Zoom out": "Afastar",
    "Toggle Spike Lines": "Linhas de referência", "Show closest data on hover": "Dado mais próximo",
    "Compare data on hover": "Comparar dados", "Reset view": "Restaurar visão" },
  format: {
    days: ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"],
    shortDays: ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"],
    months: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"],
    shortMonths: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    date: "%d/%m/%Y", decimal: ",", thousands: ".",
  },
};
const loadPlotly = () =>
  (plotlyPromise ??= import("plotly.js-dist-min").then((m) => {
    const P = (m.default ?? m) as unknown as PlotlyLib & { register: (x: unknown) => void };
    P.register(PT_BR);
    return P;
  }));

/** Paleta de traços: aço e tons sóbrios; cores fortes ficam para alarmes. */
export const TRACE = ["#2f5d87", "#b5541c", "#3d7a42", "#6a4c9c", "#4b5560", "#a27b1e"];
export const ORIGIN_COLOR = { limite: "#b86a00", estatistica: "#6e46ad", modelo: "#0d7480" } as const;

const DATE_X: Partial<LayoutAxis> = {
  type: "date", hoverformat: "%d/%m/%Y %H:%M",
  tickformatstops: [
    { dtickrange: [null, 86400000], value: "%H:%M\n%d/%m" },
    { dtickrange: [86400000, 2592000000], value: "%d/%m" },
    { dtickrange: [2592000000, null], value: "%b %Y" },
  ],
};

export const baseLayout = (extra: Partial<Layout> = {}, dateX = false): Partial<Layout> => ({
  autosize: true,
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "#eef0f1",
  font: { family: "IBM Plex Sans, sans-serif", size: 11.5, color: "#1e252c" },
  margin: { l: 52, r: 16, t: 12, b: 36 },
  legend: { orientation: "h", y: -0.18, x: 0, font: { size: 11 } },
  hovermode: "x unified",
  hoverlabel: { bgcolor: "#f0f1f2", bordercolor: "#a8aeb3", font: { family: "IBM Plex Mono, monospace", size: 11 } },
  separators: ",.",
  ...extra,
  xaxis: { gridcolor: "#d6d9dc", linecolor: "#a8aeb3", zeroline: false, ...(dateX ? DATE_X : {}), ...(extra.xaxis ?? {}) },
  yaxis: { gridcolor: "#d6d9dc", linecolor: "#a8aeb3", zeroline: false, ...(extra.yaxis ?? {}) },
});

const ISO = /^\d{4}-\d{2}-\d{2}/;
/** Detecta eixo X temporal pelo primeiro valor de x dos traços. */
function hasDateX(data: Data[]): boolean {
  for (const t of data) {
    const x = (t as { x?: unknown[] }).x;
    if (Array.isArray(x) && x.length) return typeof x[0] === "string" && ISO.test(x[0] as string);
  }
  return false;
}

interface Props {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number;
  className?: string;
  ariaLabel: string;
}

export default function Plot({ data, layout, height = 300, className = "", ariaLabel }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    const el = ref.current;
    if (!el) return;
    loadPlotly().then((P) => {
      if (!alive || !el) return;
      void P.react(el, data, baseLayout({ height, ...layout }, hasDateX(data)), {
        displaylogo: false, responsive: true, locale: "pt-BR",
        modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
      }).then(() => alive && setReady(true));
    });
    return () => { alive = false; };
  }, [data, layout, height]);

  useEffect(() => {
    const el = ref.current;
    return () => { if (el) loadPlotly().then((P) => P.purge(el)); };
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => loadPlotly().then((P) => el.isConnected && P.Plots.resize(el)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className={`relative w-full ${className}`} style={{ minHeight: height }} role="img" aria-label={ariaLabel}>
      {!ready && <div className="absolute inset-0 grid place-items-center text-ink-3 text-sm">Carregando gráfico…</div>}
      <div ref={ref} className="w-full" />
    </div>
  );
}
