import { useAuth } from '../auth/AuthContext';

const BASE_URL = 'http://127.0.0.1:8000';

export async function request<T>(path: string, options: RequestInit = {}) {
  const response = await fetch(`${BASE_URL}${path}`, options);

  if (response.status === 401) {
    throw new Error('unauthorized');
  }

  const contentType = response.headers.get('content-type');
  if (contentType?.includes('application/json')) {
    return response.json() as Promise<T>;
  }

  return null as unknown as T;
}

export function authHeaders(token: string | null) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}
