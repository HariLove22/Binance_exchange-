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
  { key: "assets", label: "Assets", icon: IWallet },
  { key: "orders", label: "Orders", icon: IList },
  { key: "rewards", label: "Rewards Hub", icon: IGift },
  { key: "referral", label: "Referral", icon: IUsers },
  { key: "account", label: "Account", icon: IUser },
  { key: "subaccounts", label: "Sub Accounts", icon: IUsersBox },
  { key: "settings", label: "Settings", icon: IGear },
];

// The Trade dropdown, like Binance's top nav. Spot is live; the rest are not built yet and say so.
type TradeOption = { label: string; desc: string; to?: string; tag?: string };
const TRADE_OPTIONS: TradeOption[] = [
  { label: "Spot", desc: "Trade crypto on the order book", to: "/dashboard/trade" },
  { label: "Margin", desc: "Leverage — not built yet", tag: "soon" },
  { label: "P2P", desc: "Buy & sell with bank transfer — not built yet", tag: "soon" },
  { label: "Convert", desc: "Instant swap — not built yet", tag: "soon" },
  { label: "Demo Trading", desc: "Practice with virtual funds — not built yet", tag: "soon" },
];

function segmentOf(path: string): string {
  // "/dashboard" -> "", "/dashboard/assets" -> "assets"
  return path.replace(/^\/dashboard\/?/, "").split("/")[0] ?? "";
}

export function Dashboard({ path }: { path: string }) {
  const { user, logout } = useAuth();
  const seg = segmentOf(path);
  const [menuOpen, setMenuOpen] = useState(false);
  const [tradeOpen, setTradeOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const tradeRef = useRef<HTMLDivElement>(null);

  // Close either dropdown on an outside click.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
      if (tradeRef.current && !tradeRef.current.contains(e.target as Node)) setTradeOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  if (!user) return null; // guarded by App; satisfies the type here.

  const active = NAV.find((n) => n.key === seg) ?? NAV[0];

  return (
    <div className="dash">
      <header className="dash-top">
        <a className="dash-brand" href="#/dashboard" onClick={(e) => { e.preventDefault(); navigate("/dashboard"); }}>
          <span className="brand-mark" aria-hidden>◈</span> Novex
        </a>
        <nav className="dash-topnav">
          <a href="#/dashboard" onClick={(e) => e.preventDefault()}>Buy Crypto</a>
          <a href="#/dashboard" onClick={(e) => e.preventDefault()}>Markets</a>

          <div className="topnav-drop" ref={tradeRef}>
            <button
              className={`topnav-trigger ${seg === "trade" ? "active" : ""}`}
              onClick={() => setTradeOpen((o) => !o)}
            >
              Trade ▾
            </button>
            {tradeOpen && (
              <div className="trade-dropdown">
                {TRADE_OPTIONS.map((opt) => (
                  <button
                    key={opt.label}
                    className={`td-item ${opt.to ? "" : "disabled"}`}
                    disabled={!opt.to}
                    onClick={() => {
                      if (opt.to) {
                        navigate(opt.to);
                        setTradeOpen(false);
                      }
                    }}
                  >
                    <span className="td-label">
                      {opt.label}
                      {opt.tag && <span className="td-tag">{opt.tag}</span>}
                    </span>
                    <span className="td-desc">{opt.desc}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <a href="#/dashboard" onClick={(e) => e.preventDefault()}>Futures</a>
          <a href="#/dashboard" onClick={(e) => e.preventDefault()}>Earn</a>
          <a href="#/dashboard" onClick={(e) => e.preventDefault()}>More</a>
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
