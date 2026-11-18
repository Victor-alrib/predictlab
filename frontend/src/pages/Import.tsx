import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DataOrigin, type UploadResp, type VarMap } from "../api/client";
import { Button, ErrorBox, Field, Loading, Notice, PageHeader, Panel, Select } from "../components/ui";
import { useDataset } from "../lib/dataset";
import { dt, num, ORIGIN_DATA_LABEL } from "../lib/format";
import { useAction, useAsync } from "../lib/hooks";

const NONE = "__none__";

function DropZone({ onFile, busy }: { onFile: (f: File) => void; busy: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
      className={`border-2 border-dashed rounded-[4px] px-6 py-10 text-center ${over ? "border-frame bg-raised" : "border-line bg-panel"}`}
    >
      <p className="font-semibold">Arraste um arquivo CSV para cá</p>
      <p className="text-ink-2 text-[13px] mt-1 max-w-[62ch] mx-auto">
        Separador (vírgula, ponto e vírgula ou tabulação), vírgula decimal e codificação são detectados automaticamente.
        Só a coluna de data/hora é obrigatória; as demais são mapeadas na próxima etapa.
      </p>
      <Button className="mt-4" variant="primary" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? "Lendo arquivo…" : "Escolher arquivo CSV"}
      </Button>
      <input ref={input} type="file" accept=".csv,text/csv,.txt" className="sr-only"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
    </div>
  );
}

export default function ImportPage() {
  const { datasets, refresh, select } = useDataset();
  const nav = useNavigate();
  const meta = useAsync(() => api.meta(), []);
  const [up, setUp] = useState<UploadResp | null>(null);
  const [roles, setRoles] = useState<{ timestamp: string | null; equipamento: string | null; estado: string | null }>({ timestamp: null, equipamento: null, estado: null });
  const [vars, setVars] = useState<VarMap[]>([]);
  const [statusMap, setStatusMap] = useState<Record<string, string>>({});
  const [eqDefault, setEqDefault] = useState("EQ-01");
  const [tsFormat, setTsFormat] = useState("");
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [origem, setOrigem] = useState<DataOrigin | "">("");
  const [result, setResult] = useState<{ id: string; avisos: string[]; linhas: number; lidas: number } | null>(null);

  const uploadA = useAction(api.upload);
  const importA = useAction(api.importDataset);
  const deleteA = useAction(api.deleteDataset);

  async function onFile(f: File) {
    setResult(null);
    const r = await uploadA.run(f);
    if (!r) return;
    setUp(r);
    setRoles(r.sugestao.roles);
    // todas as colunas aparecem na tabela; as usadas como papel ficam ocultas enquanto tiverem papel
    setVars(r.info.columns.map((c) => r.sugestao.variables.find((v) => v.column === c)
      ?? { column: c, action: "ignorar", key: null, label: c, unit: "" }));
    setStatusMap(r.sugestao.status_map);
    setEqDefault(r.sugestao.equipamento_padrao);
    setNome(f.name.replace(/\.(csv|txt)$/i, ""));
    setOrigem(/sintetic|simulad|synthetic/i.test(f.name) ? "simulado" : "");
  }

  // ao trocar a coluna de estado, busca os valores distintos e a sugestão de categorias
  useEffect(() => {
    if (!up || !roles.estado) { setStatusMap({}); return; }
    if (roles.estado === up.sugestao.roles.estado) { setStatusMap(up.sugestao.status_map); return; }
    api.statusValues(up.upload_id, roles.estado).then((r) => setStatusMap(r.sugestao)).catch(() => setStatusMap({}));
  }, [roles.estado, up]);

  const columns = up?.info.columns ?? [];
  const roleCols = new Set([roles.timestamp, roles.equipamento, roles.estado].filter(Boolean));
  const canon = meta.data?.variaveis_canonicas ?? {};
  const usedCanon = vars.filter((v) => v.action === "canonica").map((v) => v.key);
  const dupCanon = usedCanon.filter((k, i) => usedCanon.indexOf(k) !== i);
  const mappedCount = vars.filter((v) => v.action !== "ignorar" && !roleCols.has(v.column)).length;

  function setVar(i: number, patch: Partial<VarMap>) {
    setVars((vs) => vs.map((v, j) => {
      if (j !== i) return v;
      const n = { ...v, ...patch };
      if (patch.action === "canonica" && !(n.key && canon[n.key])) {
        const free = Object.keys(canon).find((k) => !usedCanon.includes(k)) ?? Object.keys(canon)[0];
        n.key = free; n.label = canon[free].label; n.unit = canon[free].unit;
      }
      if (patch.action === "personalizada") { n.key = v.column; n.label = v.column; }
      if (patch.key && canon[patch.key] && n.action === "canonica") { n.label = canon[patch.key].label; n.unit = canon[patch.key].unit; }
      return n;
    }));
  }

  // colunas usadas como papel não podem ser variáveis
  function setRole(role: keyof typeof roles, col: string) {
    setRoles((r) => ({ ...r, [role]: col === NONE ? null : col }));
  }

  async function doImport() {
    if (!up || !origem) return;
    const body = {
      upload_id: up.upload_id, nome, descricao, origem, roles,
      variables: vars.filter((v) => !roleCols.has(v.column)),
      status_map: statusMap, equipamento_padrao: eqDefault, timestamp_format: tsFormat || null,
    };
    const r = await importA.run(body);
    if (!r) return;
    await refresh();
    setResult({ id: r.dataset.id, avisos: r.relatorio_importacao.avisos, linhas: r.relatorio_importacao.linhas_importadas, lidas: r.relatorio_importacao.linhas_lidas });
    setUp(null);
  }

  const colOpts = (allowNone: boolean) => [...(allowNone ? [{ value: NONE, label: "— não há —" }] : []),
    ...columns.map((c) => ({ value: c, label: c }))];
  const imported = datasets.filter((d) => !d.is_demo);
  const blockers = [
    !roles.timestamp && "selecione a coluna de data/hora",
    mappedCount === 0 && "mapeie ao menos uma variável numérica",
    dupCanon.length > 0 && `a variável ${dupCanon[0]} está mapeada para mais de uma coluna`,
    !origem && "declare a origem dos dados",
    !nome.trim() && "dê um nome ao dataset",
  ].filter(Boolean) as string[];

  return (
    <div className="space-y-4">
      <PageHeader title="Importação de dados">
        Importe históricos de equipamentos em CSV. Cada arquivo pode ter colunas diferentes: você indica qual coluna corresponde
        a cada papel (data/hora, equipamento, estado) e a cada variável de processo. A origem dos dados é obrigatória e acompanha o
        dataset em todos os painéis e relatórios.
      </PageHeader>

      {result && (
        <Notice>
          <p><b>Importação concluída:</b> {num(result.linhas, 0)} de {num(result.lidas, 0)} linhas importadas.</p>
          {result.avisos.length > 0 && <ul className="list-disc ml-5 mt-1">{result.avisos.map((a, i) => <li key={i}>{a}</li>)}</ul>}
          <Button className="mt-2" variant="primary" onClick={() => { select(result.id); nav("/"); }}>Abrir no painel</Button>
        </Notice>
      )}

      {!up && <DropZone onFile={onFile} busy={uploadA.running} />}
      <ErrorBox>{uploadA.error}</ErrorBox>

      {up && (
        <>
          <Panel title={`Arquivo: ${up.arquivo}`} actions={<Button variant="ghost" onClick={() => setUp(null)}>Trocar arquivo</Button>}>
            <p className="text-[12.5px] text-ink-2 mb-3">
              {num(up.info.rows, 0)} linhas · separador <code className="num">{up.info.delimiter === "\t" ? "TAB" : up.info.delimiter}</code> ·
              decimal <code className="num">{up.info.decimal}</code> · codificação {up.info.encoding}
            </p>
            <div className="overflow-x-auto border border-line-soft max-h-72">
              <table className="tbl text-[12px]">
                <thead><tr>{columns.map((c) => <th key={c} className="whitespace-nowrap">{c}</th>)}</tr></thead>
                <tbody>{up.previa.map((r, i) => <tr key={i}>{columns.map((c) => <td key={c} className="num whitespace-nowrap">{r[c] ?? ""}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Papéis estruturais">
            <div className="grid gap-3 md:grid-cols-3">
              <Field label="Data/hora (obrigatória)" hint="Formatos ISO, dd/mm/aaaa e epoch são reconhecidos.">
                <Select value={roles.timestamp ?? NONE} onChange={(e) => setRole("timestamp", e.target.value)} options={colOpts(true)} />
              </Field>
              <Field label="Equipamento" hint={roles.equipamento ? "Cada valor distinto vira um equipamento." : "Sem coluna: todos os registros vão para um único equipamento."}>
                <Select value={roles.equipamento ?? NONE} onChange={(e) => setRole("equipamento", e.target.value)} options={colOpts(true)} />
              </Field>
              <Field label="Estado operacional" hint="Necessário para MTBF, MTTR e modelos supervisionados de falha.">
                <Select value={roles.estado ?? NONE} onChange={(e) => setRole("estado", e.target.value)} options={colOpts(true)} />
              </Field>
              {!roles.equipamento && (
                <Field label="Nome do equipamento">
                  <input className="field" value={eqDefault} onChange={(e) => setEqDefault(e.target.value)} />
                </Field>
              )}
              <Field label="Formato de data (opcional)" hint="Use se a detecção falhar. Ex.: %d/%m/%Y %H:%M">
                <input className="field num" value={tsFormat} placeholder="automático" onChange={(e) => setTsFormat(e.target.value)} />
              </Field>
            </div>
          </Panel>

          {roles.estado && Object.keys(statusMap).length > 0 && (
            <Panel title="Categorias de estado">
              <p className="text-[12.5px] text-ink-2 mb-3">
                Traduza cada valor do arquivo para uma categoria padrão. "Parado" é standby (disponível); "Falha" inicia um evento de falha;
                "Manutenção" logo após uma falha conta como reparo, e isolada conta como preventiva.
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(statusMap).map(([raw, cat]) => (
                  <label key={raw} className="flex items-center gap-2 text-[13px]">
                    <code className="num bg-well px-1.5 py-0.5 rounded-[2px] min-w-0 truncate flex-1" title={raw}>{raw}</code>
                    <span aria-hidden>→</span>
                    <Select value={cat} onChange={(e) => setStatusMap({ ...statusMap, [raw]: e.target.value })}
                      options={Object.entries(meta.data?.categorias_estado ?? {}).map(([k, v]) => ({ value: k, label: v }))} />
                  </label>
                ))}
              </div>
            </Panel>
          )}

          <Panel title="Variáveis de processo" bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="tbl text-[12.5px]">
                <thead><tr><th>Coluna do arquivo</th><th>Tratamento</th><th>Variável</th><th>Rótulo</th><th>Unidade</th></tr></thead>
                <tbody>
                  {vars.map((v, i) => roleCols.has(v.column) ? null : (
                    <tr key={v.column}>
                      <td className="font-medium whitespace-nowrap">{v.column}
                        {v.confidence !== undefined && v.action === "canonica" && <span className="text-ink-3 font-normal ml-1">(sugestão)</span>}
                        {v.reason && <div className="text-ink-3 font-normal">{v.reason}</div>}
                      </td>
                      <td>
                        <Select value={v.action} onChange={(e) => setVar(i, { action: e.target.value as VarMap["action"] })}
                          options={[{ value: "canonica", label: "Variável padrão" }, { value: "personalizada", label: "Variável personalizada" }, { value: "ignorar", label: "Ignorar" }]} />
                      </td>
                      <td>
                        {v.action === "canonica" ? (
                          <Select value={v.key ?? ""} onChange={(e) => setVar(i, { key: e.target.value })}
                            className={dupCanon.includes(v.key ?? "") ? "border-alarm!" : ""}
                            options={Object.entries(canon).map(([k, c]) => ({ value: k, label: c.label }))} />
                        ) : v.action === "personalizada" ? <span className="text-ink-3">nova variável</span> : <span className="text-ink-3">—</span>}
                      </td>
                      <td><input className="field w-44" disabled={v.action === "ignorar"} value={v.label} onChange={(e) => setVar(i, { label: e.target.value })} /></td>
                      <td><input className="field w-24 num" disabled={v.action === "ignorar"} value={v.unit} onChange={(e) => setVar(i, { unit: e.target.value })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Identificação e origem">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Nome do dataset"><input className="field" value={nome} onChange={(e) => setNome(e.target.value)} maxLength={120} /></Field>
              <Field label="Descrição (opcional)"><input className="field" value={descricao} onChange={(e) => setDescricao(e.target.value)} /></Field>
            </div>
            <fieldset className="mt-4">
              <legend className="text-[12.5px] text-ink-2 font-medium mb-1.5">De onde vêm estes dados? (obrigatório)</legend>
              <div className="flex flex-wrap gap-2">
                {(["medicao_real", "dataset_publico", "simulado"] as DataOrigin[]).map((o) => (
                  <label key={o} className={`flex items-start gap-2 border rounded-[3px] px-3 py-2 cursor-pointer max-w-xs ${origem === o ? "border-frame bg-raised" : "border-line"}`}>
                    <input type="radio" name="origem" className="mt-1" checked={origem === o} onChange={() => setOrigem(o)} />
                    <span>
                      <b className="text-[13px]">{ORIGIN_DATA_LABEL[o]}</b>
                      <span className="block text-[11.5px] text-ink-3">
                        {o === "medicao_real" ? "Coletados de equipamento real (CLP, SCADA, historian)." :
                          o === "dataset_publico" ? "Publicados por terceiros, ex.: Kaggle, NASA C-MAPSS, UCI AI4I." :
                            "Gerados por simulação. Serão marcados como simulação em toda a plataforma."}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button variant="primary" disabled={blockers.length > 0 || importA.running} onClick={doImport}>
                {importA.running ? "Importando…" : "Importar dataset"}
              </Button>
              {blockers.length > 0 && <span className="text-[12.5px] text-ink-2">Para importar: {blockers.join("; ")}.</span>}
            </div>
            <div className="mt-3"><ErrorBox>{importA.error}</ErrorBox></div>
          </Panel>
        </>
      )}

      <Panel title="Datasets disponíveis" bodyClass="p-0">
        {datasets.length === 0 ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="tbl text-[12.5px]">
              <thead><tr><th>Nome</th><th>Origem</th><th>Período</th><th>Equipamentos</th><th>Linhas</th><th>Estado</th><th /></tr></thead>
              <tbody>
                {datasets.map((d) => (
                  <tr key={d.id}>
                    <td className="font-medium">{d.name}{d.is_demo && <span className="text-ink-3 font-normal"> (demonstração)</span>}</td>
                    <td className={d.is_synthetic ? "text-[#7a4b00] font-medium" : ""}>{ORIGIN_DATA_LABEL[d.data_origin]}</td>
                    <td className="num whitespace-nowrap">{dt(d.start, false)} – {dt(d.end, false)}</td>
                    <td>{d.equipment.join(", ")}</td>
                    <td className="num">{num(d.rows, 0)}</td>
                    <td>{d.has_status ? "mapeado" : <span className="text-ink-3">ausente</span>}</td>
                    <td className="text-right">
                      {!d.is_demo && (
                        <Button variant="danger" disabled={deleteA.running}
                          onClick={async () => { if (confirm(`Remover o dataset "${d.name}"? Esta ação não pode ser desfeita.`)) { await deleteA.run(d.id); await refresh(); } }}>
                          Remover
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {imported.length === 0 && (
          <p className="px-4 py-3 text-[12.5px] text-ink-3 border-t border-line-soft">
            Ainda não há datasets importados. A pasta <code>examples/</code> do repositório tem três CSVs sintéticos com convenções diferentes de colunas para testar o mapeamento.
          </p>
        )}
        <div className="px-4 pb-3"><ErrorBox>{deleteA.error}</ErrorBox></div>
      </Panel>
    </div>
  );
}
