import { useEffect, useMemo } from "react";
import { api, type DatasetMeta } from "../api/client";
import { useAsync } from "../lib/hooks";
import { Field, Select } from "./ui";

/** Variáveis efetivamente presentes em cada equipamento (datasets heterogêneos). */
export function useEquipmentVars(ds: DatasetMeta | null): Record<string, string[]> {
  const q = useAsync(() => api.quality(ds!.id), [ds?.id], !!ds);
  return useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const e of (q.data?.equipamentos ?? []) as { equipamento: string; faltantes_pct: Record<string, number | null> }[]) {
      out[e.equipamento] = Object.entries(e.faltantes_pct).filter(([, v]) => v !== null && v < 100).map(([k]) => k);
    }
    return out;
  }, [q.data]);
}

interface Props {
  ds: DatasetMeta;
  equipamento: string;
  variavel?: string;
  onEquipamento: (e: string) => void;
  onVariavel?: (v: string) => void;
  allowAll?: boolean;
}

export function EquipVarPicker({ ds, equipamento, variavel, onEquipamento, onVariavel, allowAll }: Props) {
  const vars = useEquipmentVars(ds);
  const available = equipamento === "*" ? ds.variables.map((v) => v.key) : vars[equipamento] ?? ds.variables.map((v) => v.key);
  useEffect(() => {
    if (onVariavel && variavel && available.length && !available.includes(variavel)) onVariavel(available[0]);
  }, [available.join(","), variavel]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Field label="Equipamento">
        <Select
          value={equipamento}
          onChange={(e) => onEquipamento(e.target.value)}
          options={[...(allowAll ? [{ value: "*", label: "Todos os equipamentos" }] : []),
            ...ds.equipment.map((e) => ({ value: e, label: e }))]}
        />
      </Field>
      {onVariavel && (
        <Field label="Variável">
          <Select
            value={variavel}
            onChange={(e) => onVariavel(e.target.value)}
            options={ds.variables.filter((v) => available.includes(v.key))
              .map((v) => ({ value: v.key, label: v.unit ? `${v.label} (${v.unit})` : v.label }))}
          />
        </Field>
      )}
    </>
  );
}
