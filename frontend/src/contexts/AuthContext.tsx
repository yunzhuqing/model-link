import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface AuthContextType {
  token: string | null;
  login: (token: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  validateToken: () => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Decode a JWT token payload without verification (just base64 decode).
 * Returns null if the token is invalid.
 */
function decodeToken(token: string): { exp?: number; sub?: string } | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    // JWT uses base64url encoding
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const jsonStr = atob(base64);
    return JSON.parse(jsonStr);
  } catch {
    return null;
  }
}

/**
 * Check if a JWT token is expired by examining its `exp` claim.
 */
function isTokenExpired(token: string): boolean {
  const decoded = decodeToken(token);
  if (!decoded || !decoded.exp) return true; // No expiry means treat as invalid
  const now = Math.floor(Date.now() / 1000);
  return decoded.exp < now;
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [token, setToken] = useState<string | null>(() => {
    const stored = localStorage.getItem('token');
    if (stored && isTokenExpired(stored)) {
      localStorage.removeItem('token');
      return null;
    }
    return stored;
  });

  const login = (newToken: string) => {
    localStorage.setItem('token', newToken);
    setToken(newToken);
  };

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    setToken(null);
  }, []);

  const validateToken = useCallback((): boolean => {
    const stored = localStorage.getItem('token');
    if (!stored || isTokenExpired(stored)) {
      logout();
      return false;
    }
    return true;
  }, [logout]);

  return (
    <AuthContext.Provider value={{ token, login, logout, isAuthenticated: !!token, validateToken }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
