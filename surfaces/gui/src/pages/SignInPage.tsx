import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { signIn } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { AuthButton, AuthField, AuthLayout, authInputClass } from "../auth/AuthLayout";

export function SignInPage() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const user = await signIn({ identifier, password });
      setUser(user);
      navigate("/chat", { replace: true });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Sign in failed.";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Welcome back">
      <form onSubmit={onSubmit}>
        <AuthField label="Email / Username" id="identifier">
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
        <AuthButton disabled={busy}>Sign In</AuthButton>
      </form>
      <div className="mt-5 flex flex-col gap-2 text-center">
        <Link to="/forgot-password" className="text-accent hover:underline text-[13px]">
          Forgot Password?
        </Link>
        <Link to="/signup" className="text-muted hover:text-fg text-[13px]">
          Create Account
        </Link>
      </div>
    </AuthLayout>
  );
}
