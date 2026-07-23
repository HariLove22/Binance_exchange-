const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const API_V1 = `${API_BASE}/api/v1`;

// --- token storage -------------------------------------------------------
// localStorage persists across tabs/reloads. Fine for a JWT in this app; for stricter
// XSS posture you'd move to an httpOnly cookie + CSRF token later.
const TOKEN_KEY = "novex_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const TIMEOUT_MS = 10_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${API_V1}${path}`, {
      // Without this, a hung backend leaves the caller waiting forever — the UI sits in a
      // loading state that never resolves, which reads as "still working", not "broken".
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
      ...init,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError") {
      throw new ApiError(`Request timed out after ${TIMEOUT_MS / 1000}s`, 0);
    }
    throw new ApiError("Can't reach the server — is the API running?", 0);
  }

  if (!res.ok) throw new ApiError(await extractError(res, init), res.status);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// FastAPI errors come back as {detail: "..."} for HTTPException, or
// {detail: [{msg, loc, ...}]} for validation (422). Surface something human-readable.
async function extractError(res: Response, init?: RequestInit): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) {
      return String(detail[0].msg).replace(/^Value error,\s*/, "");
    }
  } catch {
    /* body wasn't JSON */
  }
  return `${init?.method ?? "GET"} request failed (${res.status})`;
}

// --- types ---------------------------------------------------------------
export interface HealthResponse {
  status: string;
  environment: string;
}
export interface DbHealthResponse {
  status: string;
  database: string;
}

export interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  role: "USER" | "ADMIN";
  is_verified: boolean;
  created_at: string;
}
export interface AuthResponse {
  access_token: string | null;
  token_type: string;
  requires_verification: boolean;
  user: AuthUser;
}

export interface RegisterBody {
  email: string;
  full_name: string;
  password: string;
}
export interface LoginBody {
  email: string;
  password: string;
}

export interface Balance {
  asset: string;
  scale: number;
  // Fixed-scale strings, never numbers — the ledger stores NUMERIC(36,18) and a JSON number
  // would be parsed into a double here, losing precision. Do arithmetic on these as strings /
  // BigInt if it is ever needed; for display, format the string.
  available: string;
  locked: string;
  total: string;
}

export interface WalletNetwork {
  asset_network_id: number;
  asset: string;
  chain: string;
  chain_name: string;
  min_withdrawal: string;
  withdrawal_fee: string;
  confirmations: number;
  deposit_enabled: boolean;
  withdraw_enabled: boolean;
}

export interface DepositRecord {
  id: number;
  asset: string;
  chain: string;
  tx_hash: string;
  amount: string;
  status: string;
  confirmations: number;
  required_confirmations: number;
}

export interface WithdrawalRecord {
  id: number;
  asset: string;
  chain: string;
  to_address: string;
  amount: string;
  fee: string;
  status: string;
  tx_hash: string | null;
}

export interface AdminUserRow {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_verified: boolean;
  is_active: boolean;
  asset_count: number;
}

export interface ReconciliationRow {
  asset: string;
  trial_balance: string;
  ledger_external: string;
  custody_onchain: string;
  balanced: boolean;
}

export interface MarketInfo {
  symbol: string;
  base: string;
  quote: string;
  price_tick: string;
  qty_step: string;
  min_notional: string;
  maker_fee: string;
  taker_fee: string;
}

export interface DepthLevel {
  price: string;
  quantity: string;
}
export interface OrderBook {
  symbol: string;
  bids: DepthLevel[];
  asks: DepthLevel[];
}

export interface TradeTick {
  id: number;
  price: string;
  quantity: string;
  taker_side: string;
  created_at: string;
}

export interface OrderRow {
  id: number;
  symbol: string;
  side: string;
  type: string;
  price: string | null;
  trigger_price?: string | null;
  quantity: string;
  filled_quantity: string;
  status: string;
}

export interface MyTrade {
  id: number;
  symbol: string;
  price: string;
  quantity: string;
  side: string;
  role: string;
  created_at: string;
}

/** Binance kline: [openTime, open, high, low, close, volume, ...]. */
export type Kline = [number, string, string, string, string, string, ...unknown[]];

export interface UniverseRow {
  symbol: string;
  base: string;
  quote: string;
  price: number;
  change_percent: number;
  quote_volume: number;
  tradeable: boolean;
}
export interface Universe {
  segments: string[];
  markets: UniverseRow[];
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  dbHealth: () => request<DbHealthResponse>("/health/db"),

  register: (body: RegisterBody) =>
    request<AuthResponse>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: LoginBody) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<AuthUser>("/auth/me"),

  balances: () => request<Balance[]>("/wallet/balances"),
  networks: (asset?: string) =>
    request<WalletNetwork[]>(`/wallet/networks${asset ? `?asset=${asset}` : ""}`),
  depositAddress: (assetNetworkId: number) =>
    request<{ asset_network_id: number; address: string; memo: string | null }>(
      `/wallet/deposit/address?asset_network_id=${assetNetworkId}`,
      { method: "POST" },
    ),
  deposits: () => request<DepositRecord[]>("/wallet/deposits"),
  withdraw: (body: {
    asset_network_id: number;
    to_address: string;
    amount: string;
    memo?: string | null;
  }) => request<WithdrawalRecord>("/wallet/withdraw", { method: "POST", body: JSON.stringify(body) }),
  withdrawals: () => request<WithdrawalRecord[]>("/wallet/withdrawals"),
  reconcile: () => request<ReconciliationRow[]>("/wallet/reconcile"),

  // dev-only: stand in for chain events
  simulateDeposit: (assetNetworkId: number, amount: string) =>
    request<DepositRecord>("/wallet/dev/simulate-deposit", {
      method: "POST",
      body: JSON.stringify({ asset_network_id: assetNetworkId, amount }),
    }),
  confirmWithdrawal: (id: number) =>
    request<WithdrawalRecord>(`/wallet/dev/withdrawals/${id}/confirm`, { method: "POST" }),

  // admin
  adminUsers: () => request<AdminUserRow[]>("/admin/users"),
  adminReconcile: () => request<ReconciliationRow[]>("/admin/reconcile"),
  adminCredit: (body: { user_id: number; asset: string; amount: string; chain?: string }) =>
    request<{ deposit_id: number; asset: string; amount: string; status: string }>("/admin/credit", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // market data
  marketSymbols: () => request<MarketInfo[]>("/market/symbols"),
  marketUniverse: (quote?: string, search?: string) => {
    const p = new URLSearchParams();
    if (quote) p.set("quote", quote);
    if (search) p.set("search", search);
    p.set("limit", "800");
    return request<Universe>(`/market/all?${p.toString()}`);
  },
  klines: (symbol: string, interval: string, limit = 200) =>
    request<Kline[]>(`/market/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`),
  orderBook: (symbol: string) => request<OrderBook>(`/market/depth?symbol=${symbol}&limit=16`),
  marketTrades: (symbol: string) => request<TradeTick[]>(`/market/trades?symbol=${symbol}&limit=30`),

  // trading
  placeOrder: (body: {
    symbol: string;
    side: "BUY" | "SELL";
    type: "LIMIT" | "MARKET" | "STOP_LIMIT" | "STOP_MARKET";
    quantity: string;
    price?: string | null;
    trigger_price?: string | null;
  }) => request<OrderRow>("/trade/order", { method: "POST", body: JSON.stringify(body) }),
  cancelOrder: (id: number) => request<OrderRow>(`/trade/order/${id}`, { method: "DELETE" }),
  openOrders: () => request<OrderRow[]>("/trade/orders"),
  orderHistory: () => request<OrderRow[]>("/trade/orders?include_history=true"),
  myTrades: () => request<MyTrade[]>("/trade/mytrades"),
  refreshMarketMaker: () =>
    request<Record<string, number>>("/trade/dev/market-maker/refresh", { method: "POST" }),
  listMarket: (symbol: string) =>
    request<{ symbol: string; status: string }>("/trade/list", { method: "POST", body: JSON.stringify({ symbol }) }),

  // fiat on-ramp
  onrampCurrencies: () =>
    request<{ code: string; name: string; per_usd: string }[]>("/wallet/onramp/currencies"),
  onrampQuote: (body: { fiat: string; fiat_amount: string; asset: string }) =>
    request<OnrampQuote>("/wallet/onramp/quote", { method: "POST", body: JSON.stringify(body) }),
  onrampBuy: (body: { fiat: string; fiat_amount: string; asset: string }) =>
    request<OnrampQuote>("/wallet/onramp/buy", { method: "POST", body: JSON.stringify(body) }),

  convertQuote: (body: { from_asset: string; to_asset: string; from_amount: string }) =>
    request<ConvertQuote>("/wallet/convert/quote", { method: "POST", body: JSON.stringify(body) }),
  convertExecute: (body: { from_asset: string; to_asset: string; from_amount: string }) =>
    request<ConvertQuote>("/wallet/convert/execute", { method: "POST", body: JSON.stringify(body) }),
};

export interface ConvertQuote {
  from_asset: string;
  to_asset: string;
  from_amount: string;
  to_amount: string;
  rate: string;
}

export interface OnrampQuote {
  fiat: string;
  fiat_amount: string;
  usd_amount: string;
  asset: string;
  unit_price_usd: string;
  crypto_amount: string;
}

/** Trim trailing zeros from a fixed-scale amount string for display only. Never used for math. */
export function trimAmount(value: string): string {
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-" ? "0" : trimmed;
}
