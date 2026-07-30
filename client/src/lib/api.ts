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

// Registering creates the account but does NOT start a session — no token here by design.
export interface RegisterResponse {
  user: AuthUser;
  requires_verification: boolean;
  message: string;
}

export interface RegisterBody {
  email: string;
  full_name: string;
  password: string;
  referral_code?: string | null;
}

export interface ReferralRow {
  email: string;
  earned_usd: string;
  joined: string;
}
export interface ReferralSummary {
  code: string;
  count: number;
  total_earned_usd: string;
  commission_rate: string;
  referrals: ReferralRow[];
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

export interface OrderFill {
  price: string; // the trade price (maker's resting price)
  quantity: string;
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
  // ISO timestamp of when the order was placed — used by order history for date sort/display.
  created_at: string;
  // Trades that executed when this order was placed. Empty for a resting (unmatched) order.
  // The server includes these on the place-order response so a receipt can show what it cost.
  fills: OrderFill[];
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
    request<RegisterResponse>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: LoginBody) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<AuthUser>("/auth/me"),
  updateProfile: (body: { full_name: string }) =>
    request<AuthUser>("/auth/profile", { method: "PATCH", body: JSON.stringify(body) }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ message: string }>("/auth/change-password", { method: "POST", body: JSON.stringify(body) }),

  // kyc
  referralMe: () => request<ReferralSummary>("/referral/me"),

  kycMe: () => request<KycStatus>("/kyc/me"),
  kycSubmit: (body: {
    legal_name: string; date_of_birth: string; country: string; id_type: string; id_number: string;
    doc_front?: string | null; doc_back?: string | null; selfie?: string | null;
  }) => request<KycStatus>("/kyc/submit", { method: "POST", body: JSON.stringify(body) }),
  kycPending: () => request<KycPending[]>("/kyc/admin/pending"),
  kycDetail: (id: number) => request<KycDetail>(`/kyc/admin/${id}`),
  kycReview: (id: number, approve: boolean, reason?: string) =>
    request<KycStatus>(`/kyc/admin/${id}/review`, { method: "POST", body: JSON.stringify({ approve, reason }) }),

  // account center
  accountOverview: () => request<AccountOverview>("/account/overview"),
  demoGet: () => request<DemoAccount>("/account/demo"),
  demoCreate: () => request<DemoAccount>("/account/demo", { method: "POST" }),
  demoReset: () => request<DemoAccount>("/account/demo/reset", { method: "POST" }),
  demoTrade: (body: { base: string; side: "BUY" | "SELL"; quantity: string }) =>
    request<DemoAccount>("/account/demo/trade", { method: "POST", body: JSON.stringify(body) }),

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
  placeOco: (body: {
    symbol: string;
    side: "BUY" | "SELL";
    quantity: string;
    limit_price: string;
    stop_price: string;
    stop_limit_price: string;
  }) => request<OrderRow[]>("/trade/oco", { method: "POST", body: JSON.stringify(body) }),
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

  // P2P
  p2pAds: (q: { asset?: string; fiat?: string; side?: "BUY" | "SELL"; amount?: string; payment_method?: string; sort?: string } = {}) => {
    const p = new URLSearchParams();
    if (q.asset) p.set("asset", q.asset);
    if (q.fiat) p.set("fiat", q.fiat);
    if (q.side) p.set("side", q.side);
    if (q.amount) p.set("amount", q.amount);
    if (q.payment_method) p.set("payment_method", q.payment_method);
    if (q.sort) p.set("sort", q.sort);
    const qs = p.toString();
    return request<P2PAd[]>(`/p2p/ads${qs ? `?${qs}` : ""}`);
  },
  p2pMyAds: () => request<P2PAd[]>("/p2p/ads/mine"),
  p2pPostAd: (body: {
    side: "BUY" | "SELL"; asset: string; fiat: string; price: string;
    min_fiat: string; max_fiat: string; total_qty: string; payment_methods: string; terms?: string | null;
  }) => request<P2PAd>("/p2p/ads", { method: "POST", body: JSON.stringify(body) }),
  p2pCloseAd: (id: number) => request<P2PAd>(`/p2p/ads/${id}/close`, { method: "POST" }),
  p2pOpenOrder: (body: { ad_id: number; fiat_amount: string; payment_method: string }) =>
    request<P2POrder>("/p2p/orders", { method: "POST", body: JSON.stringify(body) }),
  p2pMyOrders: (openOnly = false) => request<P2POrder[]>(`/p2p/orders${openOnly ? "?open_only=true" : ""}`),
  p2pMarkPaid: (id: number) => request<P2POrder>(`/p2p/orders/${id}/paid`, { method: "POST" }),
  p2pRelease: (id: number) => request<P2POrder>(`/p2p/orders/${id}/release`, { method: "POST" }),
  p2pCancel: (id: number) => request<P2POrder>(`/p2p/orders/${id}/cancel`, { method: "POST" }),
  p2pDispute: (id: number) => request<P2POrder>(`/p2p/orders/${id}/dispute`, { method: "POST" }),
  p2pResolve: (id: number, inFavorOfBuyer: boolean) =>
    request<P2POrder>(`/p2p/orders/${id}/resolve`, { method: "POST", body: JSON.stringify({ in_favor_of_buyer: inFavorOfBuyer }) }),
  p2pDisputes: () => request<P2PDispute[]>("/p2p/admin/disputes"),

  // margin
  marginOpen: (body: { mode?: "CROSS" | "ISOLATED"; symbol?: string | null; tier?: "CLASSIC" | "PRO"; leverage?: string | null }) =>
    request<MarginAccount>("/margin/account", { method: "POST", body: JSON.stringify(body) }),
  marginAccount: (mode: "CROSS" | "ISOLATED" = "CROSS", symbol?: string) =>
    request<MarginAccount>(`/margin/account?mode=${mode}${symbol ? `&symbol=${symbol}` : ""}`),
  marginTransfer: (body: { mode?: string; symbol?: string | null; asset: string; amount: string; deposit: boolean }) =>
    request<MarginAccount>("/margin/transfer", { method: "POST", body: JSON.stringify(body) }),
  marginBorrow: (body: { mode?: string; symbol?: string | null; asset: string; amount: string }) =>
    request<MarginAccount>("/margin/borrow", { method: "POST", body: JSON.stringify(body) }),
  marginRepay: (body: { loan_id: number; amount: string }) =>
    request<MarginAccount>("/margin/repay", { method: "POST", body: JSON.stringify(body) }),
  marginOrder: (body: { mode?: string; symbol: string; side: "BUY" | "SELL"; type?: "LIMIT" | "MARKET"; quantity: string; price?: string | null; auto_borrow?: boolean }) =>
    request<{ id: number; status: string; filled_quantity: string; quantity: string; wallet: string }>("/margin/order", { method: "POST", body: JSON.stringify(body) }),
};

export interface MarginLoanRow {
  id: number;
  asset: string;
  principal: string;
  accrued_interest: string;
  owed: string;
  hourly_rate: string;
}

export interface KycStatus {
  status: "NOT_STARTED" | "PENDING" | "APPROVED" | "REJECTED";
  legal_name?: string | null;
  country?: string | null;
  id_type?: string | null;
  reject_reason?: string | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  has_front?: boolean;
  has_back?: boolean;
  has_selfie?: boolean;
}

export interface KycPending {
  id: number;
  user_id: number;
  email: string;
  legal_name: string;
  date_of_birth: string;
  country: string;
  id_type: string;
  id_number: string;
  submitted_at: string;
}

export interface KycDetail extends KycPending {
  doc_front?: string | null;
  doc_back?: string | null;
  selfie?: string | null;
}

export interface AccountOverview {
  spot_usd: string;
  margin: { open: boolean; equity_usd?: string; margin_level?: string | null; health?: string; max_leverage?: string };
  demo: { exists: boolean; total_usd?: string };
}

export interface DemoHoldingRow {
  symbol: string;
  quantity: string;
  usd_value: string;
}

export interface DemoAccount {
  exists: boolean;
  total_usd: string;
  holdings: DemoHoldingRow[];
}

export interface MarginBalanceRow {
  asset: string;
  available: string;
  locked: string;
}

export interface MarginAccount {
  id: number;
  mode: string;
  symbol: string | null;
  tier: string;
  max_leverage: string;
  wallet: string;
  gross_usd: string;
  debt_usd: string;
  equity_usd: string;
  max_borrow_usd: string;
  margin_level: string | null;
  health: string;
  loans: MarginLoanRow[];
  balances: MarginBalanceRow[];
}

export interface P2PDispute {
  id: number;
  asset: string;
  crypto_amount: string;
  fiat: string;
  fiat_amount: string;
  price: string;
  payment_method: string;
  seller_id: number;
  seller_email: string;
  buyer_id: number;
  buyer_email: string;
}

export interface P2PAd {
  id: number;
  maker_id: number;
  maker_name: string;
  maker_orders: number;
  maker_completion: string | null;
  pay_window_min: number;
  side: "BUY" | "SELL";
  asset: string;
  fiat: string;
  price: string;
  min_fiat: string;
  max_fiat: string;
  available_qty: string;
  payment_methods: string[];
  terms: string | null;
  status: string;
}

export interface P2POrder {
  id: number;
  ad_id: number;
  side_for_me: "BUY" | "SELL";
  counterparty_id: number;
  asset: string;
  fiat: string;
  price: string;
  crypto_amount: string;
  fiat_amount: string;
  payment_method: string;
  status: string;
}

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

/**
 * Format a fixed-scale amount string for display — capped at `maxDecimals` (2 by default) so the
 * UI never shows the ledger's full 18-decimal precision. Display only; never used for math.
 *
 * Truncates rather than rounds — an exact string slice, no float — so a shown "available" is never
 * rounded *up* past the real balance. Trailing zeros are then dropped (5.00 -> 5).
 *
 * The one subtlety is small crypto amounts: 0.00076 BTC cut to 2 places would read as "0" and look
 * like the balance vanished. So when the integer part is 0, we keep enough places to show two
 * significant fraction digits — a real value is never displayed as a false zero.
 */
export function trimAmount(value: string, maxDecimals = 2): string {
  if (!value.includes(".")) return value;
  const neg = value.startsWith("-");
  const [rawInt, frac = ""] = (neg ? value.slice(1) : value).split(".");
  const int = rawInt || "0";

  let places = maxDecimals;
  if (int === "0") {
    const firstSignificant = frac.search(/[1-9]/);
    if (firstSignificant >= 0) places = Math.max(maxDecimals, firstSignificant + 2);
  }

  const capped = frac.slice(0, places).replace(/0+$/, "");
  const body = capped ? `${int}.${capped}` : int;
  return neg && body !== "0" ? `-${body}` : body;
}
