import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { router } from 'expo-router';
import { DriverProfile, loadMyProfile, logout } from '../lib/session';

const labels: Record<DriverProfile['verification_status'], string> = {
  pending_review: 'Ожидает проверки',
  approved: 'Личность подтверждена',
  rejected: 'Проверка отклонена',
};

export default function Profile() {
  const [profile, setProfile] = useState<DriverProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try { setProfile(await loadMyProfile()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Ошибка подключения'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return <ScrollView style={s.page} contentContainerStyle={s.content}>
    <Text style={s.title}>Мой профиль</Text>
    {loading ? <ActivityIndicator style={{ marginTop: 24 }} /> :
      <View style={s.card}>
        {error ? <Text style={s.note}>{error}</Text> :
          profile ? <>
            <Text style={s.heading}>Водитель</Text>
            <Text style={s.note}>Статус: {labels[profile.verification_status]}</Text>
          </> : <>
            <Text style={s.heading}>Вы не вошли в аккаунт</Text>
            <Text style={s.note}>Регистрация по SMS станет доступна после подключения провайдера.</Text>
          </>}
      </View>}
    <Pressable style={s.action} onPress={() => void refresh()}><Text style={s.actionText}>Обновить статус</Text></Pressable>
    {profile && <Pressable style={s.action} onPress={() => void logout().then(() => setProfile(null)).catch(() => setError('Не удалось завершить сеанс'))}><Text style={s.actionText}>Выйти</Text></Pressable>}
    <Pressable onPress={() => router.back()}><Text style={s.back}>← Назад</Text></Pressable>
  </ScrollView>;
}
const s = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#F5F7F6' }, content: { padding: 24, paddingTop: 75 },
  title: { fontSize: 30, fontWeight: '800', color: '#172A20' },
  card: { backgroundColor: 'white', padding: 24, borderRadius: 18, marginTop: 26 },
  heading: { fontSize: 19, fontWeight: '700', color: '#172A20' },
  note: { color: '#6C7B73', fontSize: 15, lineHeight: 23, marginTop: 10 },
  action: { borderRadius: 14, borderColor: '#147D52', borderWidth: 1, padding: 16, alignItems: 'center', marginTop: 16 },
  actionText: { color: '#147D52', fontWeight: '700' }, back: { color: '#147D52', marginTop: 25 },
});
