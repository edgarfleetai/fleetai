import React,{useState} from 'react';
import {View,Text,ScrollView,Pressable,StyleSheet} from 'react-native';
import {useLocalSearchParams,router} from 'expo-router';
import {DEMO_CARS} from '../lib/demo';
export default function DemoCar(){
 const {id}=useLocalSearchParams<{id:string}>();const car=DEMO_CARS.find(c=>c.id===id);const [reserved,setReserved]=useState(false);
 if(!car)return <View style={s.page}><Text>Автомобиль не найден</Text><Pressable onPress={()=>router.back()}><Text>Назад</Text></Pressable></View>;
 return <ScrollView style={s.page} contentContainerStyle={s.content}><Pressable onPress={()=>router.back()}><Text style={s.back}>← Каталог</Text></Pressable>
 <View style={[s.visual,{backgroundColor:car.color}]}><Text style={s.emoji}>{car.icon}</Text><Text style={s.tag}>ДЕМОНСТРАЦИЯ</Text></View>
 <Text style={s.title}>{car.model}</Text><Text style={s.subtitle}>{car.year} год · {car.transmission}</Text>
 <View style={s.card}><Text style={s.cardTitle}>Условия аренды</Text><Text style={s.line}>Аренда: {car.price.toLocaleString('ru-RU')} ₽ / сутки</Text><Text style={s.line}>Залог: {car.deposit.toLocaleString('ru-RU')} ₽</Text><Text style={s.line}>Оформление после проверки личности</Text></View>
 {reserved?<View style={s.notice}><Text style={s.noticeTitle}>✓ Демонстрационная бронь</Text><Text style={s.subtitle}>Это только пример интерфейса. Автомобиль не забронирован, оплата не списана.</Text><Pressable onPress={()=>setReserved(false)}><Text style={s.back}>Сбросить демонстрацию</Text></Pressable></View>:
 <Pressable style={s.button} onPress={()=>setReserved(true)}><Text style={s.buttonText}>Показать процесс бронирования</Text></Pressable>}
 </ScrollView>
}
const s=StyleSheet.create({page:{flex:1,backgroundColor:'#F5F7F6'},content:{padding:24,paddingTop:65},back:{color:'#147D52',fontWeight:'700',marginBottom:22},visual:{height:220,borderRadius:24,justifyContent:'center',alignItems:'center'},emoji:{fontSize:105},tag:{fontSize:11,color:'#718277',fontWeight:'800',letterSpacing:1},title:{fontSize:29,fontWeight:'800',marginTop:24,color:'#183329'},subtitle:{fontSize:15,color:'#718277',marginTop:8,lineHeight:22},card:{backgroundColor:'white',padding:22,borderRadius:20,marginTop:25},cardTitle:{fontSize:19,fontWeight:'800',color:'#183329'},line:{fontSize:15,color:'#53675C',marginTop:15},button:{backgroundColor:'#147D52',padding:19,borderRadius:16,alignItems:'center',marginTop:26},buttonText:{color:'white',fontWeight:'800'},notice:{backgroundColor:'#E1F4E9',padding:22,borderRadius:20,marginTop:26},noticeTitle:{color:'#147D52',fontSize:19,fontWeight:'800'}});
