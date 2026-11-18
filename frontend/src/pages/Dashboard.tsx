import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard as D, type EquipmentCard } from "../api/client";
import AlertTable from "../components/AlertTable";
import TimeSeriesChart, { ChartLegendNote } from "../components/TimeSeriesChart";
import { Button, Empty, ErrorBox, IndicatorValue, Loading, Notice, OriginIcon, Panel, Stat, StateBadge } from "../components/ui";
import { useDataset } from "../lib/dataset";
import { dt, localIso, num } from "../lib/format";
import { useAsync } from "../lib/hooks";

function Sparkline({ values, color = "#2f5d87" }: { values: (number | null)[]; color?: string }) {
  const pts = values.map((v, i) => [i, v] as const).filter(([, v]) => v !== null) as [number, number][];
  if (pts.length < 2) return <div className="h-7" />;
  const ys = pts.map((p) => p[1]);
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1, n = values.length - 1 || 1;
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${((i / n) * 100).toFixed(2)},${(26 - ((v - lo) / span) * 24).toFixed(2)}`).join("");
  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="w-full h-7" aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const MONITOR_STYLE: Record<string, { box: string; dot: string; blink?: boolean }> = {
  falha: { box: "border-alarm", dot: "bg-alarm", blink: true },
  alarme: { box: "border-alarm", dot: "bg-alarm", blink: true },
  atencao: { box: "border-warn", dot: "bg-warn" },
  manutencao: { box: "border-maint", dot: "bg-maint" },
  sem_dados: { box: "border-line border-dashed", dot: "bg-ink-3" },
  parado: { box: "border-line", dot: "bg-well border border-ink-3" },
  normal: { box: "border-line", dot: "bg-raised border border-ink-3" },
  indefinido: { box: "border-line", dot: "bg-raised border border-ink-3" },
};

function Faceplate({ c, selected, onSelect }: { c: EquipmentCard; selected: boolean; onSelect: () => void }) {
  const st = MONITOR_STYLE[c.monitoramento.codigo] ?? MONITOR_STYLE.indefinido;
  const sparkKeys = Object.keys(c.sparkline).filter((k) => k !== "timestamps");
  return (
    <button
      onClick={onSelect}
      aria-pressed={selected}
      className={`text-left bg-raised border-2 ${st.box} rounded-[4px] p-3 flex flex-col gap-2 cursor-pointer min-w-0
        ${selected ? "outline-2 outline-frame outline-offset-2" : "hover:bg-white"}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold text-[15px] leading-tight">{c.equipamento}</div>
          {c.descricao && <div className="text-[11.5px] text-ink-3 leading-snug line-clamp-2">{c.descricao}</div>}
        </div>
        <div className="flex items-center gap-1.5 shrink-0 text-[12px] font-medium">
          <span className={`inline-block size-2.5 rounded-[2px] ${st.dot} ${st.blink ? "blink" : ""}`} aria-hidden />
          {c.monitoramento.rotulo}
        </div>
      </div>

      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-[12.5px]">
        {c.valores.map((v) => {
          const out = v.fora_do_limite;
          return (
            <div key={v.variavel} className="contents">
              <dt className="text-ink-2 truncate">{v.rotulo}</dt>
              <dd className={`num text-right ${out ? "bg-alarm text-white px-1 rounded-[2px] font-semibold" : ""}`}
                title={v.limite ? `Limite: ${v.limite.min ?? "—"} a ${v.limite.max ?? "—"}` : "Sem limite configurado"}>
                {out === "max" ? "▲ " : out === "min" ? "▼ " : ""}{num(v.valor, 1)}
                <span className={out ? "ml-1" : "text-ink-3 ml-1"}>{v.unidade}</span>
              </dd>
            </div>
          );
        })}
      </dl>

      {sparkKeys[0] && (
        <div>
          <Sparkline values={c.sparkline[sparkKeys[0]] as (number | null)[]} />
          <div className="text-[11px] text-ink-3">Últimas 48 h de {c.valores.find((v) => v.variavel === sparkKeys[0])?.rotulo.toLowerCase()}</div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-ink-2 border-t border-line-soft pt-2">
        <span>Estado: <StateBadge estado={c.estado_operacional} /></span>
        <span>Alertas ativos: <b className="num">{c.alertas_ativos}</b></span>
        <span>Falhas: <b className="num">{c.n_falhas}</b></span>
      </div>
      {c.alertas_ativos_detalhe.length > 0 && (
        <ul className="text-[11.5px] space-y-0.5">
          {c.alertas_ativos_detalhe.slice(0, 2).map((a, i) => (
            <li key={i} className="flex gap-1.5 items-start"><span className="mt-0.5"><OriginIcon origem={a.origem} size={10} /></span>{a.mensagem}</li>
          ))}
        </ul>
      )}
    </button>
  );
}

function Replay({ d, value, onChange }: { d: D; value: string | null; onChange: (v: string | null) => void }) {
  const t0 = new Date(d.dataset.start).getTime(), t1 = new Date(d.dataset.end).getTime();
  const cur = value ? new Date(value).getTime() : t1;
  const [draft, setDraft] = useState(cur);
  useEffect(() => setDraft(cur), [cur]);
  const toIso = (ms: number) => localIso(ms).slice(0, 16);
  return (
    <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-4">
      <label className="flex-1 flex flex-col gap-1">
        <span className="text-[12.5px] text-ink-2">
          Reprodução histórica: painel como estava em <b className="num text-ink">{dt(new Date(draft).toISOString())}</b>
        </span>
        <input
          type="range" min={t0} max={t1} step={3600_000} value={draft}
          onChange={(e) => setDraft(Number(e.target.value))}
          onPointerUp={() => onChange(draft >= t1 ? null : toIso(draft))}
          onKeyUp={() => onChange(draft >= t1 ? null : toIso(draft))}
          className="w-full accent-[#2b3a48]"
          aria-label="Instante de referência do painel"
        />
      </label>
      <Button onClick={() => onChange(null)} disabled={!value}>Voltar ao último registro</Button>
    </div>
  );
}

export default function Dashboard() {
  const { current: ds } = useDataset();
  const [ref, setRef] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { setRef(null); setSel(null); }, [ds?.id]);

  const dash = useAsync(() => api.dashboard(ds!.id, ref ?? undefined), [ds?.id, ref], !!ds);
  const d = dash.data;
  const equip = sel ?? d?.equipamentos[0]?.equipamento ?? null;
  const card = d?.equipamentos.find((c) => c.equipamento === equip);
  const vars = card?.valores.map((v) => v.variavel) ?? [];
  const [shown, setShown] = useState<string[]>([]);
  useEffect(() => { setShown(vars.slice(0, 1)); }, [equip, ds?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const t1 = d?.referencia_temporal;
  const t0 = useMemo(() => (t1 ? localIso(new Date(t1).getTime() - 7 * 86400_000) : undefined), [t1]);
  const series = useAsync(() => api.series(ds!.id, equip!, undefined, 2500, t0, t1?.slice(0, 19)),
    [ds?.id, equip, t0, t1], !!ds && !!equip && !!t1);
  const alerts = useAsync(() => api.alerts(ds!.id, { equipamento: equip! }), [ds?.id, equip, d?.resumo_alertas.total], !!ds && !!equip);

  if (!ds) return <Loading label="Carregando datasets…" />;
  if (dash.error) return <ErrorBox>{dash.error}</ErrorBox>;
  if (!d) return <Loading label="Montando o painel…" />;

  const k = d.kpis;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">{ds.name}</h1>
          <p className="text-ink-2 text-[13px]">
            Situação no instante <span className="num">{dt(d.referencia_temporal)}</span>
            {d.reproducao_historica ? " (reprodução histórica — só dados até este instante)" : " (último registro do dataset)"}.
            Este painel reproduz dados históricos importados; não há conexão com equipamentos em tempo real.
          </p>
        </div>
        {dash.loading && <span className="text-ink-3 text-sm">Atualizando…</span>}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
        <Stat label="Equipamentos monitorados"><span className="num text-[26px] font-semibold leading-none">{k.equipamentos}</span></Stat>
        <Stat label="Em falha ou alarme"><span className={`num text-[26px] font-semibold leading-none ${k.em_alarme ? "text-alarm" : ""}`}>{k.em_alarme}</span></Stat>
        <Stat label="Alertas nos últimos 7 dias"><span className="num text-[26px] font-semibold leading-none">{k.alertas_ultimos_7d}</span></Stat>
        <Stat label="Falhas registradas" note={!k.possui_estado ? "sem coluna de estado" : undefined}>
          <span className="num text-[26px] font-semibold leading-none">{k.possui_estado ? k.falhas_registradas : "—"}</span>
        </Stat>
        <Stat label="Disponibilidade observada"><IndicatorValue ind={k.disponibilidade_observada} digits={2} big /></Stat>
        <Stat label="MTBF da frota"><IndicatorValue ind={k.mtbf_frota} digits={0} big /></Stat>
      </div>

      <Panel bodyClass="px-4 py-3"><Replay d={d} value={ref} onChange={setRef} /></Panel>

      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
        {d.equipamentos.map((c) => (
          <Faceplate key={c.equipamento} c={c} selected={c.equipamento === equip} onSelect={() => setSel(c.equipamento)} />
        ))}
      </div>

      <Panel
        title={`Tendência — ${equip ?? ""} (7 dias até a referência)`}
        actions={
          <div className="flex flex-wrap gap-1.5">
            {vars.map((v) => {
              const lbl = card?.valores.find((x) => x.variavel === v)?.rotulo ?? v;
              const on = shown.includes(v);
              return (
                <button key={v} aria-pressed={on}
                  onClick={() => setShown(on ? shown.filter((x) => x !== v) : [...shown, v].slice(-2))}
                  className={`px-2 py-0.5 text-[12px] rounded-[3px] border cursor-pointer ${on ? "bg-frame text-frame-ink border-frame" : "bg-raised border-line text-ink-2"}`}>
                  {lbl}
                </button>
              );
            })}
          </div>
        }
      >
        {series.error && <ErrorBox>{series.error}</ErrorBox>}
        {series.data && shown.length > 0 ? (
          <>
            <TimeSeriesChart ds={ds} series={series.data} alerts={alerts.data?.alertas ?? []} varsShown={shown} />
            <ChartLegendNote />
          </>
        ) : series.loading ? <Loading /> : <Empty title="Selecione até duas variáveis para o gráfico" />}
      </Panel>

      <Panel title="Histórico de alarmes recentes" actions={<Link to="/alertas" className="text-[13px] text-steel underline underline-offset-2">Ver todos os alertas</Link>}
        bodyClass="p-0">
        {d.alarmes_recentes.length
          ? <AlertTable alerts={d.alarmes_recentes.slice(0, 12)} ds={ds} compact />
          : <Empty title="Nenhum alerta até este instante">Configure limites em Alertas ou treine um modelo para gerar previsões.</Empty>}
      </Panel>

      {ds.is_demo && (
        <Notice>
          Este é o ambiente de demonstração: quatro equipamentos simulados com falhas injetadas de propósito
          (incluindo falhas súbitas sem sinal precursor). Para analisar seus próprios dados, use{" "}
          <Link to="/importacao" className="underline">Importação de dados</Link>.
        </Notice>
      )}
    </div>
  );
}
