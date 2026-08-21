"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

export type ResourceParams = Record<string, string> & { page: string; page_size: string; q: string };

function readParams(defaults: ResourceParams) {
  if (typeof window === "undefined") return defaults;
  const url = new URL(window.location.href);
  return Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, url.searchParams.get(key) ?? value])) as ResourceParams;
}

export function useResourceParams(extraDefaults: Record<string, string> = {}) {
  const pathname = usePathname();
  const defaultsKey = JSON.stringify(extraDefaults);
  const defaults = useMemo(() => ({ page: "1", page_size: "25", q: "", ...JSON.parse(defaultsKey) } as ResourceParams), [defaultsKey]);
  const [params, setParams] = useState<ResourceParams>(defaults);

  useEffect(() => {
    const sync = () => setParams(readParams(defaults));
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [defaults, pathname]);

  const update = useCallback((changes: Record<string, string>, resetPage = true) => {
    setParams((current) => {
      const next = { ...current, ...changes, ...(resetPage ? { page: "1" } : {}) };
      const query = new URLSearchParams();
      Object.entries(next).forEach(([key, value]) => {
        const defaultValue = defaults[key];
        if (value && value !== defaultValue) query.set(key, value);
      });
      const suffix = query.toString();
      window.history.replaceState(null, "", suffix ? `${pathname}?${suffix}` : pathname);
      return next;
    });
  }, [defaults, pathname]);

  return { params, update };
}
