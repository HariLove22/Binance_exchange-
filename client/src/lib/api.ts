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
};

/** Trim trailing zeros from a fixed-scale amount string for display only. Never used for math. */
export function trimAmount(value: string): string {
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-" ? "0" : trimmed;
}
