import { createContext, useCallback, useContext, useMemo, useState } from "react";
import * as api from "../lib/api";

/**
 * The token lives in React state and nowhere else.
 *
 * localStorage would survive a refresh, but any injected script can read it —
 * that is the standard XSS path for stealing sessions. Keeping it in a closure
 * costs a re-login on refresh and removes that whole class of attack. The
 * production fix for both is an httpOnly cookie issued by the API.
 */
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);

  const loadUser = useCallback(async (accessToken) => {
    try {
      setUser(await api.getMe(accessToken));
    } catch {
      setUser(null); // /me is optional chrome; never block sign-in on it
    }
  }, []);

  const signIn = useCallback(
    async (email, password) => {
      const { access_token } = await api.login(email, password);
      setToken(access_token);
      await loadUser(access_token);
    },
    [loadUser],
  );

  const register = useCallback(
    async (email, password, orgName) => {
      const { access_token } = await api.signup(email, password, orgName);
      setToken(access_token);
      await loadUser(access_token);
    },
    [loadUser],
  );

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ token, user, signIn, register, signOut, isAuthed: Boolean(token) }),
    [token, user, signIn, register, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
