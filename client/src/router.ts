import { useEffect, useState } from "react";

// Minimal hash-based, path-style router — no dependency, consistent with the project's
// minimal-deps philosophy. Paths look like "/", "/login", "/dashboard/assets", and may carry
// a query string: "/login?registered=1". Swap for react-router if server routes are needed.

function rawHash(): string {
  return window.location.hash.replace(/^#/, "");
}

export function currentPath(): string {
  const [p] = rawHash().split("?");
  if (p === "" || p === "/") return "/";
  return p.replace(/\/+$/, "") || "/";
}

export function currentQuery(): URLSearchParams {
  const h = rawHash();
  const i = h.indexOf("?");
  return new URLSearchParams(i >= 0 ? h.slice(i + 1) : "");
}

export function navigate(path: string): void {
  const target = `#${path}`;
  if (window.location.hash !== target) {
    window.location.hash = target;
  }
  // Scroll to top on route change so a new page doesn't start mid-scroll.
  window.scrollTo({ top: 0 });
}

export function useRoutePath(): string {
  const [path, setPath] = useState<string>(currentPath);

  useEffect(() => {
    const onChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return path;
}
