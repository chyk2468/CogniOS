import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  forgotPasswordReset,
  forgotPasswordStart,
  forgotPasswordVerifyPet,
} from "../api/auth";
import { AuthButton, AuthField, AuthLayout, authInputClass } from "../auth/AuthLayout";

type Step = "identify" | "pet" | "reset";

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("identify");
  const [identifier, setIdentifier] = useState("");
  const [token, setToken] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [petAnswer, setPetAnswer] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const onIdentify = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const t = await forgotPasswordStart(identifier);
      setToken(t);
      setStep("pet");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  };

  const onVerifyPet = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const rt = await forgotPasswordVerifyPet(token, petAnswer);
      setResetToken(rt);
      setStep("reset");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setBusy(false);
    }
  };

  const onReset = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setErrors({});
    setBusy(true);
    try {
      await forgotPasswordReset({
        reset_token: resetToken,
        password,
        confirm_password: confirmPassword,
      });
      navigate("/signin", { replace: true });
    } catch (err: unknown) {
      const e = err as Error & { fields?: Record<string, string> };
      if (e.fields) setErrors(e.fields);
      else setError(e.message || "Password reset failed.");
    } finally {
      setBusy(false);
    }
  };

  if (step === "identify") {
    return (
      <AuthLayout title="Reset Password">
        <form onSubmit={onIdentify}>
          <AuthField label="Email / Username" id="identifier">
            <input
              id="identifier"
              type="text"
              className={authInputClass}
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
            />
          </AuthField>
          {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}
          <AuthButton disabled={busy}>Continue</AuthButton>
        </form>
        <p className="mt-5 text-center">
          <Link to="/signin" className="text-accent hover:underline text-[13px]">
            Back to Sign In
          </Link>
        </p>
      </AuthLayout>
    );
  }

  if (step === "pet") {
    return (
      <AuthLayout title="Reset Password" subtitle="Answer your security question">
        <form onSubmit={onVerifyPet}>
          <AuthField label="Favorite Pet Animal" id="pet_answer">
            <input
              id="pet_answer"
              type="text"
              autoComplete="off"
              className={authInputClass}
              value={petAnswer}
              onChange={(e) => setPetAnswer(e.target.value)}
              required
            />
          </AuthField>
          {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}
          <AuthButton disabled={busy}>Verify</AuthButton>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Reset Password" subtitle="Choose a new password">
      <form onSubmit={onReset}>
        <AuthField label="New Password" id="password" error={errors.password}>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            className={authInputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </AuthField>
        <AuthField label="Confirm New Password" id="confirm_password" error={errors.confirm_password}>
          <input
            id="confirm_password"
            type="password"
            autoComplete="new-password"
            className={authInputClass}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </AuthField>
        {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}
        <AuthButton disabled={busy}>Reset Password</AuthButton>
      </form>
    </AuthLayout>
  );
}
