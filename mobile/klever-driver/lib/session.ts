import * as SecureStore from 'expo-secure-store';
import { API_BASE_URL } from './api';

const TOKEN_KEY = 'klever_driver_session_v1';
export type DriverProfile = { account_id: string; verification_status: 'pending_review' | 'approved' | 'rejected' };

export async function readSessionToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

/** Use only a token returned by the trusted backend after verified OTP. */
export async function saveVerifiedSessionToken(token: string): Promise<void> {
  if (!token || token.length < 32) throw new Error('Invalid session token');
  await SecureStore.setItemAsync(TOKEN_KEY, token, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

export async function loadMyProfile(): Promise<DriverProfile | null> {
  const token = await readSessionToken();
  if (!token) return null;
  if (!API_BASE_URL) throw new Error('Сервер авторизации ещё не подключён');
  const response = await fetch(`${API_BASE_URL.replace(/\/$/, '')}/v1/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 401) {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    return null;
  }
  if (!response.ok) throw new Error('Не удалось получить профиль');
  return response.json() as Promise<DriverProfile>;
}

export async function logout(): Promise<void> {
  const token = await readSessionToken();
  if (token && API_BASE_URL) {
    try {
      await fetch(`${API_BASE_URL.replace(/\/$/, '')}/v1/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // Still erase the device token; the server session will expire.
    }
  }
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
