import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../lib/api";

/**
 * The access token lives in React state only (30 minutes, never in storage
 * scripts can read). Staying signed in across refreshes comes from an
 * httpOnly session cookie on the site's own origin: on load we trade it for a
 * fresh access token, and when a token expires mid-session we do the same.
 *
 * localStorage holds only a "this browser had a session" hint, so anonymous
 * visitors don't trigger a pointless refresh call. It is not a credential.
 */
const AuthContext = createContext(null);
const HINT = "citebase_has_session";

function readHint() {
  try {
    return window.localStorage.getItem(HINT) === "1";
  } catch {
    return false;
  }
}
function writeHint(on) {
  try {
    if (on) window.localStorage.setItem(HINT, "1");
    else window.localStorage.removeItem(HINT);
  } catch {
    /* storage blocked: we just won't try to restore next time */
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);
  const [restoring, setRestoring] = useState(readHint);
  const refreshing = useRef(null);

  const loadUser = useCallback(async (accessToken) => {
    try {
      setUser(await api.getMe(accessToken));
    } catch {
      setUser(null); // /me is optional chrome; never block sign-in on it
    }
  }, []);

  /** Every way of signing in ends here: keep the token, start a cookie session. */
  const establish = useCallback(
    async (accessToken) => {
      setToken(accessToken);
      writeHint(true);
      api.startSession(accessToken).catch(() => {
        /* the app still works for this tab; it just won't survive a refresh */
      });
      await loadUser(accessToken);
    },
    [loadUser],
  );

  const dropLocal = useCallback(() => {
    setToken(null);
    setUser(null);
    writeHint(false);
  }, []);

  /** One refresh at a time, however many requests hit a 401 together. */
  const renew = useCallback(() => {
    if (!refreshing.current) {
      refreshing.current = api
        .refreshSession()
        .then(({ access_token }) => {
          setToken(access_token);
          return access_token;
        })
        .catch(() => {
          dropLocal();
          return null;
        })
        .finally(() => {
          refreshing.current = null;
        });
    }
    return refreshing.current;
  }, [dropLocal]);

  useEffect(() => {
    api.setTokenRefresher(renew);
    return () => api.setTokenRefresher(null);
  }, [renew]);

  // Restore on page load. The API may be waking from sleep, so retry a few times
  // on network errors; a 401 means the session is over.
  useEffect(() => {
    if (!readHint()) return undefined;
    let cancelled = false;
    (async () => {
      for (const wait of [0, 3000, 8000, 15000, 30000, 45000]) {
        if (wait) await sleep(wait);
        if (cancelled) return;
        try {
          const { access_token } = await api.refreshSession();
          if (cancelled) return;
          setToken(access_token);
          await loadUser(access_token);
          break;
        } catch (err) {
          if (err.status === 401 || err.status === 403) {
            dropLocal();
            break;
          }
        }
      }
      if (!cancelled) setRestoring(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadUser, dropLocal]);

  const signIn = useCallback(
    async (email, password) => {
      const { access_token } = await api.login(email, password);
      await establish(access_token);
    },
    [establish],
  );

  const register = useCallback(
    async (email, password, orgName) => {
      const { access_token } = await api.signup(email, password, orgName);
      await establish(access_token);
    },
    [establish],
  );

  const joinWithInvite = useCallback(
    async (inviteToken, password) => {
      const { access_token } = await api.acceptInvite(inviteToken, password);
      await establish(access_token);
    },
    [establish],
  );

  /** Google/GitHub callback, password reset and password change hand us a token directly. */
  const signInWithToken = establish;

  const refreshUser = useCallback(() => (token ? loadUser(token) : Promise.resolve()), [token, loadUser]);

  const signOut = useCallback(() => {
    api.endSession().catch(() => {});
    dropLocal();
  }, [dropLocal]);

  const value = useMemo(
    () => ({
      token,
      user,
      restoring,
      signIn,
      register,
      joinWithInvite,
      signInWithToken,
      signOut,
      refreshUser,
      isAuthed: Boolean(token),
    }),
    [token, user, restoring, signIn, register, joinWithInvite, signInWithToken, signOut, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

const RANK = { VIEWER: 0, MEMBER: 1, ADMIN: 2, OWNER: 3 };

/** UI hint only — the API enforces every permission on its own. */
export function hasRole(user, minRole) {
  return (RANK[user?.role] ?? -1) >= RANK[minRole];
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
