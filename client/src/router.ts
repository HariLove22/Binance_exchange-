import { useEffect, useState } from "react";

// Minimal hash-based, path-style router — no dependency, consistent with the project's
// minimal-deps philosophy. Paths look like "/", "/login", "/dashboard/assets".
// Swap for react-router if real deep-linking / server routes are needed.

export function currentPath(): string {
  const h = window.location.hash.replace(/^#/, "");
  if (h === "" || h === "/") return "/";
  return h.replace(/\/+$/, "") || "/";
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
