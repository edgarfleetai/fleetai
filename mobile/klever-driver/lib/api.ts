/** Public configuration only. Never embed API keys or OTP secrets in a mobile bundle. */
export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || '';
export type Vehicle = { id: string; make: string; model: string; year: number; dailyRent: number; deposit: number; status: 'available' | 'reserved' | 'rented'; imageUrl?: string };
export type ApplicationStatus = 'draft' | 'pending_review' | 'approved' | 'rejected';
export async function listVehicles(): Promise<Vehicle[]> {
  if (!API_BASE_URL) return [];
  const res = await fetch(`${API_BASE_URL.replace(/\/$/,'')}/v1/public/vehicles`);
  if (!res.ok) throw new Error('Не удалось загрузить автомобили');
  const data: unknown = await res.json();
  if (!Array.isArray(data)) throw new Error('Неверный ответ сервера');
  return data as Vehicle[];
}
