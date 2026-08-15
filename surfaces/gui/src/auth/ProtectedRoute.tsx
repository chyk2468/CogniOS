import { Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { getAuthStatus } from "../api/auth";
import { useAuth } from "./AuthContext";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { state } = useAuth();

  if (state.status === "loading") {
    return (
      <div className="min-h-screen grid place-items-center bg-bg text-muted text-[13px]">
        Loading…
      </div>
    );
  }

  if (state.status !== "authenticated") {
    return <Navigate to="/signin" replace />;
  }

  return <>{children}</>;
}

export function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const { state } = useAuth();

  if (state.status === "loading") {
    return (
      <div className="min-h-screen grid place-items-center bg-bg text-muted text-[13px]">
        Loading…
      </div>
    );
  }

  if (state.status === "authenticated") {
    return <Navigate to="/chat" replace />;
  }

  return <>{children}</>;
}

export function SignUpRoute({ children }: { children: React.ReactNode }) {
  const { state } = useAuth();
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    getAuthStatus()
      .then((s) => setAllowed(s.signup_allowed))
      .catch(() => setAllowed(false));
  }, []);

  if (state.status === "loading" || allowed === null) {
    return (
      <div className="min-h-screen grid place-items-center bg-bg text-muted text-[13px]">
        Loading…
      </div>
    );
  }

  if (state.status === "authenticated") {
    return <Navigate to="/chat" replace />;
  }

  if (!allowed) {
    return <Navigate to="/signin" replace />;
  }

  return <>{children}</>;
}

export function RootRedirect() {
  const { state } = useAuth();
  const [signupAllowed, setSignupAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    getAuthStatus()
      .then((s) => setSignupAllowed(s.signup_allowed))
      .catch(() => setSignupAllowed(false));
  }, []);

  if (state.status === "loading" || signupAllowed === null) {
    return (
      <div className="min-h-screen grid place-items-center bg-bg text-muted text-[13px]">
        Loading…
      </div>
    );
  }

  if (state.status === "authenticated") {
    return <Navigate to="/chat" replace />;
  }

  return <Navigate to={signupAllowed ? "/signup" : "/signin"} replace />;
}
