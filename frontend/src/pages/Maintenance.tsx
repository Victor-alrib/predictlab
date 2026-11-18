import { useEffect, useState } from "react";
import type { Data } from "plotly.js";
import { api, type MaintEquipment } from "../api/client";
import Plot from "../components/Plot";
import { Empty, ErrorBox, Field, IndicatorValue, Loading, Notice, PageHeader, Panel, Select, Stat } from "../components/ui";
import { useDataset } from "../lib/dataset";
import { dt, hours, localIso, num } from "../lib/format";
import { useAsync } from "../lib/hooks";

const TIME_LABEL: Record<string, string> = {
  operacao: "Operação", standby: "Parado / standby", falha_e_reparo: "Falha + reparo",
  manutencao_preventiva: "Manutenção preventiva", sem_dados: "Sem dados",
};
const TIME_COLOR: Record<string, string> = {
  operacao: "#7f8b95", standby: "#bcc2c7", falha_e_reparo: "#c8102e", manutencao_preventiva: "#2f6fb0", sem_dados: "#e5e7e9",
};

function EquipmentDetail({ m }: { m: MaintEquipment }) {
  const ind = m.indicadores;
  const times = Object.entries(m.tempos_h).filter(([k]) => k in TIME_LABEL);
  return (
    <Panel title={`${m.equipamento} — detalhes`}>
      {!m.suficiente && m.motivos.length > 0 && (
        <Notice tone="warn">
          <b>Indicadores parciais.</b> {m.motivos.join(" ")}
        </Notice>
      )}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-3">
        <Stat label="MTBF" note="tempo em operação ÷ nº de falhas"><IndicatorValue ind={ind.mtbf} big digits={1} /></Stat>
        <Stat label="MTTR" note="média de falhas completas"><IndicatorValue ind={ind.mttr} big digits={1} /></Stat>
        <Stat label="Disponibilidade intrínseca" note="MTBF ÷ (MTBF + MTTR)"><IndicatorValue ind={ind.disponibilidade_intrinseca} big digits={2} /></Stat>
        <Stat label="Disponibilidade observada" note="exclui falha, reparo e preventiva"><IndicatorValue ind={ind.disponibilidade_observada} big digits={2} /></Stat>
        <Stat label="Frequência de falhas"><IndicatorValue ind={ind.falhas_por_30d} big digits={2} /></Stat>
      </div>

      {times.length > 0 && (
        <div className="mt-4">
          <div className="text-[12.5px] text-ink-2 mb-1">Distribuição do tempo observado ({hours(m.tempos_h.observado)})</div>
          <div className="flex h-5 border border-line rounded-[2px] overflow-hidden" role="img" aria-label="Distribuição do tempo por estado">
            {times.map(([k, h]) => h > 0 && (
              <div key={k} style={{ width: `${(h / m.tempos_h.observado) * 100}%`, background: TIME_COLOR[k] }} title={`${TIME_LABEL[k]}: ${hours(h)}`} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1.5 text-[12px] text-ink-2">
            {times.map(([k, h]) => (
              <span key={k}><span className="inline-block size-2.5 mr-1 align-middle border border-line" style={{ background: TIME_COLOR[k] }} />
                {TIME_LABEL[k]}: <span className="num">{hours(h)}</span></span>
            ))}
          </div>
        </div>
      )}

      {m.dispersao && m.dispersao.tbf_h.length > 0 && (
        <p className="text-[12.5px] text-ink-2 mt-3">
          Tempos entre falhas (h de operação): <span className="num">{m.dispersao.tbf_h.map((x) => num(x, 0)).join(" · ")}</span>
          {m.dispersao.tbf_desvio_h !== null && <> — desvio-padrão <span className="num">{num(m.dispersao.tbf_desvio_h, 0)} h</span>. Com poucos intervalos, o MTBF é uma estimativa grosseira.</>}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2 mt-4">
        <div>
          <h3 className="text-[13px] font-semibold mb-2">Histórico de falhas</h3>
          {m.falhas.length ? (
            <div className="overflow-x-auto max-h-80 border border-line-soft">
              <table className="tbl text-[12.5px]">
                <thead><tr><th>Início</th><th>Falha</th><th>Reparo</th><th>Total</th><th /></tr></thead>
                <tbody>{m.falhas.map((f, i) => (
                  <tr key={i}>
                    <td className="num whitespace-nowrap">{dt(f.inicio)}</td>
                    <td className="num">{hours(f.duracao_falha_h)}</td>
                    <td className="num">{hours(f.duracao_reparo_h)}</td>
                    <td className="num font-medium">{hours(f.duracao_h)}</td>
                    <td className="text-ink-3 text-[11.5px]">{f.truncada ? "truncada (fora do MTTR)" : ""}</td>
                  </tr>))}
                </tbody>
              </table>
            </div>
          ) : <Empty title="Nenhuma falha registrada" />}
          {m.preventivas.length > 0 && (
            <p className="text-[12px] text-ink-3 mt-2">
              Manutenções preventivas: {m.preventivas.map((p) => `${dt(p.inicio)} (${hours(p.duracao_h)})`).join("; ")}. Não entram no MTTR.
            </p>
          )}
        </div>
        <div>
          <h3 className="text-[13px] font-semibold mb-2">Ocorrências por semana <span className="font-normal text-ink-3">(data = segunda-feira da semana)</span></h3>
          {m.frequencia_semanal.length ? (
            <Plot height={240} ariaLabel="Falhas por semana" data={[{ type: "bar", x: m.frequencia_semanal.map((w) => w.semana), y: m.frequencia_semanal.map((w) => w.falhas), marker: { color: "#c8102e" } }]}
              layout={{ yaxis: { dtick: 1, title: { text: "Falhas" } }, hovermode: "closest" }} />
          ) : <Empty title="Sem ocorrências" />}
        </div>
      </div>
    </Panel>
  );
}

export default function Maintenance() {
  const { current: ds } = useDataset();
  const [minF, setMinF] = useState(2);
  const [minD, setMinD] = useState(7);
  const [sel, setSel] = useState("");
  useEffect(() => setSel(""), [ds?.id]);
  const r = useAsync(() => api.maintenance(ds!.id, { min_falhas: minF, min_dias: minD }), [ds?.id, minF, minD], !!ds);

  if (!ds) return <Loading />;
  const d = r.data;
  const eqSel = sel || d?.equipamentos[0]?.equipamento || "";
  const detail = d?.equipamentos.find((e) => e.equipamento === eqSel);

  const timeline: Data[] = [];
  d?.equipamentos.forEach((m) => {
    m.falhas.forEach((f) => timeline.push({ type: "scatter", mode: "lines", x: [f.inicio, f.fim], y: [m.equipamento, m.equipamento], line: { color: "#c8102e", width: 14 }, showlegend: false, hovertemplate: `Falha · ${hours(f.duracao_h)}<extra>${m.equipamento}</extra>` }));
    m.preventivas.forEach((p) => {
      const end = localIso(new Date(p.inicio).getTime() + p.duracao_h * 3600_000);
      timeline.push({ type: "scatter", mode: "lines", x: [p.inicio, end], y: [m.equipamento, m.equipamento], line: { color: "#2f6fb0", width: 14 }, showlegend: false, hovertemplate: `Preventiva · ${hours(p.duracao_h)}<extra>${m.equipamento}</extra>` });
    });
  });

  return (
    <div className="space-y-4">
      <PageHeader title="Indicadores de manutenção">
        MTBF, MTTR, disponibilidade e histórico de falhas calculados a partir da coluna de estado operacional. Quando os dados não
        bastam, o indicador aparece como "dados insuficientes" com o motivo, em vez de um número pouco confiável.
      </PageHeader>

      {!ds.has_status && (
        <Notice tone="warn">
          Este dataset não tem coluna de estado operacional mapeada, então não há como identificar falhas e reparos. Reimporte o
          arquivo mapeando a coluna de estado, se ela existir.
        </Notice>
      )}

      <Panel bodyClass="p-4 flex flex-wrap gap-4 items-start">
        <Field label="Mínimo de falhas para estimar" hint="Abaixo disso, MTBF/MTTR não são exibidos.">
          <input type="number" min={1} max={50} className="field num w-28" value={minF} onChange={(e) => setMinF(Math.max(1, Number(e.target.value)))} />
        </Field>
        <Field label="Mínimo de dias observados">
          <input type="number" min={0} max={365} className="field num w-28" value={minD} onChange={(e) => setMinD(Math.max(0, Number(e.target.value)))} />
        </Field>
        {d && <Field label="Detalhar equipamento"><Select value={eqSel} onChange={(e) => setSel(e.target.value)} options={d.equipamentos.map((m) => ({ value: m.equipamento, label: m.equipamento }))} /></Field>}
      </Panel>

      <ErrorBox>{r.error}</ErrorBox>
      {!d ? <Loading /> : (
        <>
          <Panel title="Resumo por equipamento" bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="tbl text-[13px]">
                <thead><tr><th>Equipamento</th><th>Falhas</th><th>MTBF</th><th>MTTR</th><th>Disp. intrínseca</th><th>Disp. observada</th><th>Falhas / 30 dias</th></tr></thead>
                <tbody>
                  {d.equipamentos.map((m) => (
                    <tr key={m.equipamento} onClick={() => setSel(m.equipamento)} className={`cursor-pointer ${m.equipamento === eqSel ? "bg-raised" : ""}`}>
                      <td className="font-semibold">{m.equipamento}</td>
                      <td className="num">{d.possui_estado ? m.n_falhas : "—"}</td>
                      <td><IndicatorValue ind={m.indicadores.mtbf} /></td>
                      <td><IndicatorValue ind={m.indicadores.mttr} /></td>
                      <td><IndicatorValue ind={m.indicadores.disponibilidade_intrinseca} digits={2} /></td>
                      <td><IndicatorValue ind={m.indicadores.disponibilidade_observada} digits={2} /></td>
                      <td><IndicatorValue ind={m.indicadores.falhas_por_30d} digits={2} /></td>
                    </tr>
                  ))}
                  {d.frota && (
                    <tr className="bg-well/50 font-medium">
                      <td>Frota</td><td className="num">{d.frota.n_falhas}</td>
                      <td><IndicatorValue ind={d.frota.indicadores.mtbf} /></td>
                      <td><IndicatorValue ind={d.frota.indicadores.mttr} /></td>
                      <td><IndicatorValue ind={d.frota.indicadores.disponibilidade_intrinseca} digits={2} /></td>
                      <td><IndicatorValue ind={d.frota.indicadores.disponibilidade_observada} digits={2} /></td>
                      <td>—</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          {timeline.length > 0 && (
            <Panel title="Linha do tempo de paradas" bodyClass="p-2">
              <Plot height={110 + 38 * d.equipamentos.length} data={timeline} ariaLabel="Linha do tempo de falhas e preventivas"
                layout={{ hovermode: "closest", yaxis: { type: "category", automargin: true }, xaxis: { type: "date", range: [ds.start, ds.end] }, margin: { l: 70, r: 16, t: 8, b: 36 } }} />
              <p className="text-[11.5px] text-ink-3 px-2"><span className="inline-block size-2.5 bg-alarm mr-1 align-middle" />Falha (inclui reparo)
                <span className="inline-block size-2.5 bg-maint ml-4 mr-1 align-middle" />Manutenção preventiva</p>
            </Panel>
          )}

          {detail && d.possui_estado && <EquipmentDetail m={detail} />}
        </>
      )}
    </div>
  );
}
