// Cliente HTTP e tipos da API do PredictLab.

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "Não foi possível conectar à API. Verifique se o backend está rodando na porta 8000.");
  }
  if (!res.ok) {
    let msg = `Erro ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail))
        msg = body.detail.map((d: { msg: string; loc?: string[] }) => `${d.loc?.slice(1).join(".") ?? ""}: ${d.msg}`).join("; ");
    } catch { /* corpo não-JSON */ }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

const qs = (p: Record<string, string | number | boolean | undefined | null>) => {
  const u = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && u.set(k, String(v)));
  const s = u.toString();
  return s ? `?${s}` : "";
};

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// ---------------------------------------------------------------- tipos

export type DataOrigin = "medicao_real" | "dataset_publico" | "simulado";
export type Origin = "limite" | "estatistica" | "modelo";
export type Severity = "baixa" | "media" | "alta";

export interface Variable { key: string; label: string; unit: string; canonical?: boolean; source_column?: string }

export interface DatasetMeta {
  id: string; name: string; description: string; data_origin: DataOrigin; is_synthetic: boolean; is_demo: boolean;
  created_at: string; rows: number; equipment: string[]; variables: Variable[]; has_status: boolean;
  start: string; end: string; provenance: Record<string, unknown>;
}

export interface Indicator { valor: number | null; unidade: string; status: "ok" | "insuficiente"; motivo: string | null }

export interface Alert {
  id: string; origem: Origin; metodo: string; equipamento: string; variavel: string | null;
  inicio: string; fim: string; duracao_h: number; severidade: Severity; valor: number | null;
  referencia: number | null; mensagem: string; score?: number; run_id?: string;
}

export interface AlertSummary {
  total: number; por_origem: Record<Origin, number>; por_severidade: Record<Severity, number>;
  por_equipamento: Record<string, Record<Origin, number>>;
}

export interface EquipmentCard {
  equipamento: string; descricao?: string | null; estado_operacional: string | null;
  monitoramento: { codigo: string; rotulo: string }; ultimo_registro: string; ultima_leitura_valida: string | null;
  valores: { variavel: string; rotulo: string; unidade: string; valor: number | null;
    limite: { min?: number; max?: number } | null; fora_do_limite: "max" | "min" | null }[];
  alertas_ativos: number; alertas_ativos_detalhe: Pick<Alert, "origem" | "severidade" | "mensagem" | "variavel">[];
  alertas_total: number; n_falhas: number; disponibilidade_observada?: Indicator;
  distribuicao_estados_pct: Record<string, number>;
  sparkline: { timestamps: string[] } & Record<string, (number | null)[] | string[]>;
}

export interface Dashboard {
  dataset: DatasetMeta; referencia_temporal: string; reproducao_historica: boolean;
  kpis: { equipamentos: number; em_alarme: number; alertas_ultimos_7d: number; alertas_total: number;
    falhas_registradas: number; disponibilidade_observada: Indicator | null; mtbf_frota: Indicator | null; possui_estado: boolean };
  equipamentos: EquipmentCard[]; alarmes_recentes: Alert[]; resumo_alertas: AlertSummary;
}

export interface SeriesResp {
  equipamento: string; timestamps: string[]; series: Record<string, (number | null)[]>;
  pontos_originais: number; reamostrado: boolean; estados?: { estado: string; inicio: string; fim: string }[];
}

export interface Failure { inicio: string; fim: string; duracao_h: number; duracao_falha_h: number; duracao_reparo_h: number; truncada: boolean }
export interface MaintEquipment {
  equipamento: string; suficiente: boolean; motivos: string[]; n_falhas: number; n_falhas_completas: number;
  tempos_h: Record<string, number>; indicadores: Record<string, Indicator>;
  dispersao?: { tbf_h: number[]; tbf_desvio_h: number | null; ttr_desvio_h: number | null };
  falhas: Failure[]; preventivas: { inicio: string; duracao_h: number }[];
  frequencia_semanal: { semana: string; falhas: number }[];
}
export interface MaintResp {
  parametros: { min_falhas: number; min_dias: number }; possui_estado: boolean;
  equipamentos: MaintEquipment[]; frota: { n_falhas: number; indicadores: Record<string, Indicator> } | null;
}

export interface SampleMetrics {
  precisao: number | null; recall: number | null; f1: number | null; roc_auc: number | null; pr_auc: number | null;
  prevalencia: number | null; matriz_confusao: { vn: number; fp: number; fn: number; vp: number };
}
export interface EventMetrics {
  falhas_no_teste: number; falhas_antecipadas: number; taxa_deteccao_eventos: number | null;
  antecedencia_media_h: number | null; alarmes_falsos: number; alarmes_falsos_por_30d: number | null; horizonte_h: number;
  detalhes: { evento: string; equipamento: string; inicio_falha: string; antecipada: boolean; antecedencia_h: number | null }[];
}
export interface ForecastResult {
  modelo: string; nome: string; erro?: string;
  metricas_holdout?: { mae: number; rmse: number; wape_pct: number | null; vies: number; cobertura_ic95: number | null; ganho_vs_base_pct?: number | null };
  holdout?: { previsto: number[]; inferior: number[]; superior: number[] };
  futuro?: { previsto: number[]; inferior: number[]; superior: number[] };
}
export interface Run {
  id: string; created_at: string; tipo: "classificacao" | "anomalia" | "previsao"; modelo: string; modelo_nome: string;
  dataset_id: string; dataset_sintetico: boolean; equipamentos: string[]; variavel?: string;
  parametros: Record<string, unknown>; duracao_s: number; avisos: string[];
  metricas?: { teste?: SampleMetrics | null; treino?: SampleMetrics; eventos?: EventMetrics | null;
    cv?: { dobras: { dobra: number; f1: number | null; pr_auc?: number | null; observacao?: string }[]; f1_media: number | null; f1_desvio: number | null };
    anomalia?: { taxa_anomalias_teste: number | null } };
  divisao?: Record<string, number | string>;
  atributos?: { n: number; lista: string[] };
  curva_pr?: { precisao: number[]; recall: number[]; limiar: number[] } | null;
  importancias?: { atributo: string; importancia: number }[];
  series?: Record<string, { timestamps: string[]; score: (number | null)[]; rotulo: (number | null)[] }>;
  limiar_exibicao?: number | null;
  // previsão
  rotulo?: string; unidade?: string; historico?: { timestamps: string[]; valor: (number | null)[] };
  holdout_timestamps?: string[]; holdout_real?: (number | null)[]; futuro_timestamps?: string[];
  resultados?: ForecastResult[]; melhor_modelo?: string | null;
}

export interface Threshold { min?: number | null; max?: number | null; severidade: Severity; duracao_min_min?: number }

export interface UploadResp {
  upload_id: string; arquivo: string;
  info: { encoding: string; delimiter: string; decimal: string; rows: number; columns: string[] };
  previa: Record<string, string | null>[];
  sugestao: {
    roles: { timestamp: string | null; equipamento: string | null; estado: string | null };
    variables: VarMap[]; status_values: string[]; status_map: Record<string, string>; equipamento_padrao: string;
  };
}
export interface VarMap { column: string; action: "canonica" | "personalizada" | "ignorar"; key: string | null;
  label: string; unit: string; confidence?: number; reason?: string }

export interface Meta {
  variaveis_canonicas: Record<string, { label: string; unit: string }>;
  categorias_estado: Record<string, string>;
  origens_dado: Record<DataOrigin, string>;
}

// ---------------------------------------------------------------- endpoints

export const api = {
  meta: () => request<Meta>("/api/meta"),
  datasets: () => request<DatasetMeta[]>("/api/datasets"),
  deleteDataset: (id: string) => request<{ ok: boolean }>(`/api/datasets/${id}`, { method: "DELETE" }),
  quality: (id: string) => request<{ equipamentos: Record<string, unknown>[] }>(`/api/datasets/${id}/quality`),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<UploadResp>("/api/datasets/upload", { method: "POST", body: fd });
  },
  statusValues: (uploadId: string, coluna: string) =>
    request<{ valores: string[]; sugestao: Record<string, string> }>(`/api/datasets/upload/${uploadId}/status-values${qs({ coluna })}`),
  importDataset: (body: unknown) =>
    request<{ dataset: DatasetMeta; relatorio_importacao: { avisos: string[]; linhas_importadas: number; linhas_lidas: number }; qualidade: unknown }>(
      "/api/datasets/import", json("POST", body)),
  series: (id: string, equipamento: string, variaveis?: string[], max_points = 2500, inicio?: string, fim?: string) =>
    request<SeriesResp>(`/api/datasets/${id}/series${qs({ equipamento, variaveis: variaveis?.join(","), max_points, inicio, fim })}`),
  dashboard: (id: string, referencia?: string) => request<Dashboard>(`/api/dashboard/${id}${qs({ referencia })}`),
  trend: (id: string, p: { equipamento: string; variavel: string; janelas?: string; apenas_operando?: boolean }) =>
    request<TrendResp>(`/api/analysis/${id}/trend${qs(p)}`),
  seasonality: (id: string, p: { equipamento: string; variavel: string }) =>
    request<SeasonResp>(`/api/analysis/${id}/seasonality${qs(p)}`),
  profile: (id: string, p: { equipamento: string; variavel: string }) =>
    request<ProfileResp>(`/api/analysis/${id}/profile${qs(p)}`),
  compare: (id: string, body: unknown) => request<CompareResp>(`/api/analysis/${id}/compare`, json("POST", body)),
  maintenance: (id: string, p: { equipamento?: string; min_falhas?: number; min_dias?: number }) =>
    request<MaintResp>(`/api/maintenance/${id}${qs(p)}`),
  models: () => request<{ classificacao_anomalia: Record<string, { nome: string; descricao: string; tipo: string; disponivel: boolean }>; previsao: Record<string, string> }>("/api/ml/models"),
  classify: (id: string, body: unknown) => request<Run>(`/api/ml/${id}/classification`, json("POST", body)),
  anomaly: (id: string, body: unknown) => request<Run>(`/api/ml/${id}/anomaly`, json("POST", body)),
  forecast: (id: string, body: unknown) => request<Run>(`/api/ml/${id}/forecast`, json("POST", body)),
  runs: (id: string) => request<Run[]>(`/api/ml/runs${qs({ dataset_id: id })}`),
  run: (runId: string) => request<Run>(`/api/ml/runs/${runId}`),
  deleteRun: (runId: string) => request<{ ok: boolean }>(`/api/ml/runs/${runId}`, { method: "DELETE" }),
  alerts: (id: string, p: { equipamento?: string; origens?: string; severidade?: string; k?: number }) =>
    request<{ resumo: AlertSummary; alertas: Alert[]; origens: Record<Origin, string> }>(`/api/alerts/${id}${qs(p)}`),
  thresholds: (id: string) => request<{ limites: Record<string, Record<string, Threshold>>; efetivos: Record<string, Record<string, Threshold>> }>(`/api/alerts/${id}/thresholds`),
  setThreshold: (id: string, eq: string, v: string, t: Threshold) =>
    request(`/api/alerts/${id}/thresholds/${encodeURIComponent(eq)}/${encodeURIComponent(v)}`, json("PUT", t)),
  deleteThreshold: (id: string, eq: string, v: string) =>
    request(`/api/alerts/${id}/thresholds/${encodeURIComponent(eq)}/${encodeURIComponent(v)}`, { method: "DELETE" }),
  suggestThreshold: (id: string, equipamento: string, variavel: string) =>
    request<{ min: number; max: number; base: string; aviso: string }>(`/api/alerts/${id}/thresholds/suggest${qs({ equipamento, variavel })}`),
  report: (id: string, body: unknown) => request<string>(`/api/reports/${id}`, json("POST", body)),
};

export interface TrendResp {
  equipamento: string; variavel: string; rotulo: string; unidade: string; frequencia: string;
  timestamps: string[]; valor: (number | null)[]; medias_moveis: Record<string, (number | null)[]>; linha_tendencia: (number | null)[] | null;
  estatisticas: { inclinacao_por_dia: number | null; r2: number | null; p_valor_regressao: number | null; kendall_tau: number | null;
    kendall_p: number | null; direcao: string; media: number | null; desvio: number | null; minimo: number | null; maximo: number | null; n: number };
}
export interface SeasonResp {
  acf: { lags_h: number[]; valores: number[]; limiar_significancia: number };
  candidatos: { periodo: string; horas: number; acf: number }[];
  periodo_detectado: { periodo: string; horas: number; acf: number } | null;
  decomposicao: { timestamps: string[]; observado: number[]; tendencia: number[]; sazonal: number[]; residuo: number[] } | null;
  forca_sazonal: number | null; forca_tendencia: number | null; interpolacao: string;
}
export interface ProfileResp {
  perfil_horario: { hora: number[]; media: number[]; desvio: number[]; p10: number[]; p90: number[] };
  perfil_semanal: { dia: string[]; media: number[] };
  histograma: { contagem: number[]; bordas: number[] };
  diario: { data: string[]; mean: number[]; min: number[]; max: number[] };
  por_estado: Record<string, { media: number | null; n: number }> | null;
  quantis: Record<string, number | null>;
}
export interface PeriodStats { inicio: string; fim: string; n: number; media: number; desvio: number; minimo: number; maximo: number; mediana: number; p95: number }
export interface CompareResp {
  periodo_a: PeriodStats; periodo_b: PeriodStats; diferenca_media: number; diferenca_pct: number | null; cohen_d: number | null;
  mann_whitney_p: number; significativo_5pct: boolean; interpretacao: string;
  perfil_horario: { hora: number[]; a: (number | null)[]; b: (number | null)[] };
  histograma: { bordas: number[]; a: number[]; b: number[] };
}
