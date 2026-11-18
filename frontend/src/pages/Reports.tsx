import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Button, ErrorBox, Field, Loading, Notice, PageHeader, Panel, Select } from "../components/ui";
import { useDataset } from "../lib/dataset";
import { dt } from "../lib/format";
import { useAction, useAsync } from "../lib/hooks";

const SECTIONS = [
  { k: "resumo", l: "Resumo e procedência do dataset" },
  { k: "qualidade", l: "Qualidade dos dados" },
  { k: "series", l: "Séries temporais e limites" },
  { k: "manutencao", l: "Indicadores de manutenção" },
  { k: "alertas", l: "Alertas" },
  { k: "modelos", l: "Modelos e resultados" },
  { k: "metodologia", l: "Metodologia, limitações e reprodutibilidade" },
];

export default function Reports() {
  const { current: ds } = useDataset();
  const [eq, setEq] = useState("*");
  const [secoes, setSecoes] = useState(SECTIONS.map((s) => s.k));
  const [titulo, setTitulo] = useState("");
  const [autor, setAutor] = useState("");
  const [runIds, setRunIds] = useState<string[] | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const runs = useAsync(() => api.runs(ds!.id), [ds?.id], !!ds);
  const gen = useAction(api.report);
  useEffect(() => { setHtml(null); setEq("*"); setRunIds(null); }, [ds?.id]);

  if (!ds) return <Loading />;
  const list = runs.data ?? [];
  const chosen = runIds ?? list.map((r) => r.id);

  async function build(embed = true) {
    const h = await gen.run(ds!.id, { equipamento: eq === "*" ? null : eq, secoes, run_ids: chosen.length ? chosen : null,
      titulo: titulo || null, autor: autor || null, embutir_plotly: embed });
    if (h) setHtml(h);
    return h;
  }
  function download(h: string) {
    const blob = new Blob([h], { type: "text/html;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `relatorio_${ds!.name.replace(/[^\w-]+/g, "_").slice(0, 50)}.html`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Relatórios">
        Gere um relatório técnico com gráficos interativos, indicadores, alertas, resultados de modelos e a metodologia aplicada.
        O arquivo HTML é autocontido e pode ser impresso em PDF pelo navegador.
      </PageHeader>

      {ds.is_synthetic && <Notice tone="warn">O dataset atual é simulado. O relatório leva aviso de simulação no cabeçalho, nas limitações, no rodapé e como marca d'água.</Notice>}

      <Panel title="Conteúdo">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <Field label="Título (opcional)"><input className="field" value={titulo} placeholder={`Relatório técnico — ${ds.name}`} onChange={(e) => setTitulo(e.target.value)} /></Field>
            <Field label="Autor (opcional)"><input className="field" value={autor} onChange={(e) => setAutor(e.target.value)} /></Field>
            <Field label="Escopo"><Select value={eq} onChange={(e) => setEq(e.target.value)} options={[{ value: "*", label: "Todos os equipamentos" }, ...ds.equipment.map((e) => ({ value: e, label: e }))]} /></Field>
          </div>
          <fieldset>
            <legend className="text-[12.5px] text-ink-2 font-medium mb-1.5">Seções</legend>
            <div className="space-y-1">
              {SECTIONS.map((s) => (
                <label key={s.k} className="flex items-center gap-2 text-[13px]">
                  <input type="checkbox" checked={secoes.includes(s.k)} onChange={(e) => setSecoes(e.target.checked ? [...secoes, s.k] : secoes.filter((x) => x !== s.k))} />
                  {s.l}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        {secoes.includes("modelos") && (
          <fieldset className="mt-4">
            <legend className="text-[12.5px] text-ink-2 font-medium mb-1.5">Execuções de modelos incluídas</legend>
            {list.length === 0 ? <p className="text-[12.5px] text-ink-3">Nenhum modelo treinado neste dataset; a seção indicará isso.</p> : (
              <div className="grid gap-1 md:grid-cols-2">
                {list.map((r) => (
                  <label key={r.id} className="flex items-center gap-2 text-[12.5px]">
                    <input type="checkbox" checked={chosen.includes(r.id)} onChange={(e) => setRunIds(e.target.checked ? [...chosen, r.id] : chosen.filter((x) => x !== r.id))} />
                    {r.modelo_nome} — {r.tipo === "previsao" ? `${r.equipamentos[0]} / ${r.variavel}` : r.equipamentos.join(", ")} <span className="text-ink-3 num">({dt(r.created_at)})</span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>
        )}
        <div className="flex flex-wrap gap-2 mt-4">
          <Button variant="primary" disabled={gen.running || secoes.length === 0} onClick={() => build()}>{gen.running ? "Gerando…" : "Gerar relatório"}</Button>
          {html && <Button onClick={() => download(html)}>Baixar HTML</Button>}
          {html && <Button onClick={() => { const w = window.open("", "_blank"); if (w) { w.document.write(html); w.document.close(); } }}>Abrir em nova aba para imprimir</Button>}
        </div>
        <p className="text-[11.5px] text-ink-3 mt-2">O arquivo embute a biblioteca de gráficos (~3,5 MB) e abre sem internet.</p>
        <div className="mt-2"><ErrorBox>{gen.error}</ErrorBox></div>
      </Panel>

      {html && (
        <Panel title="Pré-visualização" bodyClass="p-0">
          <iframe title="Pré-visualização do relatório" srcDoc={html} className="w-full h-[80vh] bg-white border-0" sandbox="allow-scripts allow-popups" />
        </Panel>
      )}
    </div>
  );
}
