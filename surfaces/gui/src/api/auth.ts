import { fetch, httpBase } from "./client";

export type AuthUser = {
  id: number;
  full_name: string;
  username: string;
  email: string;
};

export type AuthState =
  | { status: "loading" }
  | { status: "authenticated"; user: AuthUser }
  | { status: "unauthenticated" };

type MeResponse =
  | { authenticated: true; user: AuthUser }
  | { authenticated: false };

type FieldErrors = Record<string, string>;

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
}): Promise<AuthUser> {
  const data = await authJson<{ ok: true; user: AuthUser }>("/v1/auth/signin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return data.user;
}

export async function signOut(): Promise<void> {
  await authJson<{ ok: true }>("/v1/auth/signout", { method: "POST" });
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
): Promise<string> {
  const data = await authJson<{ ok: true; reset_token: string }>(
    "/v1/auth/forgot-password/verify-pet",
    { method: "POST", body: JSON.stringify({ token, pet_answer }) },
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
