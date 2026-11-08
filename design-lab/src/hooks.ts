import { useEffect, useState } from "react";
import type { DependencyList } from "react";
export function useData<T>(
  loader: () => Promise<T>,
  deps: DependencyList = [],
) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setData(undefined);
    setError(false);
    loader()
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, deps);
  return { data, error };
}
