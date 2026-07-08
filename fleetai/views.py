HTML = '''
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>FleetAI 3.0</title>
<style>
body{font-family:Arial;background:#f3f5f7;margin:0;color:#111827}.wrap{max-width:1280px;margin:auto;padding:24px}
.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:12px}
.stat{background:#111827;color:white;border-radius:14px;padding:16px}.stat b{font-size:22px;display:block;margin-top:8px}
input,select{padding:12px;font-size:16px;border:1px solid #ddd;border-radius:10px;margin:4px}input.msg{width:78%;font-size:18px}button{padding:10px 14px;font-size:15px;border:0;border-radius:10px;background:#2563eb;color:white;cursor:pointer}.danger{background:#dc2626}.small{padding:6px 9px;font-size:12px}
table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:left}.badge{padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-size:12px}.warn{background:#fff7ed;border-left:5px solid #f97316}.ok{color:#16a34a}.bad{color:#dc2626}.calendar{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.daycard{border:1px solid #e5e7eb;border-radius:14px;padding:12px;background:#f9fafb}.event{background:white;border-left:4px solid #2563eb;border-radius:10px;padding:9px;margin:8px 0;box-shadow:0 1px 6px #0001}.event.income{border-left-color:#16a34a}.event.repair,.event.service,.event.expense{border-left-color:#dc2626}.event.downtime{border-left-color:#f97316}.raw{font-size:13px;color:#6b7280}
@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}input.msg{width:100%;margin-bottom:8px}table{font-size:12px}}
</style></head><body><div class="wrap"><h1>🚗 FleetAI 3.0</h1>
<div id="summary"></div>
<div class="card"><input class="msg" id="msg" placeholder="703 получил 13000 / 703 доп расходы 41700 инвестор оплатил 25000"><button onclick="add()">Записать</button><p id="res"></p></div>
<div class="card warn"><h2>Инвесторы</h2>
<button onclick="fixInvestorData()">Исправить старые неверные расчеты</button>
<button onclick="rebuildCalculations()">Пересчитать базу</button>
<div class="card"><h3>Ручное исправление инвестора у машины</h3>
<input id="fix_code" placeholder="Код машины, например 636">
<input id="fix_name" placeholder="Правильный инвестор, например илья">
<input id="fix_percent" placeholder="%, например 75">
<button onclick="reassignInvestor()">Перекинуть машину к инвестору</button>
<p>Используй это для ошибок типа инвестор «Вложил». Сначала перекинь машину, потом нажми «Пересчитать базу».</p>
</div>
<div id="investorsSummary"></div><div id="investors"></div></div>
<div class="card"><h2>Добавить машину</h2><select id="owner_type"><option value="own">Моя машина</option><option value="investor">Машина инвестора</option></select><input id="code" placeholder="Код 777"><input id="brand" placeholder="Марка"><input id="model" placeholder="Модель"><input id="plate" placeholder="Госномер"><input id="year" placeholder="Год"><input id="purchase_date" placeholder="Дата покупки"><input id="purchase_price" placeholder="Цена покупки"><input id="mileage" placeholder="Пробег"><input id="investor_name" placeholder="Имя инвестора"><input id="investor_percent" placeholder="% инвестора"><input id="settlement_day" placeholder="Расчетный день 15"><button onclick="addCar()">Добавить авто</button><p id="carRes"></p></div>
<div class="card"><h2>Машины</h2><table id="cars"></table></div>
<div id="carCard"></div>
<div class="card"><h2>Последние операции</h2><table id="ops"></table></div></div>
<script>
async function api(u,o){let r=await fetch(u,o);return await r.json()}
function rub(n){return (n||0).toLocaleString('ru-RU')+' ₽'}
async function fixInvestorData(){let r=await api('/api/fix-investor-data',{method:'POST'});alert(r.message);await load()}
async function rebuildCalculations(){if(!confirm('Пересобрать расчеты из истории операций? Это исправит зависшие неверные суммы.')) return; let r=await api('/api/rebuild-calculations',{method:'POST'}); alert(r.message); await load()}
async function reassignInvestor(){let payload={code:fix_code.value, investor_name:fix_name.value, percent:fix_percent.value||75}; let r=await api('/api/reassign-car-investor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); alert(r.message); await load()}

async function deleteOperation(id){
  if(!confirm('Удалить операцию #' + id + '? Расчеты сразу пересчитаются.')) return;
  let r = await api('/api/delete-operation/' + id, {method:'POST'});
  alert(r.message);
  await load();
}
async function deleteCar(code){
  if(!confirm('Удалить машину ' + code + ' и ВСЕ ее записи? Это действие нельзя отменить.')) return;
  let r = await api('/api/delete-car/' + code, {method:'POST'});
  alert(r.message);
  await load();
}
async function resetCarInvestor(code){
  if(!confirm('Убрать инвестора у машины ' + code + ' и удалить связанные инвесторские записи?')) return;
  let r = await api('/api/reset-car-investor/' + code, {method:'POST'});
  alert(r.message);
  await load();
  await openCar(code);
}

async function loadSummary(){let s=await api('/api/summary');summary.innerHTML=`<div class="grid"><div class="stat">Всего <b>${s.cars}</b></div><div class="stat">Мои <b>${s.own_cars}</b></div><div class="stat">Инвесторов <b>${s.investor_cars}</b></div><div class="stat">Доход <b>${rub(s.income)}</b></div><div class="stat">Расход <b>${rub(s.expenses)}</b></div><div class="stat">Прибыль <b>${rub(s.profit)}</b></div><div class="stat">Простой <b>${s.downtime_days||0} дн.</b></div></div>`}
async function loadInvestorsSummary(){let s=await api('/api/investors-summary');investorsSummary.innerHTML=`<div class="card"><h3>Общий расчет по инвесторам</h3><div class="grid"><div class="stat">Инвесторов <b>${s.investors_count}</b></div><div class="stat">Вложили <b>${rub(s.total_invested)}</b></div><div class="stat">Выплачено <b>${rub(s.total_payouts)}</b></div><div class="stat">К выплате <b>${rub(s.available_to_pay)}</b></div><div class="stat">Долг инвесторов <b>${rub(s.investor_debt_to_park)}</b></div><div class="stat">Прибыль <b>${rub(s.profit)}</b></div><div class="stat">Доля парка <b>${rub(s.owner_share)}</b></div></div><table><tr><th>Инвестор</th><th>Машин</th><th>Вложил</th><th>Прибыль</th><th>Доля инвестора</th><th>Выплачено</th><th>К выплате</th><th>Долг инвестора</th><th>Парк должен</th></tr>${s.investors.map(i=>`<tr><td>${i.name}</td><td>${i.cars_count}</td><td>${rub(i.total_invested)}</td><td>${rub(i.profit)}</td><td>${rub(i.investor_share)}</td><td>${rub(i.total_payouts)}</td><td>${rub(i.available_to_pay)}</td><td>${rub(i.investor_debt_to_park)}</td><td>${rub(i.park_debt_to_investor)}</td></tr>`).join('')}</table></div>`}
async function loadInvestors(){let d=await api('/api/investors');if(!d.length){investors.innerHTML='Пока нет машин инвесторов';return}investors.innerHTML=d.map(i=>`<div class="card"><h3>${i.name}</h3><b>Вложил:</b> ${rub(i.total_invested)} | <b>Выплачено:</b> ${rub(i.total_payouts)} | <b>К выплате:</b> ${rub(i.available_to_pay)} | <b>Долг инвестора:</b> ${rub(i.investor_debt_to_park)}<table><tr><th>Машина</th><th>%</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Инвестору</th><th>Долг</th><th>Карточка</th></tr>${i.cars.map(c=>`<tr><td>${c.code} ${c.car}</td><td>${c.percent}%</td><td>${rub(c.income)}</td><td>${rub(c.expenses)}</td><td>${rub(c.profit)}</td><td>${rub(c.available_to_pay)}</td><td>${rub(c.investor_debt_to_park||0)}</td><td><button onclick="openCar('${c.code}')">Открыть</button></td></tr>`).join('')}</table></div>`).join('')}
async function loadCars(){let c=await api('/api/cars');cars.innerHTML='<tr><th>Тип</th><th>Код</th><th>Авто</th><th>Госномер</th><th>Инвестор</th><th>%</th><th>Стоимость</th><th>Доход</th><th>Расход</th><th>Прибыль</th><th>Расчет</th><th>Карточка</th><th>Удалить</th></tr>'+c.map(x=>`<tr><td><span class="badge">${x.owner_type==='investor'?'Инвестор':'Моя'}</span></td><td>${x.code}</td><td>${x.brand||''} ${x.model||''}</td><td>${x.plate||''}</td><td>${x.investor_name||''}</td><td>${x.investor_percent||0}</td><td>${rub(x.full_cost)}</td><td>${rub(x.income)}</td><td>${rub(x.expenses)}</td><td>${rub(x.profit)}</td><td><button onclick="openPeriod('${x.code}')">Расчет</button></td><td><button onclick="openCar('${x.code}')">Открыть</button></td><td><button class="danger small" onclick="deleteCar('${x.code}')">Удалить авто</button></td></tr>`).join('')}
function groupByDate(ops){let g={};ops.forEach(o=>{let d=(o.date||'').split(' ')[0]||'Без даты';if(!g[d])g[d]=[];g[d].push(o)});return g}
function renderCalendar(ops){let g=groupByDate(ops);return `<div class="calendar">${Object.keys(g).map(day=>`<div class="daycard"><h4>${day}</h4>${g[day].map(o=>`<div class="event ${o.type}"><b>${o.type}</b><div>${o.description||''}</div><div><b>${rub(o.amount)}</b></div><div class="raw">${o.raw||''}</div><button class="danger small" onclick="deleteOperation(${o.id})">Удалить запись</button></div>`).join('')}</div>`).join('')}</div>`}
async function openCar(code){let d=await api('/api/car/'+code);let c=d.car;let html=`<div class="card"><h2>${c.code} ${c.brand||''} ${c.model||''}</h2><p><b>Доход:</b> ${rub(c.income)} | <b>Расход:</b> ${rub(c.expenses)} | <b>Прибыль:</b> ${rub(c.profit)}</p><p><b>Инвестор:</b> ${c.investor_name||'-'} ${c.investor_percent?'('+c.investor_percent+'%)':''}</p><p><button onclick="openPeriod('${c.code}')">Расчетный период</button> <button onclick="openInvestorBalance('${c.code}')">Взаиморасчет</button> <button class="danger" onclick="resetCarInvestor('${c.code}')">Убрать инвестора</button></p></div><div class="card"><h3>Календарь изменений</h3>${renderCalendar(d.operations)}</div>`;carCard.innerHTML=html;window.scrollTo(0,carCard.offsetTop)}
async function openInvestorBalance(code){let d=await api('/api/investor-balance/'+code);let b=d.balance;carCard.innerHTML=`<div class="card warn"><h2>Взаиморасчет ${code}</h2><p><b>Доля прибыли инвестора:</b> ${rub(b.investor_share_total)}</p><p><b>Погашено долгом:</b> ${rub(b.debt_repaid_by_profit)}</p><p><b>Инвестор должен парку:</b> ${rub(b.investor_debt_to_park)}</p><p><b>Парк должен инвестору:</b> ${rub(b.park_debt_to_investor)}</p><p><b>Выплачено:</b> ${rub(b.paid_to_investor)}</p><p><b>Доступно к выплате:</b> ${rub(b.available_to_pay)}</p></div><div class="card"><h3>Журнал взаиморасчетов</h3><table><tr><th>Дата</th><th>Всего</th><th>Инвестор оплатил</th><th>Парк оплатил</th><th>Долг инвестора</th><th>Комментарий</th></tr>${d.settlements.map(x=>`<tr><td>${x.date}</td><td>${rub(x.total_cost)}</td><td>${rub(x.investor_paid)}</td><td>${rub(x.park_paid)}</td><td>${rub(x.investor_debt_to_park)}</td><td>${x.comment||''}</td></tr>`).join('')}</table></div>`;window.scrollTo(0,carCard.offsetTop)}
async function openPeriod(code){let d=await api('/api/period/'+code);let p=d.current_period;carCard.innerHTML=`<div class="card warn"><h2>Расчетный период ${code}</h2><p>${p.start_date} — ${p.end_date}</p><p>Доход: ${rub(p.income)} | Расход: ${rub(p.expenses)} | Прибыль: ${rub(p.profit)}</p><p>Инвестору: ${rub(p.investor_amount)} | Парку: ${rub(p.owner_amount)}</p><button onclick="closePeriod('${code}')">Закрыть период</button></div>`}
async function closePeriod(code){let r=await api('/api/close-period/'+code,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});alert(r.message);load();openPeriod(code)}
async function loadOps(){let o=await api('/api/operations');ops.innerHTML='<tr><th>ID</th><th>Дата</th><th>Машина</th><th>Тип</th><th>Описание</th><th>Сумма</th><th>Сообщение</th><th>Удалить</th></tr>'+o.map(x=>`<tr><td>${x.id}</td><td>${x.date}</td><td>${x.car_code}</td><td>${x.type}</td><td>${x.description||''}</td><td>${rub(x.amount)}</td><td>${x.raw||''}</td><td><button class="danger small" onclick="deleteOperation(${x.id})">Удалить</button></td></tr>`).join('')}
async function add(){let m=msg.value;try{let r=await api('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});res.innerText=r.message||JSON.stringify(r);if(r.ok)msg.value='';load()}catch(e){res.innerText='Ошибка: '+e}}
async function addCar(){let payload={owner_type:owner_type.value,code:code.value,brand:brand.value,model:model.value,plate:plate.value,year:year.value,purchase_date:purchase_date.value,purchase_price:purchase_price.value,mileage:mileage.value,investor_name:investor_name.value,investor_percent:investor_percent.value,settlement_day:settlement_day.value};let r=await api('/api/add-car',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});carRes.innerText=r.message;load()}
async function load(){await loadSummary();await loadInvestorsSummary();await loadInvestors();await loadCars();await loadOps()}
msg.addEventListener('keydown',e=>{if(e.key==='Enter')add()});load();
</script></body></html>
'''
