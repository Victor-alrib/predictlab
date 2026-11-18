import type { Alert, DatasetMeta } from "../api/client";
import { varLabel } from "../lib/dataset";
import { dt, hours } from "../lib/format";
import { Empty, OriginBadge, SeverityBadge } from "./ui";

export default function AlertTable({ alerts, ds, compact = false, onSelect }:
  { alerts: Alert[]; ds: DatasetMeta | null; compact?: boolean; onSelect?: (a: Alert) => void }) {
  if (!alerts.length) return <Empty title="Nenhum alerta nesta seleção" />;
  return (
    <div className="overflow-x-auto">
      <table className="tbl text-[12.5px]">
        <thead>
          <tr>
            <th>Origem</th>
            <th>Sev.</th>
            <th>Equip.</th>
            {!compact && <th>Variável</th>}
            <th>Início</th>
            <th>Duração</th>
            <th className="min-w-[280px]">Descrição</th>
            {!compact && <th>Método</th>}
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id} onClick={onSelect ? () => onSelect(a) : undefined} className={onSelect ? "cursor-pointer" : ""}>
              <td><OriginBadge origem={a.origem} short /></td>
              <td><SeverityBadge s={a.severidade} /></td>
              <td className="font-medium whitespace-nowrap">{a.equipamento}</td>
              {!compact && <td className="whitespace-nowrap">{varLabel(ds, a.variavel)}</td>}
              <td className="num whitespace-nowrap">{dt(a.inicio)}</td>
              <td className="num whitespace-nowrap">{hours(a.duracao_h)}</td>
              <td>{a.mensagem}</td>
              {!compact && <td className="text-ink-3 whitespace-nowrap">{a.metodo}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
