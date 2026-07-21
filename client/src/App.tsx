import { useEffect } from "react";
import { Landing } from "./landing/Landing";
import { Login } from "./auth/Login";
import { Signup } from "./auth/Signup";
import { Dashboard } from "./dashboard/Dashboard";
import { useAuth } from "./auth/AuthContext";
import { useRoutePath, navigate } from "./router";
import { FullScreenLoader } from "./components/Loader";

function App() {
  const path = useRoutePath();
  const { user, loading } = useAuth();

  const isProtected = path.startsWith("/dashboard");
  const isAuthPage = path === "/login" || path === "/signup";

  // Redirects run in an effect (never navigate during render):
  //  - not logged in + protected page  → /login
  //  - logged in + login/signup page    → /dashboard
  useEffect(() => {
    if (loading) return;
    if (isProtected && !user) navigate("/login");
    else if (isAuthPage && user) navigate("/dashboard");
  }, [loading, user, isProtected, isAuthPage, path]);

  // Initial token check in flight — don't flash any page yet.
  if (loading) return <FullScreenLoader />;

  // The effect above fires after paint, so guard the render too: this is what actually
  // stops an unauthenticated user from ever seeing a dashboard page.
  if (isProtected && !user) return <FullScreenLoader />;
  if (isAuthPage && user) return <FullScreenLoader />;

  if (path === "/login") return <Login />;
  if (path === "/signup") return <Signup />;
  if (isProtected) return <Dashboard path={path} />;
  return <Landing />;
}

export default App;
