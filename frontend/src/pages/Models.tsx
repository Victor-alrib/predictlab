import { useEffect, useMemo, useState } from "react";
import type { Data } from "plotly.js";
import { api, type Run } from "../api/client";
import { EquipVarPicker } from "../components/Pickers";
import Plot, { TRACE } from "../components/Plot";
import { Button, Empty, ErrorBox, Field, Loading, Notice, PageHeader, Panel, Select, Tabs } from "../components/ui";
import { useDataset } from "../lib/dataset";
import { dt, num, pct } from "../lib/format";
import { useAction, useAsync } from "../lib/hooks";

type Tab = "falha" | "anomalia" | "previsao" | "comparacao";

const STAGES = [
  { n: 1, nome: "Random Forest", desc: "Classificação de falha iminente; ponto de partida robusto." },
  { n: 2, nome: "XGBoost", desc: "Gradient boosting; normalmente o mais forte em dados tabulares." },
  { n: 3, nome: "Isolation Forest", desc: "Não supervisionado; funciona mesmo sem rótulos de falha." },
  { n: 4, nome: "Previsão temporal", desc: "Holt-Winters e ARIMA comparados a um modelo ingênuo." },
];

function Metric({ label, v, digits = 3, hint }: { label: string; v: number | null | undefined; digits?: number; hint?: string }) {
  return (
    <div className="bg-raised border border-line-soft rounded-[3px] px-3 py-2" title={hint}>
      <div className="text-[12px] text-ink-2">{label}</div>
      <div className="num text-[19px] font-semibold">{num(v, digits)}</div>
    </div>
  );
}

function Warnings({ run }: { run: Run }) {
  return (
    <>
      {run.dataset_sintetico && (
        <Notice tone="warn">
          Resultado obtido sobre <b>dados simulados</b>. Os padrões de degradação foram injetados de forma limpa, então o desempenho
          tende a ser otimista em relação a dados reais.
        </Notice>
      )}
      {run.avisos.map((a, i) => <Notice key={i} tone="warn">{a}</Notice>)}
    </>
  );
}

function ClassifierResult({ run }: { run: Run }) {
  const m = run.metricas!;
  const t = m.teste;
  const ev = m.eventos;
  const eqs = Object.keys(run.series ?? {});
  const [eq, setEq] = useState(eqs[0]);
  useEffect(() => setEq(eqs[0]), [run.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = run.series?.[eq];
  const thr = (run.tipo === "classificacao" ? (run.parametros.limiar as number) : run.limiar_exibicao) ?? null;
  const cm = t?.matriz_confusao;
  return (
    <div className="space-y-4">
      <Warnings run={run} />
      <div className="text-[12.5px] text-ink-2">
        Treino até <span className="num">{dt(String(run.divisao?.corte))}</span>, teste depois disso
        {run.divisao?.falhas_treino !== undefined && <> · {String(run.divisao.falhas_treino)} falha(s) no treino, {String(run.divisao.falhas_teste)} no teste</>}
        {" "}· {run.atributos?.n} atributos · {num(run.duracao_s, 1)} s
      </div>

      {ev && (
        <div>
          <h3 className="text-[13px] font-semibold mb-2">Avaliação por evento (o que a operação perceberia)</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="bg-raised border border-line-soft rounded-[3px] px-3 py-2">
              <div className="text-[12px] text-ink-2">Falhas antecipadas</div>
              <div className="num text-[19px] font-semibold">{ev.falhas_antecipadas} de {ev.falhas_no_teste}</div>
            </div>
            <Metric label="Antecedência média (h)" v={ev.antecedencia_media_h} digits={1} />
            <Metric label="Alarmes falsos" v={ev.alarmes_falsos} digits={0} hint="Episódios de alerta sem falha nas próximas H horas" />
            <Metric label="Alarmes falsos por 30 dias" v={ev.alarmes_falsos_por_30d} digits={1} />
          </div>
        </div>
      )}

      {t && (
        <div>
          <h3 className="text-[13px] font-semibold mb-2">{run.tipo === "anomalia" ? "Comparação com rótulos (só referência)" : "Métricas por amostra no teste"}</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <Metric label="Precisão" v={t.precisao} /><Metric label="Recall" v={t.recall} /><Metric label="F1" v={t.f1} />
            <Metric label="PR-AUC" v={t.pr_auc} hint="Mais informativa que ROC-AUC com classes desbalanceadas" />
            <Metric label="ROC-AUC" v={t.roc_auc} />
          </div>
          <p className="text-[12px] text-ink-3 mt-1">
            Prevalência de positivos no teste: {pct(t.prevalencia)} — é a PR-AUC de um classificador aleatório.
            {m.treino?.f1 !== undefined && m.treino?.f1 !== null && <> F1 no treino: {num(m.treino.f1, 3)}.</>}
            {m.cv?.f1_media !== null && m.cv?.f1_media !== undefined && <> Validação cruzada temporal (treino): F1 {num(m.cv.f1_media, 3)} ± {num(m.cv.f1_desvio, 3)}.</>}
          </p>
        </div>
      )}

      {s && (
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
            <h3 className="text-[13px] font-semibold">{run.tipo === "anomalia" ? "Escore de anomalia no período de teste" : "Probabilidade de falha no período de teste"}</h3>
            {eqs.length > 1 && <Select value={eq} onChange={(e) => setEq(e.target.value)} options={eqs.map((e) => ({ value: e, label: e }))} />}
          </div>
          <Plot height={300} ariaLabel="Escore do modelo ao longo do tempo" data={[
            { type: "scatter", mode: "lines", x: s.timestamps, y: s.rotulo, name: `Janela de ${run.parametros.horizonte_h ?? run.parametros.horizonte_h_referencia} h antes de falha`, fill: "tozeroy", fillcolor: "rgba(200,16,46,.13)", line: { width: 0, shape: "hv" } },
            { type: "scatter", mode: "lines", x: s.timestamps, y: s.score, name: run.tipo === "anomalia" ? "Escore (normalizado)" : "Probabilidade", line: { color: "#0d7480", width: 1.4 } },
            ...(thr !== null ? [{ type: "scatter", mode: "lines", x: [s.timestamps[0], s.timestamps[s.timestamps.length - 1]], y: [thr, thr], name: "Limiar", line: { color: "#1e252c", dash: "dash", width: 1 } } as Data] : []),
          ]} layout={{ yaxis: { range: [0, 1.05], tickformat: ".0%" } }} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {cm && (
          <div>
            <h3 className="text-[13px] font-semibold mb-2">Matriz de confusão (teste)</h3>
            <table className="text-[13px] num border border-line w-full text-center">
              <thead><tr className="bg-well"><th className="p-1.5" /><th className="p-1.5 font-medium">Previsto normal</th><th className="p-1.5 font-medium">Previsto falha</th></tr></thead>
              <tbody>
                <tr><th className="bg-well p-1.5 font-medium">Real normal</th><td className="p-2">{cm.vn}</td><td className="p-2 bg-warn-soft">{cm.fp}</td></tr>
                <tr><th className="bg-well p-1.5 font-medium">Real falha</th><td className="p-2 bg-alarm-soft">{cm.fn}</td><td className="p-2">{cm.vp}</td></tr>
              </tbody>
            </table>
          </div>
        )}
        {run.curva_pr && (
          <div>
            <h3 className="text-[13px] font-semibold mb-1">Curva precisão × recall</h3>
            <Plot height={230} ariaLabel="Curva precisão-recall" data={[{ type: "scatter", mode: "lines", x: run.curva_pr.recall, y: run.curva_pr.precisao, line: { color: "#2f5d87" }, text: run.curva_pr.limiar.map((l) => `limiar ${num(l, 2)}`), hovertemplate: "R %{x:.2f} · P %{y:.2f} · %{text}<extra></extra>" }]}
              layout={{ xaxis: { title: { text: "Recall" }, range: [0, 1.02] }, yaxis: { title: { text: "Precisão" }, range: [0, 1.02] }, hovermode: "closest", margin: { l: 48, r: 8, t: 8, b: 40 } }} />
          </div>
        )}
        {run.importancias && run.importancias.length > 0 && (
          <div>
            <h3 className="text-[13px] font-semibold mb-1">Atributos mais importantes</h3>
            <Plot height={230} ariaLabel="Importância dos atributos" data={[{ type: "bar", orientation: "h", x: run.importancias.slice(0, 10).reverse().map((i) => i.importancia), y: run.importancias.slice(0, 10).reverse().map((i) => i.atributo), marker: { color: "#46505a" } }]}
              layout={{ margin: { l: 170, r: 8, t: 8, b: 30 }, hovermode: "closest", yaxis: { tickfont: { size: 10 } } }} />
          </div>
        )}
      </div>

      {ev && ev.detalhes.length > 0 && (
        <details className="text-[12.5px]">
          <summary className="cursor-pointer font-medium">Detalhe das falhas do período de teste</summary>
          <table className="tbl mt-2"><thead><tr><th>Equipamento</th><th>Início da falha</th><th>Antecipada</th><th>Antecedência</th></tr></thead>
            <tbody>{ev.detalhes.map((x) => <tr key={x.evento}><td>{x.equipamento}</td><td className="num">{dt(x.inicio_falha)}</td><td>{x.antecipada ? "sim" : "não"}</td><td className="num">{x.antecedencia_h !== null ? `${num(x.antecedencia_h, 1)} h` : "—"}</td></tr>)}</tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function ForecastResult({ run }: { run: Run }) {
  const ok = (run.resultados ?? []).filter((r) => !r.erro);
  const [shown, setShown] = useState(run.melhor_modelo ?? ok[0]?.modelo);
  useEffect(() => setShown(run.melhor_modelo ?? ok[0]?.modelo), [run.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const best = ok.find((r) => r.modelo === shown);
  const data: Data[] = useMemo(() => {
    const d: Data[] = [{ type: "scatter", mode: "lines", name: "Real", x: run.historico!.timestamps, y: run.historico!.valor, line: { color: "#7c858d", width: 1.2 } }];
    if (best?.holdout && best.futuro) {
      d.push({ type: "scatter", mode: "lines", name: `${best.nome} — holdout`, x: run.holdout_timestamps, y: best.holdout.previsto, line: { color: "#b5541c", dash: "dot", width: 1.6 } });
      d.push({ type: "scatter", mode: "lines", x: run.futuro_timestamps, y: best.futuro.superior, line: { width: 0 }, showlegend: false, hoverinfo: "skip" });
      d.push({ type: "scatter", mode: "lines", name: "Intervalo 95%", x: run.futuro_timestamps, y: best.futuro.inferior, fill: "tonexty", fillcolor: "rgba(13,116,128,.16)", line: { width: 0 } });
      d.push({ type: "scatter", mode: "lines", name: "Previsão futura", x: run.futuro_timestamps, y: best.futuro.previsto, line: { color: "#0d7480", width: 2 } });
    }
    return d;
  }, [run, best]);
  return (
    <div className="space-y-4">
      <Warnings run={run} />
      <div className="overflow-x-auto">
        <table className="tbl text-[13px]">
          <thead><tr><th>Modelo</th><th>MAE</th><th>RMSE</th><th>WAPE</th><th>Viés</th><th>Cobertura IC 95%</th><th>Ganho de MAE vs. ingênuo</th><th /></tr></thead>
          <tbody>{(run.resultados ?? []).map((r) => r.erro ? (
            <tr key={r.modelo}><td>{r.nome}</td><td colSpan={7} className="text-alarm">Falhou: {r.erro}</td></tr>
          ) : (
            <tr key={r.modelo} className={r.modelo === shown ? "bg-raised" : ""}>
              <td className="font-medium">{r.nome}{r.modelo === run.melhor_modelo && <span className="ml-1.5 text-[11px] bg-frame text-frame-ink px-1 rounded-[2px]">menor MAE</span>}</td>
              <td className="num">{num(r.metricas_holdout!.mae, 3)}</td><td className="num">{num(r.metricas_holdout!.rmse, 3)}</td>
              <td className="num">{num(r.metricas_holdout!.wape_pct, 1)}%</td><td className="num">{num(r.metricas_holdout!.vies, 3)}</td>
              <td className="num">{pct(r.metricas_holdout!.cobertura_ic95, 0)}</td>
              <td className={`num ${(r.metricas_holdout!.ganho_vs_base_pct ?? 0) < 0 ? "text-alarm" : ""}`}>{r.metricas_holdout!.ganho_vs_base_pct === undefined ? "referência" : `${num(r.metricas_holdout!.ganho_vs_base_pct, 1)}%`}</td>
              <td><Button variant="ghost" onClick={() => setShown(r.modelo)} disabled={r.modelo === shown}>Ver no gráfico</Button></td>
            </tr>))}
          </tbody>
        </table>
      </div>
      <Plot height={340} data={data} ariaLabel="Histórico, holdout e previsão" layout={{ yaxis: { title: { text: `${run.rotulo} (${run.unidade})` } } }} />
      <p className="text-[12px] text-ink-3 max-w-[90ch]">
        Holdout: os últimos {String(run.parametros.holdout_h)} h ficaram fora do ajuste e servem para medir o erro. A previsão futura reajusta o modelo com
        toda a série e projeta {String(run.parametros.horizonte_h)} h. Cobertura do IC próxima de 95% indica incerteza bem calibrada.
      </p>
    </div>
  );
}

export function RunResult({ run }: { run: Run }) {
  return run.tipo === "previsao" ? <ForecastResult run={run} /> : <ClassifierResult run={run} />;
}

function ComparisonTab({ runs, onOpen, onDelete }: { runs: Run[]; onOpen: (id: string) => void; onDelete: (id: string) => void }) {
  const cls = runs.filter((r) => r.tipo !== "previsao");
  const fc = runs.filter((r) => r.tipo === "previsao");
  if (!runs.length) return <Empty title="Nenhum modelo treinado neste dataset">Treine modelos nas outras abas; cada execução aparece aqui para comparação.</Empty>;
  const metricKeys = [["precisao", "Precisão"], ["recall", "Recall"], ["f1", "F1"], ["pr_auc", "PR-AUC"]] as const;
  return (
    <div className="space-y-5">
      {cls.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="tbl text-[12.5px]">
              <thead><tr><th>Modelo</th><th>Equipamentos</th><th>Horizonte</th><th>Precisão</th><th>Recall</th><th>F1</th><th>PR-AUC</th><th>Falhas antecipadas</th><th>Alarmes falsos/30d</th><th>Quando</th><th /></tr></thead>
              <tbody>{cls.map((r) => {
                const t = r.metricas?.teste; const e = r.metricas?.eventos;
                return (
                  <tr key={r.id}>
                    <td className="font-medium">{r.modelo_nome}</td><td>{r.equipamentos.join(", ")}</td>
                    <td className="num">{String(r.parametros.horizonte_h ?? r.parametros.horizonte_h_referencia)} h</td>
                    {metricKeys.map(([k]) => <td key={k} className="num">{num(t?.[k], 3)}</td>)}
                    <td className="num">{e ? `${e.falhas_antecipadas}/${e.falhas_no_teste}` : "—"}</td>
                    <td className="num">{num(e?.alarmes_falsos_por_30d, 1)}</td>
                    <td className="num whitespace-nowrap">{dt(r.created_at)}</td>
                    <td className="whitespace-nowrap"><Button variant="ghost" onClick={() => onOpen(r.id)}>Abrir</Button><Button variant="ghost" onClick={() => onDelete(r.id)}>Excluir</Button></td>
                  </tr>);
              })}</tbody>
            </table>
          </div>
          <Plot height={300} ariaLabel="Comparação de métricas" data={cls.slice(0, 6).map((r, i) => ({
            type: "bar", name: `${r.modelo_nome} (${r.equipamentos.length > 2 ? `${r.equipamentos.length} equip.` : r.equipamentos.join(", ")})`,
            x: metricKeys.map(([, l]) => l), y: metricKeys.map(([k]) => r.metricas?.teste?.[k] ?? null), marker: { color: TRACE[i % TRACE.length] },
          } as Data))} layout={{ barmode: "group", yaxis: { range: [0, 1] }, hovermode: "closest" }} />
          <p className="text-[12px] text-ink-3 max-w-[90ch]">
            Compare apenas execuções com os mesmos equipamentos, horizonte e fração de teste. A linha de base aleatória mostra o piso: um modelo
            que não a supera com folga não aprendeu nada útil. Para Isolation Forest, as métricas contra rótulos são só referência.
          </p>
        </>
      )}
      {fc.length > 0 && (
        <div className="overflow-x-auto">
          <h3 className="text-[13px] font-semibold mb-2">Previsões temporais</h3>
          <table className="tbl text-[12.5px]">
            <thead><tr><th>Equipamento / variável</th><th>Modelo com menor MAE</th><th>MAE</th><th>Ganho vs. ingênuo</th><th>Quando</th><th /></tr></thead>
            <tbody>{fc.map((r) => {
              const b = r.resultados?.find((x) => x.modelo === r.melhor_modelo);
              return (<tr key={r.id}><td>{r.equipamentos[0]} / {r.variavel}</td><td>{b?.nome ?? "—"}</td><td className="num">{num(b?.metricas_holdout?.mae, 3)}</td>
                <td className="num">{b?.metricas_holdout?.ganho_vs_base_pct === undefined ? "—" : `${num(b?.metricas_holdout?.ganho_vs_base_pct, 1)}%`}</td>
                <td className="num">{dt(r.created_at)}</td>
                <td className="whitespace-nowrap"><Button variant="ghost" onClick={() => onOpen(r.id)}>Abrir</Button><Button variant="ghost" onClick={() => onDelete(r.id)}>Excluir</Button></td></tr>);
            })}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function Models() {
  const { current: ds } = useDataset();
  const [tab, setTab] = useState<Tab>("falha");
  const models = useAsync(() => api.models(), []);
  const runs = useAsync(() => api.runs(ds!.id), [ds?.id], !!ds);
  const [run, setRun] = useState<Run | null>(null);
  const [eqs, setEqs] = useState<string[]>([]);
  const [modelo, setModelo] = useState("random_forest");
  const [horiz, setHoriz] = useState(24);
  const [teste, setTeste] = useState(0.3);
  const [limiar, setLimiar] = useState(0.5);
  const [contam, setContam] = useState(0.02);
  const [fEq, setFEq] = useState("");
  const [fVar, setFVar] = useState("");
  const [fH, setFH] = useState(48);
  const [fHold, setFHold] = useState(168);

  useEffect(() => {
    if (!ds) return;
    setEqs(ds.equipment); setRun(null); setFEq(ds.equipment[0]); setFVar(ds.variables[0]?.key ?? "");
  }, [ds?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const train = useAction(async () => {
    if (!ds) throw new Error("Selecione um dataset.");
    if (tab === "falha") return api.classify(ds.id, { modelo, equipamentos: eqs, horizonte_h: horiz, fracao_teste: teste, limiar });
    if (tab === "anomalia") return api.anomaly(ds.id, { equipamentos: eqs, contaminacao: contam, horizonte_h: horiz, fracao_teste: teste });
    return api.forecast(ds.id, { equipamento: fEq, variavel: fVar, horizonte_h: fH, holdout_h: fHold });
  });

  async function doTrain() {
    const r = await train.run();
    if (r) { setRun(r); runs.reload(); }
  }

  if (!ds) return <Loading />;
  const supervised = ds.has_status;
  const avail = models.data?.classificacao_anomalia ?? {};
  const runList = runs.data ?? [];
  const visibleRun = run && ((tab === "previsao") === (run.tipo === "previsao")) && (tab !== "anomalia" || run.tipo === "anomalia") && (tab !== "falha" || run.tipo === "classificacao") ? run : null;

  return (
    <div className="space-y-4">
      <PageHeader title="Machine Learning">
        Modelos para antecipar falhas, detectar comportamento atípico e prever variáveis de processo. Toda avaliação usa divisão
        temporal (treino no passado, teste no futuro) e é comparada a uma linha de base.
      </PageHeader>

      <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((s) => (
          <li key={s.n} className="bg-panel border border-line rounded-[4px] px-3 py-2 flex gap-3">
            <span className="num text-[13px] font-semibold bg-frame text-frame-ink size-6 grid place-items-center rounded-[3px] shrink-0">{s.n}</span>
            <span><b className="text-[13px]">{s.nome}</b><span className="block text-[12px] text-ink-2">{s.desc}</span></span>
          </li>
        ))}
      </ol>

      <Panel bodyClass="p-4">
        <Tabs value={tab} onChange={(t) => { setTab(t); train.setError(null); }} items={[
          { value: "falha", label: "Previsão de falha" }, { value: "anomalia", label: "Detecção de anomalia" },
          { value: "previsao", label: "Previsão temporal" }, { value: "comparacao", label: `Comparar execuções (${runList.length})` },
        ]} />

        {tab !== "comparacao" && (
          <div className="space-y-4">
            {tab === "falha" && !supervised && (
              <Notice tone="warn">Este dataset não tem coluna de estado; não há rótulos de falha para treinar modelos supervisionados. Use a detecção de anomalia.</Notice>
            )}
            <div className="flex flex-wrap gap-3 items-start">
              {tab === "falha" && (
                <Field label="Algoritmo">
                  <Select value={modelo} onChange={(e) => setModelo(e.target.value)} options={["random_forest", "xgboost", "baseline"].filter((k) => avail[k]?.disponivel !== false).map((k) => ({ value: k, label: avail[k]?.nome ?? k }))} />
                </Field>
              )}
              {tab !== "previsao" ? (
                <>
                  <fieldset className="flex flex-col gap-1">
                    <legend className="text-[12.5px] text-ink-2 font-medium mb-1">Equipamentos</legend>
                    <div className="flex flex-wrap gap-1.5">
                      {ds.equipment.map((e) => {
                        const on = eqs.includes(e);
                        return <button key={e} aria-pressed={on} onClick={() => setEqs(on ? eqs.filter((x) => x !== e) : [...eqs, e])}
                          className={`px-2 py-1 text-[12.5px] rounded-[3px] border cursor-pointer ${on ? "bg-frame text-frame-ink border-frame" : "bg-raised border-line"}`}>{e}</button>;
                      })}
                    </div>
                  </fieldset>
                  <Field label="Horizonte (h)" hint={tab === "falha" ? "Prever falha nas próximas H horas" : "Para comparar com rótulos"}>
                    <input type="number" min={1} max={336} className="field num w-24" value={horiz} onChange={(e) => setHoriz(Number(e.target.value))} />
                  </Field>
                  <Field label="Fração de teste"><input type="number" step={0.05} min={0.1} max={0.6} className="field num w-24" value={teste} onChange={(e) => setTeste(Number(e.target.value))} /></Field>
                  {tab === "falha" && <Field label="Limiar de alerta"><input type="number" step={0.05} min={0.05} max={0.95} className="field num w-24" value={limiar} onChange={(e) => setLimiar(Number(e.target.value))} /></Field>}
                  {tab === "anomalia" && <Field label="Contaminação" hint="Fração esperada de pontos atípicos"><input type="number" step={0.01} min={0.005} max={0.3} className="field num w-24" value={contam} onChange={(e) => setContam(Number(e.target.value))} /></Field>}
                </>
              ) : (
                <>
                  <EquipVarPicker ds={ds} equipamento={fEq} variavel={fVar} onEquipamento={setFEq} onVariavel={setFVar} />
                  <Field label="Horizonte (h)"><input type="number" min={1} max={336} className="field num w-24" value={fH} onChange={(e) => setFH(Number(e.target.value))} /></Field>
                  <Field label="Holdout (h)" hint="Período final reservado para medir o erro"><input type="number" min={24} max={720} className="field num w-24" value={fHold} onChange={(e) => setFHold(Number(e.target.value))} /></Field>
                </>
              )}
              <Button className="mt-[23px]" variant="primary" onClick={doTrain}
                disabled={train.running || (tab !== "previsao" && eqs.length === 0) || (tab === "falha" && !supervised)}>
                {train.running ? "Treinando…" : tab === "previsao" ? "Gerar previsão" : "Treinar modelo"}
              </Button>
            </div>
            {tab === "falha" && avail[modelo] && <p className="text-[12px] text-ink-3">{avail[modelo].descricao}</p>}
            {tab === "anomalia" && <p className="text-[12px] text-ink-3">{avail.isolation_forest?.descricao} Treinado apenas com amostras em operação do período de treino.</p>}
            <ErrorBox>{train.error}</ErrorBox>
            {train.running && <Loading label="Treinando — com todos os equipamentos pode levar alguns segundos…" />}
            {visibleRun && !train.running && <RunResult run={visibleRun} />}
          </div>
        )}

        {tab === "comparacao" && (
          runs.loading && !runs.data ? <Loading /> :
            <ComparisonTab runs={runList}
              onOpen={async (id) => { const r = await api.run(id); setRun(r); setTab(r.tipo === "previsao" ? "previsao" : r.tipo === "anomalia" ? "anomalia" : "falha"); }}
              onDelete={async (id) => { await api.deleteRun(id); runs.reload(); if (run?.id === id) setRun(null); }} />
        )}
      </Panel>
    </div>
  );
}
