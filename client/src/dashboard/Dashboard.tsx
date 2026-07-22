import { useEffect, useRef, useState, type ComponentType, type SVGProps } from "react";
import { useAuth } from "../auth/AuthContext";
import { navigate } from "../router";
import { Overview, Placeholder } from "./pages";
import { Assets } from "./Assets";
import { Trade } from "./Trade";
import {
  IDeposit,
  IGear,
  IGift,
  IHome,
  IList,
  ISearch,
  IUser,
  IUsers,
  IUsersBox,
  IWallet,
} from "./icons";
import "./dashboard.css";

type NavItem = { key: string; label: string; icon: ComponentType<SVGProps<SVGSVGElement>> };

// key is the path segment after /dashboard ("" = the overview root).
const NAV: NavItem[] = [
  { key: "", label: "Dashboard", icon: IHome },
  { key: "trade", label: "Trade", icon: IList },
  { key: "assets", label: "Assets", icon: IWallet },
  { key: "orders", label: "Orders", icon: IList },
  { key: "rewards", label: "Rewards Hub", icon: IGift },
  { key: "referral", label: "Referral", icon: IUsers },
  { key: "account", label: "Account", icon: IUser },
  { key: "subaccounts", label: "Sub Accounts", icon: IUsersBox },
  { key: "settings", label: "Settings", icon: IGear },
];

const TOP_LINKS = ["Buy Crypto", "Markets", "Trade", "Futures", "Earn", "Square", "More"];

function segmentOf(path: string): string {
  // "/dashboard" -> "", "/dashboard/assets" -> "assets"
  return path.replace(/^\/dashboard\/?/, "").split("/")[0] ?? "";
}

export function Dashboard({ path }: { path: string }) {
  const { user, logout } = useAuth();
  const seg = segmentOf(path);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the user dropdown on any outside click.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  if (!user) return null; // guarded by App; satisfies the type here.

  const active = NAV.find((n) => n.key === seg) ?? NAV[0];

  return (
    <div className="dash">
      <header className="dash-top">
        <a className="dash-brand" href="#/dashboard" onClick={(e) => { e.preventDefault(); navigate("/dashboard"); }}>
          <span className="brand-mark" aria-hidden>◈</span> Novex
        </a>
        <nav className="dash-topnav">
          {TOP_LINKS.map((l) => (
            <a key={l} href="#/dashboard" onClick={(e) => e.preventDefault()}>{l}</a>
          ))}
        </nav>

        <div className="dash-top-right">
          <button className="icon-btn" aria-label="Search"><ISearch /></button>
          <button className="dash-deposit"><IDeposit style={{ width: 16, height: 16 }} /> Deposit</button>

          <div className="user-menu" ref={menuRef}>
            <button className="avatar" onClick={() => setMenuOpen((o) => !o)} aria-label="Account menu">
              {(user.full_name?.[0] ?? user.email[0]).toUpperCase()}
            </button>
            {menuOpen && (
              <div className="user-dropdown">
                <div className="ud-head">
                  <div className="ud-name">{user.full_name}</div>
                  <div className="ud-email">{user.email}</div>
                </div>
                <button className="ud-item" onClick={() => navigate("/dashboard/account")}>Account</button>
                <button className="ud-item" onClick={() => navigate("/dashboard/settings")}>Settings</button>
                <button className="ud-item danger" onClick={logout}>Log out</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="dash-body">
        <aside className="dash-side">
          {NAV.map((n) => {
            const Icon = n.icon;
            return (
              <button
                key={n.key || "home"}
                className={`side-item ${n.key === seg ? "active" : ""}`}
                onClick={() => navigate(`/dashboard${n.key ? `/${n.key}` : ""}`)}
              >
                <Icon />
                {n.label}
              </button>
            );
          })}
        </aside>

        <main className="dash-main">
          {seg === "" ? (
            <Overview user={user} />
          ) : seg === "trade" ? (
            <Trade />
          ) : seg === "assets" ? (
            <Assets />
          ) : (
            <Placeholder title={active.label} icon="🚧" />
          )}
        </main>
      </div>
    </div>
  );
}
