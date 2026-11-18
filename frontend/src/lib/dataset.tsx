import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type DatasetMeta } from "../api/client";

interface Ctx {
  datasets: DatasetMeta[];
  current: DatasetMeta | null;
  select: (id: string) => void;
  refresh: () => Promise<void>;
  error: string | null;
  loading: boolean;
}

const DatasetContext = createContext<Ctx | null>(null);
const KEY = "predictlab.dataset";

function readKey(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function DatasetProvider({ children }: { children: ReactNode }) {
  const [datasets, setDatasets] = useState<DatasetMeta[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(readKey);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const list = await api.datasets();
      setDatasets(list);
      setError(null);
      setCurrentId((id) => (id && list.some((d) => d.id === id) ? id : list[0]?.id ?? null));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const select = useCallback((id: string) => {
    setCurrentId(id);
    try { localStorage.setItem(KEY, id); } catch { /* armazenamento indisponível */ }
  }, []);

  const value = useMemo(() => ({
    datasets, current: datasets.find((d) => d.id === currentId) ?? null, select, refresh, error, loading,
  }), [datasets, currentId, select, refresh, error, loading]);

  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}

export function useDataset(): Ctx {
  const c = useContext(DatasetContext);
  if (!c) throw new Error("useDataset fora do DatasetProvider");
  return c;
}

export function varLabel(ds: DatasetMeta | null, key: string | null | undefined): string {
  if (!key) return "—";
  const v = ds?.variables.find((x) => x.key === key);
  return v ? v.label : key;
}

export function varUnit(ds: DatasetMeta | null, key: string | null | undefined): string {
  return ds?.variables.find((x) => x.key === key)?.unit ?? "";
}
