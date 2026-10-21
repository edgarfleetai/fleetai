import React,{useState} from 'react';
import {ScrollView,View,Text,Pressable,StyleSheet} from 'react-native';
import {router} from 'expo-router';
import {DEMO_CARS} from '../lib/demo';
export default function DemoCatalog(){
 const [filter,setFilter]=useState<'Все'|'Автомат'|'Механика'>('Все');
 const cars=DEMO_CARS.filter(c=>filter==='Все'||c.transmission===filter);
 return <ScrollView style={s.page} contentContainerStyle={s.content}>
 <Text style={s.eyebrow}>🍀 КЛЕВЕР ПАРК · ДЕМО</Text><Text style={s.title}>Найдите свою машину</Text><Text style={s.desc}>Пример оформления каталога. Автомобили и цены вымышленные, бронирование не создаётся.</Text>
 <View style={s.filters}>{(['Все','Автомат','Механика'] as const).map(f=><Pressable key={f} onPress={()=>setFilter(f)} style={[s.chip,filter===f&&s.chipActive]}><Text style={[s.chipText,filter===f&&s.chipTextActive]}>{f}</Text></Pressable>)}</View>
 {cars.map(c=><Pressable key={c.id} style={s.card} onPress={()=>router.push({pathname:'/demo-car',params:{id:c.id}})}>
 <View style={[s.carVisual,{backgroundColor:c.color}]}><Text style={s.emoji}>{c.icon}</Text><Text style={s.visualLabel}>ДЕМО АВТОМОБИЛЬ</Text></View>
 <View style={s.cardBody}><Text style={s.model}>{c.model} · {c.year}</Text><Text style={s.muted}>{c.transmission} · Для работы в такси</Text><View style={s.priceRow}><Text style={s.price}>{c.price.toLocaleString('ru-RU')} ₽ <Text style={s.per}>/ сутки</Text></Text><Text style={s.arrow}>→</Text></View></View>
 </Pressable>)}
 <Pressable onPress={()=>router.back()}><Text style={s.back}>← Главная</Text></Pressable></ScrollView>
}
const s=StyleSheet.create({page:{flex:1,backgroundColor:'#F5F7F6'},content:{padding:20,paddingTop:65,paddingBottom:40},eyebrow:{color:'#147D52',fontWeight:'800',letterSpacing:1},title:{fontSize:29,fontWeight:'800',color:'#183329',marginTop:16},desc:{color:'#697A70',fontSize:14,lineHeight:21,marginTop:10},filters:{flexDirection:'row',gap:8,marginVertical:24},chip:{paddingVertical:11,paddingHorizontal:15,backgroundColor:'white',borderRadius:25},chipActive:{backgroundColor:'#147D52'},chipText:{color:'#53675C',fontWeight:'700'},chipTextActive:{color:'white'},card:{backgroundColor:'white',borderRadius:20,marginBottom:18,overflow:'hidden'},carVisual:{height:145,alignItems:'center',justifyContent:'center'},emoji:{fontSize:68},visualLabel:{fontSize:10,fontWeight:'800',letterSpacing:1,color:'#718277'},cardBody:{padding:19},model:{fontSize:20,fontWeight:'800',color:'#183329'},muted:{fontSize:13,color:'#718277',marginTop:7},priceRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',marginTop:19},price:{fontSize:21,fontWeight:'800',color:'#147D52'},per:{fontSize:12,fontWeight:'500',color:'#718277'},arrow:{fontSize:26,color:'#147D52'},back:{color:'#147D52',fontWeight:'700',marginTop:15}});
