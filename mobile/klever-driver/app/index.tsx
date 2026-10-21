import React from 'react';
import { ScrollView, Text, View, Pressable, StyleSheet, Alert } from 'react-native';
import { Link } from 'expo-router';
const green='#147D52';
export default function Home(){return <ScrollView style={styles.page} contentContainerStyle={styles.content}>
  <Text style={styles.logo}>🍀 Клевер Парк</Text><Text style={styles.sub}>Аренда автомобилей для работы</Text>
  <View style={styles.hero}><Text style={styles.heroTitle}>Ваша машина. Ваш маршрут.</Text><Text style={styles.heroSub}>Выбирайте автомобиль, оформляйте аренду и управляйте платежами в одном приложении.</Text></View>
  <Text style={styles.section}>Начните с регистрации</Text><Text style={styles.note}>Подтвердите телефон, документы и личность. После одобрения можно забронировать свободный автомобиль.</Text>
  <Link href="/register" asChild><Pressable style={styles.primary}><Text style={styles.primaryText}>Зарегистрироваться →</Text></Pressable></Link>
  <Link href="/dashboard" asChild><Pressable style={styles.secondary}><Text style={styles.secondaryText}>Посмотреть демо кабинета</Text></Pressable></Link>
  <Text style={styles.footer}>Демо-версия. Реальные бронирования, платежи и проверка документов пока отключены.</Text>
</ScrollView>}
const styles=StyleSheet.create({page:{flex:1,backgroundColor:'#F5F7F6'},content:{padding:24,paddingTop:72},logo:{fontSize:28,fontWeight:'800',color:'#162B23'},sub:{fontSize:14,color:'#6C7B73',marginTop:6},hero:{backgroundColor:'#123B2A',padding:24,borderRadius:24,marginTop:32,marginBottom:28},heroTitle:{fontSize:30,fontWeight:'800',color:'white'},heroSub:{color:'#D5E9DE',fontSize:16,lineHeight:24,marginTop:16},section:{fontSize:22,fontWeight:'800',color:'#162B23'},note:{fontSize:15,color:'#66776D',lineHeight:23,marginTop:12,marginBottom:22},primary:{backgroundColor:green,borderRadius:15,padding:18,alignItems:'center'},primaryText:{color:'white',fontSize:16,fontWeight:'700'},secondary:{borderWidth:1,borderColor:'#D5E0D9',borderRadius:15,padding:18,alignItems:'center',marginTop:12},secondaryText:{color:'#162B23',fontSize:15,fontWeight:'700'},footer:{fontSize:12,color:'#7A8980',marginTop:30,lineHeight:19}});
