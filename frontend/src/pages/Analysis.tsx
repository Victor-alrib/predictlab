import { useEffect, useMemo, useState } from "react";
import type { Data } from "plotly.js";
import { api } from "../api/client";
import { EquipVarPicker } from "../components/Pickers";
import Plot, { TRACE } from "../components/Plot";
import { Button, Empty, ErrorBox, Field, Loading, Notice, PageHeader, Panel, Stat, Tabs } from "../components/ui";
import { useDataset } from "../lib/dataset";
import { localIso, num } from "../lib/format";
import { useAction, useAsync } from "../lib/hooks";

type Tab = "tendencia" | "sazonalidade" | "historico" | "comparacao";

const P_TXT = (p: number | null | undefined) => (p === null || p === undefined ? "—" : p < 0.001 ? "< 0,001" : num(p, 3));

function TrendTab({ id, eq, v }: { id: string; eq: string; v: string }) {
  const [janelas, setJanelas] = useState("6h,24h,7D");
  const [oper, setOper] = useState(false);
  const r = useAsync(() => api.trend(id, { equipamento: eq, variavel: v, janelas, apenas_operando: oper }), [id, eq, v, janelas, oper]);
  const t = r.data;
  const data = useMemo<Data[]>(() => {
    if (!t) return [];
    const out: Data[] = [{ type: "scattergl", mode: "lines", name: "Leitura", x: t.timestamps, y: t.valor, line: { color: "#9aa3ab", width: 1 } }];
    Object.entries(t.medias_moveis).forEach(([w, ys], i) =>
      out.push({ type: "scattergl", mode: "lines", name: `Média móvel ${w}`, x: t.timestamps, y: ys, line: { color: TRACE[i % TRACE.length], width: 1.8 } }));
    if (t.linha_tendencia) out.push({ type: "scatter", mode: "lines", name: "Tendência linear", x: t.timestamps, y: t.linha_tendencia, line: { color: "#1e252c", width: 1.5, dash: "dash" } });
    return out;
  }, [t]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-start">
        <Field label="Janelas das médias móveis" hint="Separadas por vírgula. Ex.: 1h, 6h, 24h, 7D">
          <input className="field num w-56" defaultValue={janelas} onBlur={(e) => setJanelas(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-[13px] mt-[29px]">
          <input type="checkbox" checked={oper} onChange={(e) => setOper(e.target.checked)} />
          Considerar só períodos em operação
        </label>
      </div>
      <ErrorBox>{r.error}</ErrorBox>
      {r.loading && !t && <Loading />}
      {t && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat label="Direção (Mann-Kendall)" note={`τ = ${num(t.estatisticas.kendall_tau, 3)}; p ${P_TXT(t.estatisticas.kendall_p)}`}>
              <span className="text-[18px] font-semibold capitalize">{t.estatisticas.direcao}</span>
            </Stat>
            <Stat label="Inclinação linear" note={`R² = ${num(t.estatisticas.r2, 3)}`}>
              <span className="num text-[18px] font-semibold">{num(t.estatisticas.inclinacao_por_dia, 4)}</span>
              <span className="text-ink-3 text-[12px] ml-1">{t.unidade}/dia</span>
            </Stat>
            <Stat label="Média ± desvio">
              <span className="num text-[18px] font-semibold">{num(t.estatisticas.media, 2)} ± {num(t.estatisticas.desvio, 2)}</span>
              <span className="text-ink-3 text-[12px] ml-1">{t.unidade}</span>
            </Stat>
            <Stat label="Faixa observada" note={`${num(t.estatisticas.n, 0)} pontos (reamostragem ${t.frequencia})`}>
              <span className="num text-[18px] font-semibold">{num(t.estatisticas.minimo, 1)} a {num(t.estatisticas.maximo, 1)}</span>
            </Stat>
          </div>
          <Plot data={data} height={380} ariaLabel={`Tendência de ${t.rotulo}`} layout={{ yaxis: { title: { text: `${t.rotulo} (${t.unidade})` } } }} />
          <p className="text-[12px] text-ink-3 max-w-[90ch]">
            A direção usa o teste de Mann-Kendall (τ de Kendall contra o tempo), robusto a não linearidades; só é declarada
            "crescente" ou "decrescente" com p &lt; 0,01 e |τ| &gt; 0,1. Em séries com ciclo diário forte, filtre por operação
            ou use janelas de 24 h ou mais para separar tendência de sazonalidade.
          </p>
        </>
      )}
    </div>
  );
}

function SeasonTab({ id, eq, v }: { id: string; eq: string; v: string }) {
  const r = useAsync(() => api.seasonality(id, { equipamento: eq, variavel: v }), [id, eq, v]);
  const s = r.data;
  if (r.error) return <ErrorBox>{r.error}</ErrorBox>;
  if (!s) return <Loading label="Calculando autocorrelação e decomposição STL…" />;
  const dec = s.decomposicao;
  const comp = (k: "observado" | "tendencia" | "sazonal" | "residuo", i: number): Data => ({
    type: "scattergl", mode: "lines", x: dec!.timestamps, y: dec![k], name: k, xaxis: "x", yaxis: i === 0 ? "y" : `y${i + 1}`,
    line: { width: 1.1, color: ["#46505a", "#2f5d87", "#b5541c", "#7c858d"][i] }, showlegend: false,
  });
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Stat label="Período detectado"><span className="text-[18px] font-semibold">{s.periodo_detectado?.periodo ?? "nenhum"}</span></Stat>
        <Stat label="Força da sazonalidade" note="0 = ausente, 1 = domina a série"><span className="num text-[18px] font-semibold">{num(s.forca_sazonal, 2)}</span></Stat>
        <Stat label="Força da tendência"><span className="num text-[18px] font-semibold">{num(s.forca_tendencia, 2)}</span></Stat>
        <Stat label="Candidatos (autocorrelação)">
          <div className="text-[12px] num">{s.candidatos.map((c) => <div key={c.horas}>{c.periodo}: {num(c.acf, 2)}</div>)}</div>
        </Stat>
      </div>
      <Plot
        height={240} ariaLabel="Função de autocorrelação"
        data={[{ type: "bar", x: s.acf.lags_h, y: s.acf.valores, marker: { color: "#2f5d87" }, name: "ACF" },
          { type: "scatter", mode: "lines", x: [0, s.acf.lags_h.length], y: [s.acf.limiar_significancia, s.acf.limiar_significancia], line: { color: "#c8102e", dash: "dot", width: 1 }, name: "Limiar ±1,96/√n" },
          { type: "scatter", mode: "lines", x: [0, s.acf.lags_h.length], y: [-s.acf.limiar_significancia, -s.acf.limiar_significancia], line: { color: "#c8102e", dash: "dot", width: 1 }, showlegend: false }]}
        layout={{ xaxis: { title: { text: "Defasagem (h)" } }, yaxis: { title: { text: "Autocorrelação" } }, hovermode: "closest" }}
      />
      {dec ? (
        <Plot
          height={560} ariaLabel="Decomposição STL"
          data={[comp("observado", 0), comp("tendencia", 1), comp("sazonal", 2), comp("residuo", 3)]}
          layout={{
            grid: { rows: 4, columns: 1, pattern: "coupled" }, margin: { l: 80, r: 16, t: 8, b: 36 },
            yaxis: { title: { text: "Observado" } }, yaxis2: { title: { text: "Tendência" } },
            yaxis3: { title: { text: "Sazonal" } }, yaxis4: { title: { text: "Resíduo" } },
          }}
        />
      ) : <Notice>Nenhum período candidato teve autocorrelação acima de 0,3; a decomposição sazonal não foi aplicada.</Notice>}
      <p className="text-[12px] text-ink-3">{s.interpolacao}</p>
    </div>
  );
}

function HistoryTab({ id, eq, v }: { id: string; eq: string; v: string }) {
  const { current: ds } = useDataset();
  const r = useAsync(() => api.profile(id, { equipamento: eq, variavel: v }), [id, eq, v]);
  const p = r.data;
  if (r.error) return <ErrorBox>{r.error}</ErrorBox>;
  if (!p) return <Loading />;
  const unit = ds?.variables.find((x) => x.key === v)?.unit ?? "";
  const ph = p.perfil_horario;
  const centers = p.histograma.bordas.slice(0, -1).map((b, i) => (b + p.histograma.bordas[i + 1]) / 2);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Perfil por hora do dia" bodyClass="p-2">
        <Plot height={280} ariaLabel="Perfil horário" data={[
          { type: "scatter", mode: "lines", x: ph.hora, y: ph.p90, line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
          { type: "scatter", mode: "lines", x: ph.hora, y: ph.p10, fill: "tonexty", fillcolor: "rgba(47,93,135,.18)", line: { width: 0 }, name: "Faixa p10–p90" },
          { type: "scatter", mode: "lines+markers", x: ph.hora, y: ph.media, line: { color: "#2f5d87" }, name: "Média" },
        ]} layout={{ xaxis: { title: { text: "Hora" }, dtick: 3 }, yaxis: { title: { text: unit } } }} />
      </Panel>
      <Panel title="Média por dia da semana" bodyClass="p-2">
        <Plot height={280} ariaLabel="Perfil semanal" data={[{ type: "bar", x: p.perfil_semanal.dia, y: p.perfil_semanal.media, marker: { color: "#46505a" } }]}
          layout={{ yaxis: { title: { text: unit } }, hovermode: "closest" }} />
      </Panel>
      <Panel title="Mínimo, média e máximo diários" bodyClass="p-2" className="lg:col-span-2">
        <Plot height={280} ariaLabel="Envelope diário" data={[
          { type: "scatter", mode: "lines", x: p.diario.data, y: p.diario.max, line: { width: 0.8, color: "#9aa3ab" }, name: "Máximo" },
          { type: "scatter", mode: "lines", x: p.diario.data, y: p.diario.min, fill: "tonexty", fillcolor: "rgba(154,163,171,.25)", line: { width: 0.8, color: "#9aa3ab" }, name: "Mínimo" },
          { type: "scatter", mode: "lines", x: p.diario.data, y: p.diario.mean, line: { color: "#2f5d87", width: 1.8 }, name: "Média" },
        ]} layout={{ yaxis: { title: { text: unit } } }} />
      </Panel>
      <Panel title="Distribuição das leituras" bodyClass="p-2">
        <Plot height={260} ariaLabel="Histograma" data={[{ type: "bar", x: centers, y: p.histograma.contagem, marker: { color: "#2f5d87" } }]}
          layout={{ bargap: 0.05, xaxis: { title: { text: unit } }, yaxis: { title: { text: "Contagem" } }, hovermode: "closest" }} />
      </Panel>
      <Panel title="Média por estado operacional">
        {p.por_estado ? (
          <table className="tbl text-[13px]"><thead><tr><th>Estado</th><th>Média</th><th>Leituras</th></tr></thead>
            <tbody>{Object.entries(p.por_estado).map(([k, x]) => <tr key={k}><td>{k}</td><td className="num">{num(x.media, 2)} {unit}</td><td className="num">{num(x.n, 0)}</td></tr>)}</tbody>
          </table>
        ) : <Empty title="Dataset sem coluna de estado" />}
        <div className="mt-3 text-[12px] text-ink-2 num">
          Quantis: {Object.entries(p.quantis).map(([q, x]) => `p${Number(q) * 100}: ${num(x, 2)}`).join("  ·  ")}
        </div>
      </Panel>
    </div>
  );
}

function CompareTab({ id, eq, v, start, end }: { id: string; eq: string; v: string; start: string; end: string }) {
  const d0 = new Date(start).getTime(), d1 = new Date(end).getTime();
  const iso = (ms: number) => localIso(ms).slice(0, 10);
  const [a, setA] = useState<[string, string]>([iso(d0), iso(d0 + (d1 - d0) * 0.3)]);
  const [b, setB] = useState<[string, string]>([iso(d0 + (d1 - d0) * 0.7), iso(d1)]);
  const [oper, setOper] = useState(true);
  const act = useAction(api.compare);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.compare>> | null>(null);
  const runCmp = async () => setRes((await act.run(id, { equipamento: eq, variavel: v, periodo_a: a, periodo_b: b, apenas_operando: oper })) ?? null);
  useEffect(() => { void runCmp(); }, [eq, v]); // eslint-disable-line react-hooks/exhaustive-deps

  const dates = (p: [string, string], set: (x: [string, string]) => void, label: string) => (
    <fieldset className="flex flex-wrap items-end gap-2">
      <legend className="text-[12.5px] font-medium text-ink-2 mb-1">{label}</legend>
      <input type="date" className="field num" value={p[0]} min={iso(d0)} max={iso(d1)} onChange={(e) => set([e.target.value, p[1]])} aria-label={`${label}: início`} />
      <span className="pb-1.5">a</span>
      <input type="date" className="field num" value={p[1]} min={iso(d0)} max={iso(d1)} onChange={(e) => set([p[0], e.target.value])} aria-label={`${label}: fim`} />
    </fieldset>
  );
  const centers = res ? res.histograma.bordas.slice(0, -1).map((x, i) => (x + res.histograma.bordas[i + 1]) / 2) : [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-6 gap-y-3 items-end">
        {dates(a, setA, "Período A (referência)")}
        {dates(b, setB, "Período B (comparado)")}
        <label className="flex items-center gap-2 text-[13px] pb-2"><input type="checkbox" checked={oper} onChange={(e) => setOper(e.target.checked)} />Só em operação</label>
        <Button variant="primary" onClick={runCmp} disabled={act.running}>{act.running ? "Comparando…" : "Comparar períodos"}</Button>
      </div>
      <ErrorBox>{act.error}</ErrorBox>
      {res && (
        <>
          <Notice tone={res.significativo_5pct ? "warn" : "info"}>{res.interpretacao}</Notice>
          <div className="overflow-x-auto">
            <table className="tbl text-[13px]">
              <thead><tr><th /><th>Leituras</th><th>Média</th><th>Mediana</th><th>Desvio</th><th>p95</th><th>Mín.</th><th>Máx.</th></tr></thead>
              <tbody>{[["A", res.periodo_a], ["B", res.periodo_b]].map(([k, s]) => {
                const x = s as typeof res.periodo_a;
                return <tr key={k as string}><td className="font-semibold">Período {k as string}</td>{[x.n, x.media, x.mediana, x.desvio, x.p95, x.minimo, x.maximo].map((n, i) => <td key={i} className="num">{num(n, i === 0 ? 0 : 2)}</td>)}</tr>;
              })}</tbody>
            </table>
          </div>
          <p className="text-[12.5px] text-ink-2 num">
            Diferença das médias (B − A): {num(res.diferenca_media, 3)} ({num(res.diferenca_pct, 1)}%) · d de Cohen: {num(res.cohen_d, 2)} · Mann-Whitney p {P_TXT(res.mann_whitney_p)}
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <Plot height={260} ariaLabel="Perfil horário dos períodos" data={[
              { type: "scatter", mode: "lines", name: "Período A", x: res.perfil_horario.hora, y: res.perfil_horario.a, line: { color: "#2f5d87" } },
              { type: "scatter", mode: "lines", name: "Período B", x: res.perfil_horario.hora, y: res.perfil_horario.b, line: { color: "#b5541c" } },
            ]} layout={{ xaxis: { title: { text: "Hora do dia" } } }} />
            <Plot height={260} ariaLabel="Distribuições dos períodos" data={[
              { type: "bar", name: "Período A", x: centers, y: res.histograma.a, marker: { color: "rgba(47,93,135,.6)" } },
              { type: "bar", name: "Período B", x: centers, y: res.histograma.b, marker: { color: "rgba(181,84,28,.6)" } },
            ]} layout={{ barmode: "overlay", bargap: 0.05, hovermode: "closest" }} />
          </div>
        </>
      )}
    </div>
  );
}

export default function Analysis() {
  const { current: ds } = useDataset();
  const [tab, setTab] = useState<Tab>("tendencia");
  const [eq, setEq] = useState("");
  const [v, setV] = useState("");
  useEffect(() => {
    if (!ds) return;
    setEq(ds.equipment[0]);
    setV(ds.variables[0]?.key ?? "");
  }, [ds?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ds || !eq) return <Loading />;
  return (
    <div className="space-y-4">
      <PageHeader title="Análise temporal">
        Tendências, médias móveis, sazonalidade, comportamento histórico e comparação entre períodos para uma variável de um equipamento.
      </PageHeader>
      <Panel bodyClass="p-4 flex flex-wrap gap-3">
        <EquipVarPicker ds={ds} equipamento={eq} variavel={v} onEquipamento={setEq} onVariavel={setV} />
      </Panel>
      <Panel bodyClass="p-4">
        <Tabs value={tab} onChange={setTab} items={[
          { value: "tendencia", label: "Tendência e médias móveis" }, { value: "sazonalidade", label: "Sazonalidade" },
          { value: "historico", label: "Comportamento histórico" }, { value: "comparacao", label: "Comparação entre períodos" },
        ]} />
        {v && tab === "tendencia" && <TrendTab id={ds.id} eq={eq} v={v} />}
        {v && tab === "sazonalidade" && <SeasonTab id={ds.id} eq={eq} v={v} />}
        {v && tab === "historico" && <HistoryTab id={ds.id} eq={eq} v={v} />}
        {v && tab === "comparacao" && <CompareTab id={ds.id} eq={eq} v={v} start={ds.start} end={ds.end} />}
      </Panel>
    </div>
  );
}
