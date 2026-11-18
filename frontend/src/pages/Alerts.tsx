import { useEffect, useState } from "react";
import { api, type Alert, type Origin, type Severity, type Threshold } from "../api/client";
import AlertTable from "../components/AlertTable";
import { EquipVarPicker } from "../components/Pickers";
import TimeSeriesChart, { ChartLegendNote } from "../components/TimeSeriesChart";
import { Button, ErrorBox, Field, Loading, Notice, OriginIcon, PageHeader, Panel, Select } from "../components/ui";
import { useDataset, varLabel, varUnit } from "../lib/dataset";
import { localIso, num, ORIGIN_HINT, ORIGIN_LABEL, SEVERITY_LABEL } from "../lib/format";
import { useAction, useAsync } from "../lib/hooks";

const ORIGINS: Origin[] = ["limite", "estatistica", "modelo"];
const BORDER = { limite: "border-orig-limite", estatistica: "border-orig-estat", modelo: "border-orig-modelo" };

function ThresholdEditor({ onChanged }: { onChanged: () => void }) {
  const { current: ds } = useDataset();
  const th = useAsync(() => api.thresholds(ds!.id), [ds?.id], !!ds);
  const [eq, setEq] = useState(ds?.equipment[0] ?? "");
  const [v, setV] = useState(ds?.variables[0]?.key ?? "");
  const [form, setForm] = useState<{ min: string; max: string; severidade: Severity; dur: string }>({ min: "", max: "", severidade: "media", dur: "0" });
  const [hint, setHint] = useState<string | null>(null);
  const save = useAction(api.setThreshold);
  const del = useAction(api.deleteThreshold);
  const sug = useAction(api.suggestThreshold);

  useEffect(() => {
    const cur = th.data?.limites?.[eq]?.[v];
    setForm({ min: cur?.min?.toString() ?? "", max: cur?.max?.toString() ?? "", severidade: cur?.severidade ?? "media", dur: String(cur?.duracao_min_min ?? 0) });
    setHint(null);
  }, [eq, v, th.data]);

  if (!ds) return null;
  const rows = Object.entries(th.data?.limites ?? {}).flatMap(([e, vs]) => Object.entries(vs).map(([k, t]) => ({ e, k, t: t as Threshold })));

  async function submit() {
    const t: Threshold = { min: form.min === "" ? null : Number(form.min.replace(",", ".")), max: form.max === "" ? null : Number(form.max.replace(",", ".")),
      severidade: form.severidade, duracao_min_min: Number(form.dur) || 0 };
    if (await save.run(ds!.id, eq, v, t) !== undefined) { th.reload(); onChanged(); }
  }

  return (
    <Panel title="Limites de alarme configurados">
      <p className="text-[12.5px] text-ink-2 mb-3 max-w-[85ch]">
        Limites geram alertas da origem "Limite configurado". Use valores de especificação do fabricante ou da engenharia de processo;
        a sugestão automática é só um ponto de partida estatístico.
      </p>
      <div className="flex flex-wrap gap-3 items-start">
        <EquipVarPicker ds={ds} equipamento={eq} variavel={v} onEquipamento={setEq} onVariavel={setV} allowAll />
        <Field label={`Mínimo (${varUnit(ds, v)})`}><input className="field num w-24" inputMode="decimal" value={form.min} onChange={(e) => setForm({ ...form, min: e.target.value })} /></Field>
        <Field label={`Máximo (${varUnit(ds, v)})`}><input className="field num w-24" inputMode="decimal" value={form.max} onChange={(e) => setForm({ ...form, max: e.target.value })} /></Field>
        <Field label="Severidade"><Select value={form.severidade} onChange={(e) => setForm({ ...form, severidade: e.target.value as Severity })}
          options={[{ value: "baixa", label: "Baixa" }, { value: "media", label: "Média" }, { value: "alta", label: "Alta" }]} /></Field>
        <Field label="Duração mínima (min)" hint="Ignora violações mais curtas"><input type="number" min={0} className="field num w-24" value={form.dur} onChange={(e) => setForm({ ...form, dur: e.target.value })} /></Field>
        <Button className="mt-[23px]" variant="primary" onClick={submit} disabled={save.running || (form.min === "" && form.max === "")}>Salvar limite</Button>
        <Button className="mt-[23px]" disabled={eq === "*" || sug.running} onClick={async () => {
          const s = await sug.run(ds.id, eq, v);
          if (s) { setForm({ ...form, min: String(s.min), max: String(s.max) }); setHint(`${s.base}. ${s.aviso}`); }
        }}>Sugerir pelos dados</Button>
      </div>
      {hint && <p className="text-[12px] text-warn mt-2">{hint}</p>}
      <div className="mt-2 space-y-2"><ErrorBox>{save.error || sug.error || del.error}</ErrorBox></div>
      {rows.length > 0 && (
        <div className="overflow-x-auto mt-4">
          <table className="tbl text-[12.5px]">
            <thead><tr><th>Equipamento</th><th>Variável</th><th>Mínimo</th><th>Máximo</th><th>Severidade</th><th>Duração mín.</th><th /></tr></thead>
            <tbody>{rows.map(({ e, k, t }) => (
              <tr key={`${e}/${k}`}>
                <td>{e === "*" ? "Todos" : e}</td><td>{varLabel(ds, k)}</td>
                <td className="num">{num(t.min ?? null, 2)}</td><td className="num">{num(t.max ?? null, 2)}</td>
                <td>{SEVERITY_LABEL[t.severidade]}</td><td className="num">{t.duracao_min_min ?? 0} min</td>
                <td className="text-right whitespace-nowrap">
                  <Button variant="ghost" onClick={() => { setEq(e); setV(k); }}>Editar</Button>
                  <Button variant="ghost" onClick={async () => { await del.run(ds.id, e, k); th.reload(); onChanged(); }}>Remover</Button>
                </td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export default function Alerts() {
  const { current: ds } = useDataset();
  const [origens, setOrigens] = useState<Origin[]>(ORIGINS);
  const [eq, setEq] = useState("*");
  const [sev, setSev] = useState("");
  const [k, setK] = useState(4);
  const [sel, setSel] = useState<Alert | null>(null);
  useEffect(() => { setEq("*"); setSel(null); }, [ds?.id]);

  const all = useAsync(() => api.alerts(ds!.id, { equipamento: eq === "*" ? undefined : eq, k }), [ds?.id, eq, k], !!ds);
  const shown = (all.data?.alertas ?? []).filter((a) => origens.includes(a.origem) && (!sev || a.severidade === sev));
  const ctxStart = sel ? localIso(new Date(sel.inicio).getTime() - 3 * 86400_000) : undefined;
  const ctxEnd = sel ? localIso(new Date(sel.fim).getTime() + 1 * 86400_000) : undefined;
  const ctx = useAsync(() => api.series(ds!.id, sel!.equipamento, undefined, 2000, ctxStart, ctxEnd), [sel?.id], !!ds && !!sel);

  if (!ds) return <Loading />;
  const sum = all.data?.resumo;

  return (
    <div className="space-y-4">
      <PageHeader title="Alertas">
        Três origens de alerta, tratadas de forma independente. Um alerta de limite é uma regra; uma anomalia estatística é um
        desvio do comportamento habitual; uma previsão de modelo é uma estimativa probabilística.
      </PageHeader>

      <div className="grid gap-2 md:grid-cols-3">
        {ORIGINS.map((o) => {
          const on = origens.includes(o);
          return (
            <button key={o} aria-pressed={on} onClick={() => setOrigens(on ? origens.filter((x) => x !== o) : [...origens, o])}
              className={`text-left bg-panel border-l-[5px] ${BORDER[o]} border border-line rounded-[4px] px-4 py-3 cursor-pointer ${on ? "" : "opacity-50"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-semibold"><OriginIcon origem={o} size={14} />{ORIGIN_LABEL[o]}</span>
                <span className="num text-[24px] font-semibold leading-none">{sum ? sum.por_origem[o] : "—"}</span>
              </div>
              <p className="text-[12px] text-ink-2 mt-1.5">{ORIGIN_HINT[o]}</p>
              <p className="text-[11.5px] text-ink-3 mt-1">{on ? "Exibindo — clique para ocultar" : "Oculto — clique para exibir"}</p>
            </button>
          );
        })}
      </div>

      <Panel bodyClass="p-4 flex flex-wrap gap-3 items-start">
        <EquipVarPicker ds={ds} equipamento={eq} onEquipamento={setEq} allowAll />
        <Field label="Severidade"><Select value={sev} onChange={(e) => setSev(e.target.value)} options={[{ value: "", label: "Todas" }, { value: "alta", label: "Alta" }, { value: "media", label: "Média" }, { value: "baixa", label: "Baixa" }]} /></Field>
        <Field label="Sensibilidade estatística (|z| >)" hint="Maior = menos anomalias">
          <Select value={String(k)} onChange={(e) => setK(Number(e.target.value))} options={[3, 3.5, 4, 5, 6].map((x) => ({ value: String(x), label: num(x, 1) }))} />
        </Field>
        <span className="text-[12.5px] text-ink-2 mt-[29px]">{shown.length} alerta(s) exibido(s)</span>
      </Panel>

      {sum && sum.por_origem.modelo === 0 && origens.includes("modelo") && (
        <Notice>Nenhuma previsão de modelo ainda. Treine um modelo em Machine Learning: as probabilidades altas no período de teste viram alertas desta origem.</Notice>
      )}

      {sel && (
        <Panel title={`Contexto do alerta ${sel.id} — ${sel.equipamento}`} actions={<Button variant="ghost" onClick={() => setSel(null)}>Fechar</Button>}>
          <p className="text-[13px] mb-2">{sel.mensagem} <span className="text-ink-3">({sel.metodo})</span></p>
          {ctx.data ? (
            <>
              <TimeSeriesChart ds={ds} series={ctx.data} alerts={[sel]} height={300}
                varsShown={sel.variavel ? [sel.variavel] : Object.keys(ctx.data.series).slice(0, 2)} />
              <ChartLegendNote />
            </>
          ) : <Loading />}
        </Panel>
      )}

      <Panel title="Histórico de alertas" bodyClass="p-0">
        <ErrorBox>{all.error}</ErrorBox>
        {all.loading && !all.data ? <Loading label="Calculando alertas…" /> : (
          <div className="max-h-[560px] overflow-y-auto"><AlertTable alerts={shown.slice(0, 400)} ds={ds} onSelect={setSel} /></div>
        )}
        {shown.length > 400 && <p className="px-4 py-2 text-[12px] text-ink-3">Exibindo os 400 mais recentes de {shown.length}.</p>}
      </Panel>

      <ThresholdEditor onChanged={all.reload} />
    </div>
  );
}
