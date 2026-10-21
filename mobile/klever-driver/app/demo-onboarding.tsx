import React,{useState} from 'react';
import {ScrollView,View,Text,Pressable,StyleSheet,TextInput,KeyboardAvoidingView,Platform} from 'react-native';
import {router} from 'expo-router';
type Stage='phone'|'otp'|'documents'|'selfie'|'review';
const stages:Stage[]=['phone','otp','documents','selfie','review'];
const titles:Record<Stage,string>={phone:'Ваш номер телефона',otp:'Подтверждение номера',documents:'Документы водителя',selfie:'Подтверждение личности',review:'Заявка отправлена'};
const descriptions:Record<Stage,string>={
 phone:'Укажите номер, на который придёт код подтверждения.',
 otp:'Введите код из SMS. Здесь используется только демонстрационный сценарий.',
 documents:'Для реальной регистрации понадобятся паспорт и водительское удостоверение.',
 selfie:'В рабочем приложении потребуется селфи с проверкой живого человека.',
 review:'В демонстрации заявка не передаётся и документы не сохраняются.',
};
export default function DemoOnboarding(){
 const [step,setStep]=useState(0);const [phone,setPhone]=useState('');const [code,setCode]=useState('');
 const stage=stages[step];const done=stage==='review';
 const canContinue=stage==='phone'?phone.replace(/\D/g,'').length>=10:stage==='otp'?code.length>=4:true;
 return <KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==='ios'?'padding':undefined}><ScrollView style={s.page} contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">
 <Text style={s.brand}>🍀 КЛЕВЕР ПАРК · ДЕМО</Text><View style={s.progress}>{stages.map((_,i)=><View key={i} style={[s.segment,i<=step&&s.active]}/>)}</View>
 <Text style={s.count}>ШАГ {step+1} ИЗ {stages.length}</Text><Text style={s.title}>{titles[stage]}</Text><Text style={s.desc}>{descriptions[stage]}</Text>
 {stage==='phone'&&<TextInput style={s.input} placeholder="+7 999 123-45-67" accessibilityLabel="Демо номер телефона" keyboardType="phone-pad" value={phone} onChangeText={setPhone} maxLength={20}/>}
 {stage==='otp'&&<><TextInput style={s.input} placeholder="Любые 4 цифры для демо" accessibilityLabel="Демо SMS-код" keyboardType="number-pad" value={code} onChangeText={v=>setCode(v.replace(/\D/g,'').slice(0,6))} maxLength={6}/><Text style={s.warning}>SMS не отправляется. Введённый код не проверяется сервером.</Text></>}
 {stage==='documents'&&<View style={s.info}><Text style={s.infoTitle}>📄 Паспорт и права</Text><Text style={s.infoText}>В демо загрузка файлов отключена. Фотографии документов не запрашиваются.</Text></View>}
 {stage==='selfie'&&<View style={s.info}><Text style={s.infoTitle}>📷 Селфи и проверка живого человека</Text><Text style={s.infoText}>Камера в демонстрации не запускается, биометрические данные не собираются.</Text></View>}
 {done&&<View style={s.success}><Text style={s.successTitle}>✓ Демонстрация завершена</Text><Text style={s.infoText}>Вы просмотрели все этапы регистрации. Реальный статус водителя не изменился.</Text></View>}
 <Pressable style={[s.button,!canContinue&&s.disabled]} disabled={!canContinue} onPress={()=>done?router.replace('/demo-catalog'):setStep(step+1)}><Text style={s.buttonText}>{done?'Перейти в каталог':'Продолжить →'}</Text></Pressable>
 {step>0&&!done&&<Pressable onPress={()=>setStep(step-1)}><Text style={s.back}>← Предыдущий шаг</Text></Pressable>}
 <Pressable onPress={()=>router.back()}><Text style={s.back}>На главную</Text></Pressable>
 </ScrollView></KeyboardAvoidingView>
}
const s=StyleSheet.create({page:{flex:1,backgroundColor:'#F5F7F6'},content:{padding:24,paddingTop:70,paddingBottom:55},brand:{color:'#147D52',fontWeight:'800',letterSpacing:1},progress:{flexDirection:'row',gap:7,marginTop:25,marginBottom:36},segment:{height:5,flex:1,backgroundColor:'#D9E3DC',borderRadius:6},active:{backgroundColor:'#147D52'},count:{color:'#147D52',fontSize:12,fontWeight:'800',letterSpacing:1},title:{fontSize:29,fontWeight:'800',color:'#183329',marginTop:12},desc:{fontSize:15,lineHeight:23,color:'#6E8074',marginTop:14,marginBottom:24},input:{backgroundColor:'white',borderRadius:14,borderWidth:1,borderColor:'#DCE5DE',padding:18,fontSize:18},warning:{fontSize:12,color:'#9B6B28',marginTop:12},info:{backgroundColor:'white',padding:24,borderRadius:20},infoTitle:{fontSize:19,fontWeight:'800',color:'#183329'},infoText:{fontSize:14,lineHeight:22,color:'#6E8074',marginTop:12},success:{backgroundColor:'#E1F4E9',padding:24,borderRadius:20},successTitle:{color:'#147D52',fontWeight:'800',fontSize:19},button:{backgroundColor:'#147D52',padding:18,borderRadius:15,alignItems:'center',marginTop:30},disabled:{opacity:.4},buttonText:{color:'white',fontSize:16,fontWeight:'800'},back:{marginTop:22,color:'#147D52',fontWeight:'700'}});
