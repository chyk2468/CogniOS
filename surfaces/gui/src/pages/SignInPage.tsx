import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAuthStatus, signIn, signInTotp } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { AuthButton, AuthField, AuthLayout, authInputClass } from "../auth/AuthLayout";

export function SignInPage() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [step, setStep] = useState<"password" | "totp">("password");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [challengeToken, setChallengeToken] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showSignupLink, setShowSignupLink] = useState(false);

  useEffect(() => {
    getAuthStatus()
      .then((s) => setShowSignupLink(s.signup_allowed))
      .catch(() => setShowSignupLink(false));
  }, []);

  const onPasswordSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await signIn({ identifier, password });
      if ("requires_totp" in result && result.requires_totp) {
        setChallengeToken(result.challenge_token);
        setStep("totp");
        setTotpCode("");
      } else if ("user" in result && result.user) {
        setUser(result.user);
        navigate("/chat", { replace: true });
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  };

  const onTotpSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const user = await signInTotp({ challenge_token: challengeToken, code: totpCode });
      setUser(user);
      navigate("/chat", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid authentication code.");
    } finally {
      setBusy(false);
    }
  };

  if (step === "totp") {
    return (
      <AuthLayout title="Two-Factor Authentication" subtitle="Enter the 6-digit code from your authenticator app">
        <form onSubmit={onTotpSubmit}>
          <AuthField label="Authentication code" id="totp">
            <input
              id="totp"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              className={authInputClass + " tracking-widest text-center"}
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              maxLength={6}
              required
            />
          </AuthField>
          {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}
          <AuthButton disabled={busy || totpCode.length < 6}>Verify</AuthButton>
        </form>
        <button
          type="button"
          className="w-full mt-4 text-[13px] text-muted hover:text-fg"
          onClick={() => {
            setStep("password");
            setChallengeToken("");
            setTotpCode("");
            setError("");
          }}
        >
          Back to sign in
        </button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Welcome back">
      <form onSubmit={onPasswordSubmit}>
        <AuthField label="User" id="identifier">
          <input
            id="identifier"
            type="text"
            autoComplete="username"
            className={authInputClass}
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            required
          />
        </AuthField>
        <AuthField label="Password" id="password">
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className={authInputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </AuthField>
        {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}
        <AuthButton disabled={busy}>Continue</AuthButton>
      </form>
      <div className="mt-5 flex flex-col gap-2 text-center">
        <Link to="/forgot-password" className="text-accent hover:underline text-[13px]">
          Forgot Password?
        </Link>
        {showSignupLink && (
          <Link to="/signup" className="text-muted hover:text-fg text-[13px]">
            Create owner account
          </Link>
        )}
      </div>
    </AuthLayout>
  );
}
