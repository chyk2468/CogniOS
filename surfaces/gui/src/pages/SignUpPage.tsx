import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { signUp } from "../api/auth";
import { AuthButton, AuthField, AuthLayout, authInputClass } from "../auth/AuthLayout";

export function SignUpPage() {
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [favoritePet, setFavoritePet] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setErrors({});
    setBusy(true);
    try {
      await signUp({
        full_name: fullName,
        username,
        email,
        password,
        confirm_password: confirmPassword,
        favorite_pet: favoritePet,
      });
      navigate("/signin", { replace: true, state: { message: "Owner account created. Sign in to continue." } });
    } catch (err: unknown) {
      const e = err as Error & { fields?: Record<string, string>; status?: number };
      if (e.message === "owner_exists" || e.status === 403) {
        navigate("/signin", { replace: true });
        return;
      }
      if (e.fields) setErrors(e.fields);
      else setError(e.message || "Registration failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Create your account" subtitle="Set up the owner account for this workspace">
      <form onSubmit={onSubmit}>
        <AuthField label="Full Name" id="full_name" error={errors.full_name}>
          <input id="full_name" type="text" autoComplete="name" className={authInputClass} value={fullName} onChange={(e) => setFullName(e.target.value)} required />
        </AuthField>
        <AuthField label="Username" id="username" error={errors.username}>
          <input id="username" type="text" autoComplete="username" className={authInputClass} value={username} onChange={(e) => setUsername(e.target.value)} required />
        </AuthField>
        <AuthField label="Email" id="email" error={errors.email}>
          <input id="email" type="email" autoComplete="email" className={authInputClass} value={email} onChange={(e) => setEmail(e.target.value)} required />
        </AuthField>
        <AuthField label="Password" id="password" error={errors.password}>
          <input id="password" type="password" autoComplete="new-password" className={authInputClass} value={password} onChange={(e) => setPassword(e.target.value)} required />
        </AuthField>
        <AuthField label="Confirm Password" id="confirm_password" error={errors.confirm_password}>
          <input id="confirm_password" type="password" autoComplete="new-password" className={authInputClass} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
        </AuthField>
        <AuthField label="Favorite Pet Animal" id="favorite_pet" error={errors.favorite_pet}>
          <input id="favorite_pet" type="text" autoComplete="off" className={authInputClass} value={favoritePet} onChange={(e) => setFavoritePet(e.target.value)} required />
        </AuthField>
        {error && <p className="text-[12px] text-red-500 mb-3">{error}</p>}
        <AuthButton disabled={busy}>Create Account</AuthButton>
      </form>
      <p className="mt-5 text-center text-[13px] text-muted">
        Already have an account?{" "}
        <Link to="/signin" className="text-accent hover:underline">Sign In</Link>
      </p>
    </AuthLayout>
  );
}
