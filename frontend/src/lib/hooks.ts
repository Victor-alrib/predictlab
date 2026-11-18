import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** Executa uma chamada assíncrona sempre que as dependências mudam. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => { if (my === seq.current) setData(d); })
      .catch((e: Error) => { if (my === seq.current) { setError(e.message); setData(null); } })
      .finally(() => { if (my === seq.current) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Ação disparada pelo usuário (botão), com estado de execução e erro. */
export function useAction<A extends unknown[], T>(fn: (...a: A) => Promise<T>) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (...a: A): Promise<T | undefined> => {
    setRunning(true);
    setError(null);
    try {
      return await fn(...a);
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setRunning(false);
    }
  }, [fn]);
  return { run, running, error, setError };
}
