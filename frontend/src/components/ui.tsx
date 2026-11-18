import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import type { Indicator, Origin, Severity } from "../api/client";
import { num, ORIGIN_HINT, ORIGIN_LABEL, SEVERITY_LABEL, STATE_LABEL } from "../lib/format";

export function Panel({ title, actions, children, className = "", bodyClass = "p-4" }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={`bg-panel border border-line rounded-[4px] ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b border-line-soft bg-raised/60">
          <h2 className="text-[13.5px] font-semibold text-ink">{title}</h2>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4">
      <h1 className="text-[22px] font-semibold tracking-tight leading-tight">{title}</h1>
      {children && <p className="text-ink-2 mt-1 max-w-[78ch]">{children}</p>}
    </div>
  );
}

export function Button({ variant = "default", className = "", ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "ghost" | "danger" }) {
  const styles = {
    default: "bg-raised border-line text-ink hover:bg-white",
    primary: "bg-frame border-frame text-frame-ink hover:bg-frame-2",
    ghost: "bg-transparent border-transparent text-ink-2 hover:bg-raised",
    danger: "bg-raised border-alarm/60 text-alarm hover:bg-alarm-soft",
  }[variant];
  return (
    <button
      {...p}
      className={`inline-flex items-center justify-center gap-1.5 min-h-8 px-3 border rounded-[3px] text-[13px] font-medium
        disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer ${styles} ${className}`}
    />
  );
}

export function Field({ label, hint, children, className = "" }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-[12.5px] ${className}`}>
      <span className="text-ink-2 font-medium">{label}</span>
      {children}
      {hint && <span className="text-ink-3 text-[11.5px]">{hint}</span>}
    </label>
  );
}

export function Select({ options, className = "", ...p }:
  SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string }[] }) {
  return (
    <select {...p} className={`field ${className}`}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <div role="alert" className="border border-alarm/50 bg-alarm-soft text-[#7d0a1d] rounded-[3px] px-3 py-2 text-[13px]">
      {children}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const cls = tone === "warn" ? "border-warn/60 bg-warn-soft text-[#6b4100]" : "border-line bg-raised text-ink-2";
  return <div className={`border rounded-[3px] px-3 py-2 text-[13px] ${cls}`}>{children}</div>;
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-ink-3 text-sm py-6 justify-center" aria-live="polite">
      <span className="inline-block size-3 rounded-full border-2 border-ink-3 border-t-transparent animate-spin motion-reduce:animate-none" />
      {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="text-center py-10 px-4 text-ink-2">
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 text-[13px] max-w-[60ch] mx-auto">{children}</div>}
    </div>
  );
}

/** Indicador de manutenção que nunca mostra número quando os dados são insuficientes. */
export function IndicatorValue({ ind, digits = 1, big = false }: { ind?: Indicator | null; digits?: number; big?: boolean }) {
  if (!ind) return <span className="text-ink-3">—</span>;
  if (ind.status !== "ok" || ind.valor === null)
    return (
      <span className={`text-ink-3 ${big ? "text-[15px]" : "text-[12.5px]"} italic`} title={ind.motivo ?? undefined}>
        dados insuficientes
      </span>
    );
  return (
    <span className={`num ${big ? "text-[26px] leading-none font-semibold" : ""}`}>
      {num(ind.valor, digits)}<span className={`text-ink-3 ${big ? "text-[13px] ml-1 font-normal" : "ml-0.5"}`}>{ind.unidade}</span>
    </span>
  );
}

export function Stat({ label, children, note }: { label: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="bg-raised border border-line-soft rounded-[3px] px-3 py-2.5 min-w-0">
      <div className="text-[12px] text-ink-2">{label}</div>
      <div className="mt-1">{children}</div>
      {note && <div className="text-[11.5px] text-ink-3 mt-1">{note}</div>}
    </div>
  );
}

// --- marcadores de origem: forma + cor (nunca só cor) ------------------------

export function OriginIcon({ origem, size = 12 }: { origem: Origin; size?: number }) {
  const c = { limite: "var(--color-orig-limite)", estatistica: "var(--color-orig-estat)", modelo: "var(--color-orig-modelo)" }[origem];
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden className="shrink-0">
      {origem === "limite" && <path d="M6 1 11 10.5H1Z" fill={c} />}
      {origem === "estatistica" && <path d="M6 .8 11.2 6 6 11.2.8 6Z" fill={c} />}
      {origem === "modelo" && <><circle cx="6" cy="6" r="5" fill="none" stroke={c} strokeWidth="2" /><circle cx="6" cy="6" r="2" fill={c} /></>}
    </svg>
  );
}

export function OriginBadge({ origem, short = false }: { origem: Origin; short?: boolean }) {
  const c = { limite: "text-orig-limite border-orig-limite/50", estatistica: "text-orig-estat border-orig-estat/50",
    modelo: "text-orig-modelo border-orig-modelo/50" }[origem];
  return (
    <span title={ORIGIN_HINT[origem]} className={`inline-flex items-center gap-1.5 border rounded-[3px] px-1.5 py-0.5 text-[11.5px] font-medium bg-raised whitespace-nowrap ${c}`}>
      <OriginIcon origem={origem} />
      {short ? { limite: "Limite", estatistica: "Estatística", modelo: "Modelo" }[origem] : ORIGIN_LABEL[origem]}
    </span>
  );
}

export function SeverityBadge({ s }: { s: Severity }) {
  const c = { alta: "bg-alarm text-white", media: "bg-warn text-white", baixa: "bg-well text-ink" }[s];
  return <span className={`inline-block rounded-[3px] px-1.5 py-0.5 text-[11.5px] font-semibold ${c}`}>{SEVERITY_LABEL[s]}</span>;
}

export function StateBadge({ estado }: { estado: string | null }) {
  if (!estado) return <span className="text-ink-3">—</span>;
  const c: Record<string, string> = {
    falha: "bg-alarm text-white", manutencao: "bg-maint text-white", parado: "bg-well text-ink-2",
    operando: "bg-raised text-ink border border-line", desconhecido: "bg-well text-ink-3",
  };
  return <span className={`inline-block rounded-[3px] px-1.5 py-0.5 text-[11.5px] font-medium ${c[estado] ?? c.desconhecido}`}>{STATE_LABEL[estado] ?? estado}</span>;
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: string }[] }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-0 border-b border-line mb-4">
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          aria-selected={value === it.value}
          onClick={() => onChange(it.value)}
          className={`px-3.5 py-2 text-[13px] -mb-px border-b-2 cursor-pointer ${value === it.value
            ? "border-frame text-ink font-semibold" : "border-transparent text-ink-2 hover:text-ink"}`}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
