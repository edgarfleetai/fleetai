import React,{useState} from 'react';
import {View,Text,TextInput,Pressable,StyleSheet,Alert,KeyboardAvoidingView,Platform} from 'react-native';
import {router} from 'expo-router';
const topics=['Ремонт автомобиля','Вопрос по оплате','Документы','Другое'];
export default function DemoSupport(){
 const [topic,setTopic]=useState(topics[0]);const [message,setMessage]=useState('');
 return <KeyboardAvoidingView style={s.page} behavior={Platform.OS==='ios'?'padding':undefined}><Text style={s.label}>🍀 КЛЕВЕР ПАРК · ДЕМО</Text><Text style={s.title}>Помощь водителю</Text><Text style={s.desc}>Показываем, как будет выглядеть обращение. Сообщения пока никуда не отправляются.</Text>
 <View style={s.tags}>{topics.map(t=><Pressable key={t} onPress={()=>setTopic(t)} style={[s.tag,t===topic&&s.active]}><Text style={[s.tagText,t===topic&&s.activeText]}>{t}</Text></Pressable>)}</View>
 <TextInput style={s.input} placeholder="Опишите ситуацию..." accessibilityLabel="Текст демонстрационного обращения" multiline textAlignVertical="top" value={message} onChangeText={setMessage} maxLength={1000}/>
 <Pressable style={[s.button,message.trim().length<5&&s.disabled]} disabled={message.trim().length<5} onPress={()=>Alert.alert('Демонстрационное обращение','Тема: '+topic+'\n\nСообщение не отправлено и не сохранено.')}><Text style={s.buttonText}>Посмотреть подтверждение</Text></Pressable>
 <Pressable onPress={()=>router.back()}><Text style={s.back}>← Назад</Text></Pressable></KeyboardAvoidingView>
}
const s=StyleSheet.create({page:{flex:1,backgroundColor:'#F5F7F6',padding:24,paddingTop:70},label:{color:'#147D52',fontWeight:'800'},title:{fontSize:29,fontWeight:'800',color:'#183329',marginTop:22},desc:{fontSize:14,lineHeight:22,color:'#718277',marginTop:12},tags:{flexDirection:'row',flexWrap:'wrap',gap:9,marginTop:25},tag:{backgroundColor:'white',padding:12,borderRadius:25},active:{backgroundColor:'#147D52'},tagText:{color:'#53675C',fontWeight:'700'},activeText:{color:'white'},input:{backgroundColor:'white',borderRadius:18,marginTop:25,padding:18,height:155,fontSize:16},button:{backgroundColor:'#147D52',borderRadius:15,padding:18,alignItems:'center',marginTop:20},disabled:{opacity:.4},buttonText:{color:'white',fontWeight:'800'},back:{color:'#147D52',marginTop:24,fontWeight:'700'}});
