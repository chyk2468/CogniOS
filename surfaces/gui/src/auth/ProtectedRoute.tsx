import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();

  if (state.status === "loading") {
    return (
      <div className="min-h-screen grid place-items-center bg-bg text-muted text-[13px]">
        Loading…
      </div>
    );
  }

  if (state.status !== "authenticated") {
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
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

export function RootRedirect() {
  const { state } = useAuth();

  if (state.status === "loading") {
    return (
      <div className="min-h-screen grid place-items-center bg-bg text-muted text-[13px]">
        Loading…
      </div>
    );
  }

  return <Navigate to={state.status === "authenticated" ? "/chat" : "/signin"} replace />;
}
