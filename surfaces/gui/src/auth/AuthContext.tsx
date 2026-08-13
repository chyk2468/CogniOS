import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getAuthMe,
  signOut as apiSignOut,
  type AuthState,
  type AuthUser,
} from "../api/auth";

type AuthContextValue = {
  state: AuthState;
  refresh: () => Promise<void>;
  setUser: (user: AuthUser) => void;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const refresh = useCallback(async () => {
    setState({ status: "loading" });
    setState(await getAuthMe());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setUser = useCallback((user: AuthUser) => {
    setState({ status: "authenticated", user });
  }, []);

  const signOut = useCallback(async () => {
    await apiSignOut().catch(() => {});
    setState({ status: "unauthenticated" });
  }, []);

  const value = useMemo(
    () => ({ state, refresh, setUser, signOut }),
    [state, refresh, setUser, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
