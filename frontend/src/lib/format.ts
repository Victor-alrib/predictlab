const nf = (d: number) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });

export function num(v: number | null | undefined, digits = 2, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = nf(digits).format(v);
  return unit ? `${s} ${unit}` : s;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${nf(digits).format(v * 100)}%`;
}

export function dt(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", withTime
    ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function hours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "—";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${nf(1).format(h)} h`;
  return `${nf(1).format(h / 24)} dias`;
}

/** ISO local "aaaa-mm-ddThh:mm" para inputs datetime-local. */
export function toLocalInput(iso: string): string {
  return iso.slice(0, 16);
}

export const ORIGIN_LABEL = {
  limite: "Limite configurado",
  estatistica: "Anomalia estatística",
  modelo: "Previsão de modelo",
} as const;

export const ORIGIN_HINT = {
  limite: "Regra determinística definida por você: o valor saiu da faixa configurada.",
  estatistica: "O comportamento se afastou do histórico recente do próprio equipamento. Não implica falha.",
  modelo: "Estimativa de um modelo treinado. Probabilística e sujeita a erro.",
} as const;

export const SEVERITY_LABEL = { baixa: "Baixa", media: "Média", alta: "Alta" } as const;

export const STATE_LABEL: Record<string, string> = {
  operando: "Operando", parado: "Parado / standby", falha: "Falha", manutencao: "Manutenção", desconhecido: "Desconhecido",
};

export const ORIGIN_DATA_LABEL = {
  medicao_real: "Medição real",
  dataset_publico: "Dataset público",
  simulado: "Simulação",
} as const;

/** Timestamp local sem fuso ("aaaa-mm-ddThh:mm:ss"), no mesmo padrão da API. */
export function localIso(ms: number): string {
  const x = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}T${p(x.getHours())}:${p(x.getMinutes())}:${p(x.getSeconds())}`;
}
