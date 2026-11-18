import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useDataset } from "../lib/dataset";
import { dt, ORIGIN_DATA_LABEL } from "../lib/format";
import { ErrorBox } from "./ui";

const NAV = [
  { to: "/", label: "Painel da planta", icon: "M3 13h4v8H3zM10 3h4v18h-4zM17 9h4v12h-4z" },
  { to: "/importacao", label: "Importação de dados", icon: "M12 3v12m0 0-4-4m4 4 4-4M4 17v3h16v-3" },
  { to: "/analise", label: "Análise temporal", icon: "M3 17l5-6 4 3 5-8 4 5" },
  { to: "/manutencao", label: "Indicadores de manutenção", icon: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" },
  { to: "/modelos", label: "Machine Learning", icon: "M5 5h4v4H5zM15 5h4v4h-4zM10 15h4v4h-4zM7 9l4 6m6-6-4 6" },
  { to: "/alertas", label: "Alertas", icon: "M12 3 2 20h20zM12 10v4m0 3v.5" },
  { to: "/relatorios", label: "Relatórios", icon: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7" },
  { to: "/sobre", label: "Metodologia", icon: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6m0-9.5V8" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden className="shrink-0">
      <path d={d} />
    </svg>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-4 h-14 border-b border-frame-2">
      <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
        <rect width="32" height="32" rx="5" fill="#3a4b5b" />
        <path d="M5 21h5l3-9 4 13 3-8h7" fill="none" stroke="#f2b134" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="font-semibold text-[15px] text-white">PredictLab</div>
        <div className="text-[11px] text-frame-ink/70">Monitoramento e manutenção preditiva</div>
      </div>
    </div>
  );
}

function SimulationBanner({ synthetic }: { synthetic: boolean }) {
  if (!synthetic) return null;
  return (
    <div role="status" className="flex items-stretch border-b border-ink">
      <div className="hazard w-6 sm:w-10 shrink-0" aria-hidden />
      <div className="flex-1 bg-hazard text-ink px-3 py-1.5 text-[13px] flex flex-wrap gap-x-3 items-center">
        <strong className="font-semibold">Simulação</strong>
        <span>Os dados deste ambiente são sintéticos. Nenhum valor exibido é medição de equipamento real.</span>
      </div>
      <div className="hazard w-6 sm:w-10 shrink-0" aria-hidden />
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { datasets, current, select, error } = useDataset();
  const [open, setOpen] = useState(false);
  const loc = useLocation();

  const nav = (
    <nav aria-label="Módulos" className="py-2">
      {NAV.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.to === "/"}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 mx-2 px-3 py-2 rounded-[3px] text-[13.5px] ${isActive
              ? "bg-frame-2 text-white shadow-[inset_3px_0_0_#f2b134]" : "text-frame-ink/85 hover:bg-frame-2/60 hover:text-white"}`}
        >
          <Icon d={n.icon} />
          {n.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-full flex">
      {/* trilho lateral (desktop) */}
      <aside className="hidden lg:flex flex-col w-60 shrink-0 bg-frame text-frame-ink sticky top-0 h-screen">
        <Brand />
        {nav}
        <div className="mt-auto px-4 py-3 text-[11.5px] text-frame-ink/60 border-t border-frame-2">
          Plataforma educacional e experimental. Não utilizar para decisões operacionais reais.
        </div>
      </aside>

      {/* gaveta (mobile) */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 flex">
          <div className="w-64 bg-frame text-frame-ink h-full overflow-y-auto"><Brand />{nav}</div>
          <button aria-label="Fechar menu" className="flex-1 bg-ink/40" onClick={() => setOpen(false)} />
        </div>
      )}

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 bg-panel border-b border-line">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 min-h-14">
            <button className="lg:hidden p-1.5 -ml-1 rounded-[3px] hover:bg-raised cursor-pointer" aria-label="Abrir menu" onClick={() => setOpen(true)}>
              <Icon d="M4 6h16M4 12h16M4 18h16" />
            </button>
            <label className="flex items-center gap-2 min-w-0">
              <span className="text-[12.5px] text-ink-2 whitespace-nowrap">Dataset</span>
              <select className="field max-w-[260px] sm:max-w-[360px]" value={current?.id ?? ""} onChange={(e) => select(e.target.value)}>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}{d.is_synthetic ? " (simulado)" : ""}</option>
                ))}
              </select>
            </label>
            {current && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-2">
                <span>
                  Origem:{" "}
                  <b className={current.is_synthetic ? "text-[#7a4b00]" : "text-ink"}>{ORIGIN_DATA_LABEL[current.data_origin]}</b>
                </span>
                <span className="hidden md:inline">Período: <span className="num text-ink">{dt(current.start, false)} – {dt(current.end, false)}</span></span>
                <span className="hidden xl:inline">{current.equipment.length} equipamento(s), {current.variables.length} variável(is)</span>
              </div>
            )}
          </div>
          <SimulationBanner synthetic={!!current?.is_synthetic} />
        </header>
        <main key={loc.pathname} className="flex-1 p-4 md:p-6 max-w-[1500px] w-full mx-auto">
          {error && <div className="mb-4"><ErrorBox>{error}</ErrorBox></div>}
          {children}
        </main>
      </div>
    </div>
  );
}
