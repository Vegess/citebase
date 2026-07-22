import { createContext, useContext, useState } from 'react';

interface AuthContextValue {
  token: string | null;
  email: string | null;
  setAuth: (token: string, email: string) => void;
  clearAuth: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);

  function setAuth(authToken: string, authEmail: string) {
    setToken(authToken);
    setEmail(authEmail);
  }

  function clearAuth() {
    setToken(null);
    setEmail(null);
  }

  return (
    <AuthContext.Provider value={{ token, email, setAuth, clearAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}
