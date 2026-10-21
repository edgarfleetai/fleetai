export type DemoCar = { id: string; model: string; year: number; transmission: string; price: number; deposit: number; color: string; icon: string };
/** Clearly fictional, locally bundled data for UI evaluation only. */
export const DEMO_CARS: DemoCar[] = [
 { id: 'demo-1', model: 'Hyundai Solaris', year: 2020, transmission: 'Автомат', price: 2100, deposit: 10000, color: '#DDEAE5', icon: '🚙' },
 { id: 'demo-2', model: 'Kia Rio', year: 2019, transmission: 'Механика', price: 1850, deposit: 8000, color: '#E8E7F4', icon: '🚗' },
 { id: 'demo-3', model: 'Hyundai Solaris', year: 2018, transmission: 'Автомат', price: 1950, deposit: 10000, color: '#F3E8D9', icon: '🚘' },
];
