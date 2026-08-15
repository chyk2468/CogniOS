import { fetch, httpBase } from "./client";

export type AuthUser = {
  id: number;
  full_name: string;
  username: string;
  email: string;
};

/** Short friendly name for greetings — username first, else first name from full_name. */
export function userGreetingName(user: AuthUser): string {
  const un = user.username.trim();
  if (un) return un.charAt(0).toUpperCase() + un.slice(1);
  const first = user.full_name.trim().split(/\s+/).filter(Boolean)[0];
  return first ?? "there";
}

export type AccountInfo = AuthUser & {
  created_at: string;
  totp_enabled: boolean;
};

export type AuthState =
  | { status: "loading" }
  | { status: "authenticated"; user: AuthUser }
  | { status: "unauthenticated" };

export type AuthStatus = {
  owner_exists: boolean;
  signup_allowed: boolean;
};

type MeResponse =
  | { authenticated: true; user: AuthUser }
  | { authenticated: false };

type FieldErrors = Record<string, string>;

type SignInResult =
  | { ok: true; user: AuthUser; requires_totp?: false }
  | { ok: true; requires_totp: true; challenge_token: string };

async function authJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${httpBase()}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error((body as { error?: string }).error || "Request failed") as Error & {
      status: number;
      fields?: FieldErrors;
    };
    err.status = res.status;
    err.fields = (body as { fields?: FieldErrors }).fields;
    throw err;
  }
  return body as T;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  return authJson<AuthStatus>("/v1/auth/status");
}

export async function getAuthMe(): Promise<AuthState> {
  try {
    const data = await authJson<MeResponse>("/v1/auth/me");
    if (data.authenticated) {
      return { status: "authenticated", user: data.user };
    }
    return { status: "unauthenticated" };
  } catch {
    return { status: "unauthenticated" };
  }
}

export async function getAccount(): Promise<{
  account: AccountInfo;
  session: { created_at: string; last_activity: string } | null;
}> {
  return authJson("/v1/auth/account");
}

export async function signUp(payload: {
  full_name: string;
  username: string;
  email: string;
  password: string;
  confirm_password: string;
  favorite_pet: string;
}): Promise<AuthUser> {
  const data = await authJson<{ ok: true; user: AuthUser }>("/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return data.user;
}

export async function signIn(payload: {
  identifier: string;
  password: string;
}): Promise<SignInResult> {
  return authJson<SignInResult>("/v1/auth/signin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function signInTotp(payload: {
  challenge_token: string;
  code: string;
}): Promise<AuthUser> {
  const data = await authJson<{ ok: true; user: AuthUser }>("/v1/auth/signin/totp", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return data.user;
}

export async function signOut(): Promise<void> {
  await authJson<{ ok: true }>("/v1/auth/signout", { method: "POST" });
}

export async function changePassword(payload: {
  current_password: string;
  password: string;
  confirm_password: string;
}): Promise<void> {
  await authJson<{ ok: true }>("/v1/auth/account/password", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function changeUsername(username: string): Promise<AuthUser> {
  const data = await authJson<{ ok: true; user: AuthUser }>("/v1/auth/account/username", {
    method: "PATCH",
    body: JSON.stringify({ username }),
  });
  return data.user;
}

export async function changeEmail(email: string): Promise<AuthUser> {
  const data = await authJson<{ ok: true; user: AuthUser }>("/v1/auth/account/email", {
    method: "PATCH",
    body: JSON.stringify({ email }),
  });
  return data.user;
}

export async function totpSetup(): Promise<{
  setup_token: string;
  otpauth_uri: string;
  manual_key: string;
  qr_png_base64: string;
}> {
  return authJson("/v1/auth/totp/setup", { method: "POST" });
}

export async function totpVerifySetup(payload: {
  setup_token: string;
  code: string;
}): Promise<{ totp_enabled: boolean; account: AccountInfo }> {
  return authJson("/v1/auth/totp/verify-setup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function totpDisable(payload: {
  current_password: string;
  code: string;
}): Promise<{ totp_enabled: boolean; account: AccountInfo }> {
  return authJson("/v1/auth/totp/disable", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function removeAccount(payload: {
  confirmation: string;
  current_password: string;
  totp_code?: string;
}): Promise<void> {
  await authJson<{ ok: true; owner_exists: false }>("/v1/auth/account/remove", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function forgotPasswordStart(identifier: string): Promise<string> {
  const data = await authJson<{ ok: true; token: string }>(
    "/v1/auth/forgot-password/start",
    { method: "POST", body: JSON.stringify({ identifier }) },
  );
  return data.token;
}

export async function forgotPasswordVerifyPet(
  token: string,
  pet_answer: string,
): Promise<{ reset_token?: string; requires_totp?: boolean; token?: string }> {
  return authJson("/v1/auth/forgot-password/verify-pet", {
    method: "POST",
    body: JSON.stringify({ token, pet_answer }),
  });
}

export async function forgotPasswordVerifyTotp(
  token: string,
  code: string,
): Promise<string> {
  const data = await authJson<{ ok: true; reset_token: string }>(
    "/v1/auth/forgot-password/verify-totp",
    { method: "POST", body: JSON.stringify({ token, code }) },
  );
  return data.reset_token;
}

export async function forgotPasswordReset(payload: {
  reset_token: string;
  password: string;
  confirm_password: string;
}): Promise<void> {
  await authJson<{ ok: true }>("/v1/auth/forgot-password/reset", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
