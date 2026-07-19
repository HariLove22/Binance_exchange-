import { useEffect, useState } from "react";

// Minimal hash-based router — no dependency, consistent with the project's
// minimal-deps philosophy. Swap for react-router if real deep-linking is needed.

export type Route = "landing" | "login" | "signup";

function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, "").toLowerCase();
  if (h === "login") return "login";
  if (h === "signup") return "signup";
  return "landing";
}

export function navigate(route: Route): void {
  const target = route === "landing" ? "#/" : `#/${route}`;
  if (window.location.hash !== target) {
    window.location.hash = target;
  }
  // Scroll to top on route change so a new page doesn't start mid-scroll.
  window.scrollTo({ top: 0 });
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return route;
}
