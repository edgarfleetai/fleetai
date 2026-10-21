import React,{useEffect,useState} from 'react';
import {ScrollView,Text,View,Pressable,ActivityIndicator,StyleSheet,Alert} from 'react-native';
import {router} from 'expo-router';
import {listVehicles,Vehicle,API_BASE_URL} from '../lib/api';
export default function Vehicles(){
 const [cars,setCars]=useState<Vehicle[]>([]);const [loading,setLoading]=useState(true);const [error,setError]=useState('');
 useEffect(()=>{let active=true;listVehicles().then(v=>{if(active)setCars(v)}).catch(e=>{if(active)setError(String(e.message||e))}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[]);
 return <ScrollView style={s.page} contentContainerStyle={s.content}><Text style={s.title}>Выберите автомобиль</Text><Text style={s.sub}>Доступные автомобили появятся после подключения безопасного каталога FleetAI.</Text>
 {loading&&<ActivityIndicator/>}{!!error&&<Text style={s.error}>{error}</Text>}
 {!loading&&cars.length===0&&<View style={s.empty}><Text style={s.emptyTitle}>Каталог пока не подключён</Text><Text style={s.sub}>Мы не показываем вымышленные машины и цены. Бронирование будет доступно после проверки личности.</Text></View>}
 {cars.map(c=><View key={c.id} style={s.card}><Text style={s.car}>{c.make} {c.model} · {c.year}</Text><Text style={s.sub}>{c.dailyRent.toLocaleString('ru-RU')} ₽/сутки · залог {c.deposit.toLocaleString('ru-RU')} ₽</Text><Text style={s.status}>{c.status==='available'?'Свободен':c.status==='reserved'?'Забронирован':'В аренде'}</Text><Pressable style={s.button} onPress={()=>Alert.alert('Бронирование ещё недоступно','Требуется регистрация, одобрение личности и подключение защищённого сервера бронирования.')}><Text style={s.buttonText}>Выбрать</Text></Pressable></View>)}
 <Pressable onPress={()=>router.back()}><Text style={s.back}>← Назад</Text></Pressable></ScrollView>
}
const s=StyleSheet.create({page:{flex:1,backgroundColor:'#F5F7F6'},content:{padding:24,paddingTop:75},title:{fontSize:28,fontWeight:'800',color:'#172A20'},sub:{color:'#728279',fontSize:15,lineHeight:22,marginTop:12},empty:{backgroundColor:'white',padding:24,borderRadius:20,marginTop:30},emptyTitle:{fontSize:19,fontWeight:'800',color:'#172A20'},error:{color:'#C33',marginTop:18},card:{backgroundColor:'white',borderRadius:18,padding:20,marginTop:16},car:{fontSize:19,fontWeight:'800'},status:{color:'#147D52',marginVertical:12},button:{backgroundColor:'#147D52',padding:14,borderRadius:12,alignItems:'center'},buttonText:{color:'white',fontWeight:'700'},back:{marginTop:28,color:'#147D52',fontWeight:'700'}});
