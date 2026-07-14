HTML = '''
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FleetAI 3.0</title>

<style>
body{font-family:Arial;background:#f3f5f7;margin:0;color:#111827}
.wrap{max-width:1280px;margin:auto;padding:24px}
.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.stat{background:#111827;color:white;border-radius:14px;padding:16px}
.stat b{font-size:22px;display:block;margin-top:8px}
input,select{padding:12px;font-size:16px;border:1px solid #ddd;border-radius:10px;margin:4px}
input.msg{width:78%;font-size:18px}
button{padding:10px 14px;font-size:15px;border:0;border-radius:10px;background:#2563eb;color:white;cursor:pointer}
.danger{background:#dc2626}
.small{padding:6px 9px;font-size:12px}
table{width:100%;border-collapse:collapse}
td,th{padding:9px;border-bottom:1px solid #eee;text-align:left}
.badge{padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#0369a1;font-size:12px}
.warn{background:#fff7ed;border-left:5px solid #f97316}
.ok{color:#16a34a}
.bad{color:#dc2626}
.calendar{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.daycard{border:1px solid #e5e7eb;border-radius:14px;padding:12px;background:#f9fafb}
.event{background:white;border-left:4px solid #2563eb;border-radius:10px;padding:9px;margin:8px 0;box-shadow:0 1px 6px #0001}
.event.income{border-left-color:#16a34a}
.event.repair,.event.service,.event.expense{border-left-color:#dc2626}
.event.downtime{border-left-color:#f97316}
.raw{font-size:13px;color:#6b7280}
.payment-form{display:grid;grid-template-columns:repeat(5,minmax(160px,1fr));gap:8px;align-items:end}

.investor-summary-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:14px 0}
.investor-kpi{background:#111827;color:white;border-radius:16px;padding:16px}
.investor-kpi span{display:block;font-size:13px;color:#cbd5e1}
.investor-kpi b{display:block;font-size:22px;margin-top:7px}
.investor-list{display:grid;gap:12px}
.investor-card{border:1px solid #e5e7eb;border-radius:18px;background:#fff;overflow:hidden}
.investor-head{padding:18px}
.investor-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.investor-name{font-size:21px;font-weight:700}
.investor-meta{font-size:13px;color:#6b7280;margin-top:4px}
.investor-money{font-size:25px;font-weight:800;text-align:right}
.investor-money small{display:block;font-size:12px;font-weight:400;color:#6b7280}
.investor-flow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:16px}
.flow-item{background:#f8fafc;border-radius:12px;padding:11px}
.flow-item span{display:block;font-size:12px;color:#64748b}
.flow-item b{display:block;margin-top:5px}
.investor-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.secondary{background:#e5e7eb;color:#111827}
.investor-cars{display:none;border-top:1px solid #e5e7eb;padding:8px 18px 18px}
.investor-cars.open{display:block}
.car-mini{display:grid;grid-template-columns:minmax(160px,1.4fr) repeat(4,minmax(110px,1fr)) auto;gap:10px;align-items:center;padding:14px 0;border-bottom:1px solid #f1f5f9}
.car-mini:last-child{border-bottom:0}
.car-title{font-weight:700}
.car-sub{font-size:12px;color:#64748b;margin-top:3px}
.metric span{display:block;font-size:11px;color:#64748b}
.metric b{display:block;margin-top:4px;font-size:14px}
.positive{color:#15803d}
.negative{color:#b91c1c}
.admin-tools{margin:12px 0}
.admin-tools summary{cursor:pointer;color:#64748b;font-weight:600}

.top-actions{display:flex;justify-content:flex-end;gap:8px;margin:10px 0 16px}
.icon-button{width:44px;height:44px;border-radius:50%;font-size:26px;line-height:1;padding:0;display:flex;align-items:center;justify-content:center}
.collapsible-panel{display:none}
.collapsible-panel.open{display:block}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.section-toggle{background:#e5e7eb;color:#111827}
.car-list-wrap{display:none;margin-top:12px}
.car-list-wrap.open{display:block}
.add-car-grid{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:8px}

.warehouse-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-top:14px}
.warehouse-item{border:1px solid #e5e7eb;border-radius:14px;padding:14px;background:#fff}
.warehouse-item.low{border-color:#f97316;background:#fff7ed}
.warehouse-name{font-weight:700;font-size:16px}
.warehouse-stock{font-size:24px;font-weight:800;margin:8px 0}
.warehouse-form{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:8px;align-items:end}
.warehouse-restock{display:grid;grid-template-columns:2fr 1fr 2fr auto;gap:8px;align-items:end;margin-top:12px}

.status-board{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}
.status-column{border:1px solid #e5e7eb;border-radius:16px;padding:14px;background:#fff}
.status-column.downtime{border-color:#fdba74;background:#fff7ed}
.status-title{display:flex;justify-content:space-between;align-items:center;font-weight:800;margin-bottom:10px}
.status-list{display:flex;flex-wrap:wrap;gap:8px}
.car-status-chip{border-radius:12px;padding:9px 11px;background:#f1f5f9;cursor:pointer;border:1px solid transparent}
.car-status-chip:hover{border-color:#94a3b8}
.car-status-chip strong{display:block;font-size:14px}
.car-status-chip span{display:block;font-size:11px;color:#64748b;margin-top:3px}
.car-status-chip.off{background:#ffedd5}
.status-ok{color:#15803d}
.status-off{color:#c2410c}
.badge-working{background:#dcfce7;color:#166534}
.badge-downtime{background:#ffedd5;color:#9a3412}

.command-box{position:relative;display:flex;gap:8px;align-items:flex-start}
.command-box .msg{flex:1}
.warehouse-suggestions{
  position:absolute;
  left:0;
  right:100px;
  top:48px;
  z-index:50;
  display:none;
  max-height:300px;
  overflow:auto;
  border:1px solid #d1d5db;
  border-radius:14px;
  background:#fff;
  box-shadow:0 12px 30px rgba(15,23,42,.16);
}
.warehouse-suggestions.open{display:block}
.warehouse-suggestion{
  display:flex;
  justify-content:space-between;
  gap:12px;
  padding:12px 14px;
  border-bottom:1px solid #f1f5f9;
  cursor:pointer;
}
.warehouse-suggestion:last-child{border-bottom:0}
.warehouse-suggestion:hover,
.warehouse-suggestion.active{background:#f8fafc}
.warehouse-suggestion-name{font-weight:700}
.warehouse-suggestion-meta{font-size:12px;color:#64748b;margin-top:3px}
.warehouse-suggestion-stock{
  white-space:nowrap;
  font-weight:800;
}
.warehouse-suggestion-stock.low{color:#c2410c}
.warehouse-hint{
  padding:10px 14px;
  font-size:12px;
  color:#64748b;
  background:#f8fafc;
}
@media(max-width:800px){
  .command-box{display:block}
  .command-box button{width:100%;margin-top:8px}
  .warehouse-suggestions{right:0;top:46px}
}

@media(max-width:800px){
  .status-board{grid-template-columns:1fr}
}

@media(max-width:800px){
  .warehouse-form,.warehouse-restock{grid-template-columns:1fr}
}

@media(max-width:800px){
  .add-car-grid{grid-template-columns:1fr}
  .top-actions{justify-content:flex-end}
}

@media(max-width:800px){
  .investor-summary-grid{grid-template-columns:1fr 1fr}
  .investor-flow{grid-template-columns:1fr 1fr}
  .car-mini{grid-template-columns:1fr 1fr}
  .car-mini .car-title{grid-column:1/-1}
  .car-mini button{width:100%}
}

@media(max-width:800px){
  .grid{grid-template-columns:1fr 1fr}
  .payment-form{grid-template-columns:1fr}
  input.msg{width:100%;margin-bottom:8px}
  table{font-size:12px}
}
</style>
</head>

<body>
<div class="wrap">
<h1>🚕 FleetAI 3.0</h1>

<div class="top-actions">
  <button
    class="icon-button"
    onclick="toggleAddCarForm()"
    title="Добавить машину"
  >
    +
  </button>
</div>

<div id="summary"></div>
<div id="fleetStatus"></div>

<div class="card">
  <div class="command-box">
    <input
      class="msg"
      id="msg"
      autocomplete="off"
      placeholder="703 получил 13000 / 665 замена стойки стаба цена 1000"
    >
    <button onclick="add()">Записать</button>

    <div id="warehouseSuggestions" class="warehouse-suggestions"></div>
  </div>

  <p id="res"></p>
</div>

<div class="card">
  <h2>Инвесторы</h2>
  <p class="raw">Главное: сколько начислено, удержано и осталось выплатить.</p>

  <details class="admin-tools">
    <summary>Служебные инструменты</summary>
    <div class="card warn">
      <button onclick="fixInvestorData()">Исправить старые расчёты</button>
      <button onclick="rebuildCalculations()">Пересчитать базу</button>

      <h3>Исправление инвестора у машины</h3>
      <input id="fix_code" placeholder="Код машины">
      <input id="fix_name" placeholder="Имя инвестора">
      <input id="fix_percent" placeholder="Процент">
      <button onclick="reassignInvestor()">Сохранить</button>
    </div>
  </details>

  <div id="investorsSummary"></div>
  <div id="investors"></div>
</div>

<div class="card">
  <div class="section-head">
    <div>
      <h2>Расчёты водителей</h2>
      <p class="raw">График оплат и настройка уведомлений.</p>
    </div>

    <button
      id="paymentsToggleButton"
      class="section-toggle"
      onclick="togglePaymentsPanel()"
    >
      Открыть
    </button>
  </div>

  <div id="paymentsPanel" class="collapsible-panel">
    <div class="payment-form">
      <label>Машина
        <select id="payment_car">
          <option value="">Выбери машину</option>
        </select>
      </label>

      <label>Водитель
        <input id="payment_driver" placeholder="Имя водителя">
      </label>

      <label>Сумма за неделю
        <input id="payment_amount" type="number" min="0" placeholder="13000">
      </label>

      <label>День расчёта
        <select id="payment_weekday">
          <option value="0">Понедельник</option>
          <option value="1">Вторник</option>
          <option value="2">Среда</option>
          <option value="3">Четверг</option>
          <option value="4">Пятница</option>
          <option value="5">Суббота</option>
          <option value="6">Воскресенье</option>
        </select>
      </label>

      <label>Ближайшая дата оплаты
        <input id="payment_date" type="date">
      </label>
    </div>

    <button onclick="saveDriverPayment()">Сохранить расчёт</button>
    <button class="secondary" onclick="checkPaymentsNow()">
      Проверить уведомления
    </button>

    <p id="paymentRes"></p>

    <h3>График платежей</h3>
    <table id="driverPayments"></table>
  </div>
</div>

<div id="addCarPanel" class="card collapsible-panel">
  <div class="section-head">
    <h2>Добавить машину</h2>
    <button class="secondary" onclick="toggleAddCarForm()">Закрыть</button>
  </div>

  <div class="add-car-grid">
    <select id="owner_type">
      <option value="own">Моя машина</option>
      <option value="investor">Машина инвестора</option>
    </select>
    <input id="code" placeholder="Код 777">
    <input id="brand" placeholder="Марка">
    <input id="model" placeholder="Модель">
    <input id="plate" placeholder="Госномер">
    <input id="year" placeholder="Год">
    <input id="purchase_date" placeholder="Дата покупки">
    <input id="purchase_price" placeholder="Цена покупки">
    <input id="mileage" placeholder="Пробег">
    <input id="investor_name" placeholder="Имя инвестора">
    <input id="investor_percent" placeholder="% инвестора">
    <input id="settlement_day" placeholder="Расчётный день 15">
  </div>

  <button onclick="addCar()">Добавить авто</button>
  <p id="carRes"></p>
</div>

<div class="card">
  <div class="section-head">
    <div>
      <h2>Склад</h2>
      <p class="raw">Остатки деталей и автоматическое списание по команде «со склада».</p>
    </div>
    <button
      id="warehouseToggleButton"
      class="section-toggle"
      onclick="toggleWarehousePanel()"
    >
      Открыть
    </button>
  </div>

  <div id="warehousePanel" class="collapsible-panel">
    <h3>Новая позиция</h3>

    <div class="warehouse-form">
      <input id="warehouse_part" placeholder="Название детали">
      <input id="warehouse_brand" placeholder="Бренд, например AMD">
      <input id="warehouse_quantity" type="number" min="0" placeholder="Количество">
      <input id="warehouse_min" type="number" min="0" placeholder="Минимум">
      <input id="warehouse_shelf" placeholder="Полка">
      <button onclick="addWarehouseItem()">Добавить</button>
    </div>

    <p id="warehouseRes"></p>

    <h3>Приход</h3>

    <div class="warehouse-restock">
      <select id="warehouse_restock_item">
        <option value="">Выбери деталь</option>
      </select>
      <input id="warehouse_restock_quantity" type="number" min="1" placeholder="Количество">
      <input id="warehouse_restock_comment" placeholder="Комментарий">
      <button onclick="restockWarehouse()">Записать</button>
    </div>

    <div id="warehouseItems" class="warehouse-grid"></div>
  </div>
</div>

<div class="card">
  <div class="section-head">
    <div>
      <h2>Машины</h2>
      <p class="raw">Список скрыт, чтобы не перегружать страницу.</p>
    </div>
    <button class="section-toggle" onclick="toggleCarsList()">
      Показать список
    </button>
  </div>

  <div id="carsListWrap" class="car-list-wrap">
    <table id="cars"></table>
  </div>
</div>
<div id="carCard"></div>
<div class="card"><h2>Последние операции</h2><table id="ops"></table></div>
</div>

<script>
async function api(u,o){
  const r = await fetch(u,o);
  const data = await r.json();
  return data;
}

function rub(n){return (n||0).toLocaleString('ru-RU')+' ₽'}

async function fixInvestorData(){let r=await api('/api/fix-investor-data',{method:'POST'});alert(r.message);await load()}
async function rebuildCalculations(){if(!confirm('Пересобрать расчеты из истории операций? Это исправит зависшие неверные суммы.')) return; let r=await api('/api/rebuild-calculations',{method:'POST'});alert(r.message);await load()}
async function reassignInvestor(){let payload={code:fix_code.value,investor_name:fix_name.value,percent:fix_percent.value||75};let r=await api('/api/reassign-car-investor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});alert(r.message);await load()}

async function deleteOperation(id){
  if(!confirm('Удалить операцию #' + id + '? Расчеты сразу пересчитаются.')) return;
  let r=await api('/api/delete-operation/' + id,{method:'POST'});
  alert(r.message);
  await load();
}

async function deleteCar(code){
  if(!confirm('Удалить машину ' + code + ' и ВСЕ ее записи? Это действие нельзя отменить.')) return;
  let r=await api('/api/delete-car/' + code,{method:'POST'});
  alert(r.message);
  await load();
}

async function resetCarInvestor(code){
  if(!confirm('Убрать инвестора у машины ' + code + ' и удалить связанные инвесторские записи?')) return;
  let r=await api('/api/reset-car-investor/' + code,{method:'POST'});
  alert(r.message);
  await load();
  await openCar(code);
}

async function loadSummary(){
  let s=await api('/api/summary');

  summary.innerHTML=`
    <div class="grid">
      <div class="stat">Всего машин <b>${s.cars}</b></div>
      <div class="stat">Работают <b>${s.working_cars||0}</b></div>
      <div class="stat">В простое <b>${s.downtime_cars||0}</b></div>
      <div class="stat">Доход <b>${rub(s.income)}</b></div>
      <div class="stat">Прибыль <b>${rub(s.profit)}</b></div>
    </div>
  `;

  const downtimeList=Array.isArray(s.downtime_list)
    ? s.downtime_list
    : [];
  const workingList=Array.isArray(s.working_list)
    ? s.working_list
    : [];

  fleetStatus.innerHTML=`
    <div class="status-board">
      <div class="status-column downtime">
        <div class="status-title">
          <span class="status-off">В простое сейчас</span>
          <b>${downtimeList.length}</b>
        </div>

        <div class="status-list">
          ${downtimeList.length
            ? downtimeList.map(car=>`
                <div
                  class="car-status-chip off"
                  onclick="openCar('${car.code}')"
                >
                  <strong>${car.code} ${car.brand||''} ${car.model||''}</strong>
                  <span>
                    с ${car.start_date} · ${car.days} дн.
                    ${car.reason?` · ${car.reason}`:''}
                  </span>
                </div>
              `).join('')
            : '<span class="raw">Сейчас все машины работают</span>'
          }
        </div>
      </div>

      <div class="status-column">
        <div class="status-title">
          <span class="status-ok">Активно работают</span>
          <b>${workingList.length}</b>
        </div>

        <div class="status-list">
          ${workingList.map(car=>`
            <div
              class="car-status-chip"
              onclick="openCar('${car.code}')"
            >
              <strong>${car.code} ${car.brand||''} ${car.model||''}</strong>
              <span>${car.plate||'Работает'}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

async function loadInvestorsSummary(){
  investorsSummary.innerHTML='';
}

function toggleInvestorCars(id){
  document.getElementById(id)?.classList.toggle('open');
}

async function sendInvestorReport(name){
  const encoded=encodeURIComponent(name);
  const r=await api('/api/test-investor-report/'+encoded);
  alert(r.message||'Готово');
}

async function loadInvestors(){
  const data=await api('/api/investors');

  if(!Array.isArray(data)){
    investors.innerHTML=`<p class="bad">${data.message||'Ошибка загрузки инвесторов'}</p>`;
    return;
  }

  if(!data.length){
    investors.innerHTML='<p class="raw">Пока нет машин инвесторов.</p>';
    return;
  }

  const totalPay=data.reduce((s,i)=>s+(i.available_to_pay||0),0);
  const totalDebt=data.reduce((s,i)=>s+(i.investor_debt_to_park||0),0);
  const totalAccrued=data.reduce((s,i)=>s+(i.total_accrued||0),0);
  const totalProfitForSplit=data.reduce((s,i)=>s+(i.total_profit_for_split||0),0);

  investorsSummary.innerHTML=`
    <div class="investor-summary-grid">
      <div class="investor-kpi"><span>Инвесторов</span><b>${data.length}</b></div>
      <div class="investor-kpi"><span>Прибыль до разделения</span><b>${rub(totalProfitForSplit)}</b></div>
      <div class="investor-kpi"><span>Начислено инвесторам</span><b>${rub(totalAccrued)}</b></div>
      <div class="investor-kpi"><span>К выплате</span><b>${rub(totalPay)}</b></div>
      <div class="investor-kpi"><span>Долг инвесторов</span><b>${rub(totalDebt)}</b></div>
    </div>
  `;

  investors.innerHTML=`<div class="investor-list">${data.map((i,index)=>{
    const carsId='investorCars'+index;
    const withheld=i.total_withheld||0;

    return `
      <div class="investor-card">
        <div class="investor-head">
          <div class="investor-top">
            <div>
              <div class="investor-name">${i.name}</div>
              <div class="investor-meta">${i.cars.length} машин · доля парка ${rub(i.total_park_share||0)}</div>
            </div>
            <div class="investor-money">
              ${rub(i.available_to_pay||0)}
              <small>осталось выплатить</small>
            </div>
          </div>

          <div class="investor-flow">
            <div class="flow-item">
              <span>Прибыль до разделения</span>
              <b>${rub(i.total_profit_for_split||0)}</b>
            </div>
            <div class="flow-item">
              <span>Начислено инвестору</span>
              <b>${rub(i.total_accrued||0)}</b>
            </div>
            <div class="flow-item">
              <span>Удержано</span>
              <b>${rub(withheld)}</b>
            </div>
            <div class="flow-item">
              <span>Выплачено</span>
              <b>${rub(i.total_payouts||0)}</b>
            </div>
            <div class="flow-item">
              <span>Долг</span>
              <b class="${(i.investor_debt_to_park||0)>0?'negative':''}">
                ${rub(i.investor_debt_to_park||0)}
              </b>
            </div>
          </div>

          <div class="investor-actions">
            <button onclick="toggleInvestorCars('${carsId}')">Машины</button>
            <button class="secondary" onclick="sendInvestorReport('${String(i.name).replace(/'/g,"\\'")}')">Отправить отчёт</button>
          </div>
        </div>

        <div id="${carsId}" class="investor-cars">
          ${i.cars.map(c=>`
            <div class="car-mini">
              <div class="car-title">
                ${c.code} ${c.car||''}
                <div class="car-sub">${c.percent||0}% инвестора</div>
              </div>

              <div class="metric">
                <span>Доход</span>
                <b>${rub(c.income||0)}</b>
              </div>

              <div class="metric">
                <span>Расходы</span>
                <b>${rub((c.shared_expenses||0)+(c.investor_only_expenses||0)+(c.park_only_expenses||0))}</b>
              </div>

              <div class="metric">
                <span>Прибыль до разделения</span>
                <b>${rub(c.profit_for_split||0)}</b>
              </div>

              <div class="metric">
                <span>Начислено инвестору</span>
                <b>${rub(c.accrued_to_investor||0)}</b>
              </div>

              <div class="metric">
                <span>К выплате</span>
                <b class="${(c.available_to_pay||0)>0?'positive':''}">
                  ${rub(c.available_to_pay||0)}
                </b>
                ${(c.withheld||0)>0?`<div class="car-sub">удержано ${rub(c.withheld)}</div>`:''}
              </div>

              <button class="small" onclick="openCar('${c.code}')">Открыть</button>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }).join('')}</div>`;
}

let paymentCars=[];

function paymentStatus(nextDate){
  if(!nextDate)return '<span class="badge">Не настроено</span>';
  const today=new Date();today.setHours(0,0,0,0);
  const payDate=new Date(nextDate+'T00:00:00');
  const diff=Math.round((payDate-today)/86400000);
  if(diff<0)return `<span class="bad">Просрочка ${Math.abs(diff)} дн.</span>`;
  if(diff===0)return '<span class="bad">Сегодня</span>';
  if(diff===1)return '<span class="warn">Завтра</span>';
  return `<span class="ok">Через ${diff} дн.</span>`;
}

function fillPaymentCarSelect(carsList){
  const selected=payment_car.value;
  paymentCars=carsList;
  payment_car.innerHTML='<option value="">Выбери машину</option>'+carsList.map(car=>`<option value="${car.code}">${car.code} ${car.brand||''} ${car.model||''}</option>`).join('');
  if(carsList.some(car=>car.code===selected))payment_car.value=selected;
}

payment_car.addEventListener('change',()=>{
  const car=paymentCars.find(item=>item.code===payment_car.value);
  if(!car){
    payment_driver.value='';
    payment_amount.value='';
    payment_date.value='';
    payment_weekday.value='0';
    return;
  }
  payment_driver.value=car.driver||'';
  payment_amount.value=car.weekly_payment||'';
  payment_date.value=car.next_payment_date||'';
  payment_weekday.value=String(car.payment_weekday||0);
});

async function saveDriverPayment(){
  if(!payment_car.value){paymentRes.innerText='Сначала выбери машину';return}
  if(!payment_amount.value){paymentRes.innerText='Укажи сумму недельного платежа';return}
  if(!payment_date.value){paymentRes.innerText='Укажи ближайшую дату оплаты';return}

  const payload={
    car_code:payment_car.value,
    driver:payment_driver.value,
    weekly_payment:Number(payment_amount.value),
    payment_weekday:Number(payment_weekday.value),
    next_payment_date:payment_date.value
  };

  const result=await api('/api/payment-settings',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });

  paymentRes.innerText=result.message||'Настройки сохранены';
  if(result.ok)await loadCars();
}

async function markPaymentPaid(code){
  if(!confirm(`Подтвердить получение оплаты от машины ${code}?`))return;
  const result=await api('/api/mark-driver-payment-paid',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({car_code:code})
  });
  alert(result.message);
  if(result.ok)await loadCars();
}

async function checkPaymentsNow(){
  paymentRes.innerText='Проверяем платежи...';
  const result=await api('/api/check-driver-payments');
  paymentRes.innerText=result.message||'Проверка завершена';
}

function renderDriverPayments(carsList){
  const configured=carsList.filter(car=>Number(car.weekly_payment)>0);
  if(!configured.length){
    driverPayments.innerHTML='<tr><td>Расчёты водителей пока не настроены</td></tr>';
    return;
  }
  driverPayments.innerHTML=`<tr><th>Машина</th><th>Водитель</th><th>Сумма</th><th>Следующая оплата</th><th>Статус</th><th>Действие</th></tr>${configured.map(car=>`<tr><td>${car.code}</td><td>${car.driver||'Не указан'}</td><td>${rub(car.weekly_payment)}</td><td>${car.next_payment_date||'—'}</td><td>${paymentStatus(car.next_payment_date)}</td><td><button onclick="markPaymentPaid('${car.code}')">Оплачено</button></td></tr>`).join('')}`;
}

async function loadCars(){
  let c=await api('/api/cars');

  fillPaymentCarSelect(c);
  renderDriverPayments(c);

  cars.innerHTML=`
    <tr>
      <th>Статус</th>
      <th>Тип</th>
      <th>Код</th>
      <th>Авто</th>
      <th>Госномер</th>
      <th>Пробег</th>
      <th>Инвестор</th>
      <th>%</th>
      <th>Доход</th>
      <th>Расход</th>
      <th>Прибыль</th>
      <th>Действия</th>
    </tr>
    ${c.map(x=>`
      <tr>
        <td>
          <span class="badge ${x.is_in_downtime?'badge-downtime':'badge-working'}">
            ${x.current_status}
          </span>
          ${x.is_in_downtime?`
            <div class="raw">
              ${x.current_downtime_days} дн.
              ${x.downtime_reason?` · ${x.downtime_reason}`:''}
            </div>
          `:''}
        </td>
        <td>
          <span class="badge">
            ${x.owner_type==='investor'?'Инвестор':'Моя'}
          </span>
        </td>
        <td>${x.code}</td>
        <td>${x.brand||''} ${x.model||''}</td>
        <td>${x.plate||''}</td>
        <td>${x.mileage?Number(x.mileage).toLocaleString('ru-RU')+' км':'—'}</td>
        <td>${x.investor_name||''}</td>
        <td>${x.investor_percent||0}</td>
        <td>${rub(x.income)}</td>
        <td>${rub(x.expenses)}</td>
        <td>${rub(x.profit)}</td>
        <td>
          <button onclick="openCar('${x.code}')">Открыть</button>
          <button onclick="openPeriod('${x.code}')">Расчёт</button>
          <button class="danger small" onclick="deleteCar('${x.code}')">
            Удалить
          </button>
        </td>
      </tr>
    `).join('')}
  `;
}

function groupByDate(ops){let g={};ops.forEach(o=>{let d=(o.date||'').split(' ')[0]||'Без даты';if(!g[d])g[d]=[];g[d].push(o)});return g}
function renderCalendar(ops){
  let g=groupByDate(ops);
  return `<div class="calendar">${
    Object.keys(g).map(day=>`
      <div class="daycard">
        <h4>${day}</h4>
        ${g[day].map(o=>`
          <div class="event ${o.type}">
            <b>${o.type}</b>
            <div>${o.description||''}</div>
            <div><b>${rub(o.amount)}</b></div>
            ${o.mileage?`
              <div class="raw">
                Пробег: ${Number(o.mileage).toLocaleString('ru-RU')} км
              </div>
            `:''}
            <div class="raw">${o.raw||''}</div>
            <button
              class="danger small"
              onclick="deleteOperation(${o.id})"
            >
              Удалить запись
            </button>
          </div>
        `).join('')}
      </div>
    `).join('')
  }</div>`;
}

async function openCar(code){
  let d=await api('/api/car/'+code);
  let c=d.car;

  const statusBlock=c.is_in_downtime
    ? `
      <div class="card warn">
        <h3>🟠 Машина сейчас в простое</h3>
        <p>
          <b>Начало:</b> ${c.downtime_start||'—'}
          | <b>Дней:</b> ${c.current_downtime_days||0}
        </p>
        <p><b>Причина:</b> ${c.downtime_reason||'Не указана'}</p>
        ${c.downtime_comment?`<p class="raw">${c.downtime_comment}</p>`:''}
        <p>
          Чтобы завершить простой, напиши:
          <b>${c.code} вышла с простоя</b>
        </p>
      </div>
    `
    : `
      <div class="card">
        <h3 class="status-ok">🟢 Машина активно работает</h3>
      </div>
    `;

  let html=`
    ${statusBlock}
    <div class="card">
      <h2>${c.code} ${c.brand||''} ${c.model||''}</h2>
      <p>
        <b>Текущий пробег:</b>
        ${c.mileage?Number(c.mileage).toLocaleString('ru-RU')+' км':'не указан'}
      </p>
      <p>
        <b>Доход:</b> ${rub(c.income)}
        | <b>Расход:</b> ${rub(c.expenses)}
        | <b>Прибыль:</b> ${rub(c.profit)}
      </p>
      <p>
        <b>Инвестор:</b>
        ${c.investor_name||'-'}
        ${c.investor_percent?'('+c.investor_percent+'%)':''}
      </p>
      <p>
        <button onclick="openPeriod('${c.code}')">
          Расчётный период
        </button>
        <button onclick="openInvestorBalance('${c.code}')">
          Взаиморасчёт
        </button>
        <button class="danger" onclick="resetCarInvestor('${c.code}')">
          Убрать инвестора
        </button>
      </p>
    </div>

    <div class="card">
      <h3>Календарь изменений</h3>
      ${renderCalendar(d.operations)}
    </div>
  `;

  carCard.innerHTML=html;
  window.scrollTo(0,carCard.offsetTop);
}
async function openInvestorBalance(code){let d=await api('/api/investor-balance/'+code);let b=d.balance;carCard.innerHTML=`<div class="card warn"><h2>Взаиморасчет ${code}</h2><p><b>Доля прибыли инвестора:</b> ${rub(b.investor_share_total)}</p><p><b>Погашено долгом:</b> ${rub(b.debt_repaid_by_profit)}</p><p><b>Инвестор должен парку:</b> ${rub(b.investor_debt_to_park)}</p><p><b>Парк должен инвестору:</b> ${rub(b.park_debt_to_investor)}</p><p><b>Выплачено:</b> ${rub(b.paid_to_investor)}</p><p><b>Доступно к выплате:</b> ${rub(b.available_to_pay)}</p></div><div class="card"><h3>Журнал взаиморасчетов</h3><table><tr><th>Дата</th><th>Всего</th><th>Инвестор оплатил</th><th>Парк оплатил</th><th>Долг инвестора</th><th>Комментарий</th></tr>${d.settlements.map(x=>`<tr><td>${x.date}</td><td>${rub(x.total_cost)}</td><td>${rub(x.investor_paid)}</td><td>${rub(x.park_paid)}</td><td>${rub(x.investor_debt_to_park)}</td><td>${x.comment||''}</td></tr>`).join('')}</table></div>`;window.scrollTo(0,carCard.offsetTop)}
async function openPeriod(code){
  let d=await api('/api/period/'+code);
  if(!d.ok){
    alert(d.message||'Не удалось открыть расчётный период');
    return;
  }

  let p=d.current_period;
  let hasClosedPeriods=Array.isArray(d.closed_periods)&&d.closed_periods.length>0;
  let lastClosed=hasClosedPeriods?d.closed_periods[0]:null;

  carCard.innerHTML=`
    <div class="card warn">
      <h2>Расчётный период ${code}</h2>

      <p><b>Текущий период:</b> ${p.start_date} — ${p.end_date}</p>

      <p>
        Доход: ${rub(p.income)}
        | Расход: ${rub(p.expenses)}
        | Прибыль: ${rub(p.profit)}
      </p>

      <p>
        Инвестору: ${rub(p.investor_amount)}
        | Парку: ${rub(p.owner_amount)}
      </p>

      <button onclick="closePeriod('${code}')">
        Закрыть период
      </button>

      ${hasClosedPeriods?`
        <button class="danger" onclick="reopenPeriod('${code}')">
          Открыть последний период заново
        </button>

        <p class="raw">
          Последний закрытый период:
          ${lastClosed.start_date} — ${lastClosed.end_date}
        </p>
      `:''}
    </div>
  `;

  window.scrollTo(0,carCard.offsetTop);
}

async function closePeriod(code){
  let r=await api('/api/close-period/'+code,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({})
  });

  alert(r.message);
  await load();
  await openPeriod(code);
}

async function reopenPeriod(code){
  if(!confirm(
    'Открыть последний закрытый период машины '+code+' заново? '+
    'Сохранённый расчёт будет удалён, но доходы и расходы останутся.'
  ))return;

  let r=await api('/api/reopen-period/'+code,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({})
  });

  alert(r.message);

  if(r.ok){
    await load();
    await openPeriod(code);
  }
}
async function loadOps(){
  let o=await api('/api/operations');

  ops.innerHTML=`
    <tr>
      <th>ID</th>
      <th>Дата</th>
      <th>Машина</th>
      <th>Тип</th>
      <th>Описание</th>
      <th>Сумма</th>
      <th>Пробег</th>
      <th>Сообщение</th>
      <th>Удалить</th>
    </tr>
    ${o.map(x=>`
      <tr>
        <td>${x.id}</td>
        <td>${x.date}</td>
        <td>${x.car_code}</td>
        <td>${x.type}</td>
        <td>${x.description||''}</td>
        <td>${rub(x.amount)}</td>
        <td>
          ${x.mileage
            ? Number(x.mileage).toLocaleString('ru-RU')+' км'
            : '—'
          }
        </td>
        <td>${x.raw||''}</td>
        <td>
          <button
            class="danger small"
            onclick="deleteOperation(${x.id})"
          >
            Удалить
          </button>
        </td>
      </tr>
    `).join('')}
  `;
}

let warehouseAutocompleteItems=[];
let warehouseSuggestionIndex=-1;
let warehouseAutocompleteTimer=null;

function normalizeWarehouseSearch(value){
  let text=String(value||'')
    .toLowerCase()
    .replaceAll('ё','е')
    .replace(/[^0-9a-zа-я]+/g,' ')
    .replace(/\s+/g,' ')
    .trim();

  const aliases=[
    ['стойки стаба','стойка стабилизатора'],
    ['стойка стаба','стойка стабилизатора'],
    ['стойки стабилизатора','стойка стабилизатора'],
    ['линка стабилизатора','стойка стабилизатора'],
    ['линк стабилизатора','стойка стабилизатора'],
    ['втулки стаба','втулка стабилизатора'],
    ['втулка стаба','втулка стабилизатора'],
    ['втулки стабилизатора','втулка стабилизатора'],
    ['передние колодки','тормозные колодки передние'],
    ['задние колодки','тормозные колодки задние']
  ];

  for(const [from,to] of aliases){
    text=text.replaceAll(from,to);
  }

  return text;
}

function warehouseSearchTokens(value){
  return normalizeWarehouseSearch(value)
    .split(' ')
    .filter(token=>
      token.length>=3 &&
      ![
        'замена','поменял','поменяли','ремонт','цена','стоимость',
        'работа','пробег','справа','слева','фирма','машина',
        'получил','расход','затраты'
      ].includes(token) &&
      !/^\d+$/.test(token)
    );
}

async function preloadWarehouseAutocomplete(){
  try{
    const data=await api('/api/warehouse');
    warehouseAutocompleteItems=Array.isArray(data)
      ? data.filter(item=>(item.quantity||0)>0)
      : [];
  }catch(error){
    warehouseAutocompleteItems=[];
  }
}

function warehouseItemScore(item,input){
  const query=normalizeWarehouseSearch(input);
  const queryTokens=warehouseSearchTokens(input);

  const name=normalizeWarehouseSearch(item.part_name);
  const brand=normalizeWarehouseSearch(item.brand);
  const haystack=(name+' '+brand).trim();

  let score=0;

  if(query.includes(name) || name.includes(query)){
    score+=100;
  }

  for(const token of queryTokens){
    if(haystack.includes(token)){
      score+=20;
    }else if(
      token.length>=4 &&
      haystack.split(' ').some(word=>
        word.startsWith(token.slice(0,Math.max(3,token.length-2))) ||
        token.startsWith(word.slice(0,Math.max(3,word.length-2)))
      )
    ){
      score+=10;
    }
  }

  if(brand && query.includes(brand)){
    score+=30;
  }

  return score;
}

function findWarehouseSuggestions(input){
  const tokens=warehouseSearchTokens(input);

  if(!tokens.length){
    return [];
  }

  return warehouseAutocompleteItems
    .map(item=>({
      ...item,
      score:warehouseItemScore(item,input)
    }))
    .filter(item=>item.score>0)
    .sort((a,b)=>
      b.score-a.score ||
      (b.quantity||0)-(a.quantity||0) ||
      String(a.part_name).localeCompare(String(b.part_name),'ru')
    )
    .slice(0,8);
}

function renderWarehouseSuggestions(){
  const box=document.getElementById('warehouseSuggestions');
  const input=document.getElementById('msg');
  const suggestions=findWarehouseSuggestions(input.value);

  warehouseSuggestionIndex=-1;

  if(!suggestions.length){
    box.classList.remove('open');
    box.innerHTML='';
    return;
  }

  box.innerHTML=`
    <div class="warehouse-hint">
      Есть на складе — нажми на нужную деталь
    </div>
    ${suggestions.map((item,index)=>`
      <div
        class="warehouse-suggestion"
        data-index="${index}"
        onmousedown="event.preventDefault();selectWarehouseSuggestion(${item.id})"
      >
        <div>
          <div class="warehouse-suggestion-name">
            ${item.part_name}${item.brand?' · '+item.brand:''}
          </div>
          <div class="warehouse-suggestion-meta">
            ${item.shelf?'Полка: '+item.shelf+' · ':''}
            Минимум: ${item.min_quantity||0} шт.
          </div>
        </div>

        <div class="warehouse-suggestion-stock ${(item.quantity||0)<=(item.min_quantity||0)?'low':''}">
          ${item.quantity||0} шт.
        </div>
      </div>
    `).join('')}
  `;

  box.dataset.items=JSON.stringify(
    suggestions.map(item=>item.id)
  );
  box.classList.add('open');
}

function selectWarehouseSuggestion(itemId){
  const item=warehouseAutocompleteItems.find(
    value=>Number(value.id)===Number(itemId)
  );

  if(!item){
    return;
  }

  const input=document.getElementById('msg');
  let value=input.value.trim();

  const brandText=item.brand
    ? ` фирма ${item.brand}`
    : '';

  const normalizedValue=normalizeWarehouseSearch(value);
  const normalizedBrand=normalizeWarehouseSearch(item.brand);

  if(item.brand && !normalizedValue.includes(normalizedBrand)){
    value+=brandText;
  }

  if(!normalizeWarehouseSearch(value).includes('со склада')){
    value+=' со склада';
  }

  input.value=value.replace(/\s+/g,' ').trim()+' ';
  document.getElementById('warehouseSuggestions').classList.remove('open');
  input.focus();
}

function moveWarehouseSuggestion(direction){
  const box=document.getElementById('warehouseSuggestions');
  const rows=[...box.querySelectorAll('.warehouse-suggestion')];

  if(!rows.length || !box.classList.contains('open')){
    return false;
  }

  warehouseSuggestionIndex+=direction;

  if(warehouseSuggestionIndex<0){
    warehouseSuggestionIndex=rows.length-1;
  }
  if(warehouseSuggestionIndex>=rows.length){
    warehouseSuggestionIndex=0;
  }

  rows.forEach((row,index)=>{
    row.classList.toggle(
      'active',
      index===warehouseSuggestionIndex
    );
  });

  rows[warehouseSuggestionIndex].scrollIntoView({
    block:'nearest'
  });

  return true;
}

function chooseActiveWarehouseSuggestion(){
  const box=document.getElementById('warehouseSuggestions');
  const rows=[...box.querySelectorAll('.warehouse-suggestion')];

  if(
    warehouseSuggestionIndex<0 ||
    warehouseSuggestionIndex>=rows.length
  ){
    return false;
  }

  const ids=JSON.parse(box.dataset.items||'[]');
  selectWarehouseSuggestion(ids[warehouseSuggestionIndex]);
  return true;
}

function setupWarehouseAutocomplete(){
  const input=document.getElementById('msg');

  input.addEventListener('input',()=>{
    clearTimeout(warehouseAutocompleteTimer);
    warehouseAutocompleteTimer=setTimeout(
      renderWarehouseSuggestions,
      120
    );
  });

  input.addEventListener('focus',renderWarehouseSuggestions);

  input.addEventListener('keydown',event=>{
    if(event.key==='ArrowDown'){
      if(moveWarehouseSuggestion(1)){
        event.preventDefault();
      }
    }else if(event.key==='ArrowUp'){
      if(moveWarehouseSuggestion(-1)){
        event.preventDefault();
      }
    }else if(event.key==='Enter'){
      if(chooseActiveWarehouseSuggestion()){
        event.preventDefault();
      }
    }else if(event.key==='Escape'){
      document
        .getElementById('warehouseSuggestions')
        .classList.remove('open');
    }
  });

  document.addEventListener('click',event=>{
    if(!event.target.closest('.command-box')){
      document
        .getElementById('warehouseSuggestions')
        .classList.remove('open');
    }
  });
}

async function add(){let m=msg.value;try{let r=await api('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});res.innerText=r.message||JSON.stringify(r);if(r.ok){msg.value='';await preloadWarehouseAutocomplete();}load()}catch(e){res.innerText='Ошибка: '+e}}


function toggleWarehousePanel(){
  const panel=document.getElementById('warehousePanel');
  const button=document.getElementById('warehouseToggleButton');

  panel.classList.toggle('open');
  button.innerText=panel.classList.contains('open')
    ? 'Скрыть'
    : 'Открыть';

  if(panel.classList.contains('open')){
    loadWarehouse();
  }
}

async function loadWarehouse(){
  const items=await api('/api/warehouse');

  if(!Array.isArray(items)){
    warehouseItems.innerHTML='<p class="bad">Не удалось загрузить склад</p>';
    return;
  }

  warehouse_restock_item.innerHTML=
    '<option value="">Выбери деталь</option>'+
    items.map(i=>`
      <option value="${i.id}">
        ${i.part_name} ${i.brand||''} — ${i.quantity} шт.
      </option>
    `).join('');

  if(!items.length){
    warehouseItems.innerHTML='<p class="raw">Склад пока пуст.</p>';
    return;
  }

  warehouseItems.innerHTML=items.map(i=>`
    <div class="warehouse-item ${i.low_stock?'low':''}">
      <div class="warehouse-name">
        ${i.part_name} ${i.brand||''}
      </div>
      <div class="warehouse-stock">${i.quantity} шт.</div>
      <div class="raw">
        Минимум: ${i.min_quantity} шт.
        ${i.shelf?` · Полка: ${i.shelf}`:''}
      </div>
      ${i.low_stock?'<p class="bad">⚠️ Нужно пополнить</p>':''}
    </div>
  `).join('');
}

async function addWarehouseItem(){
  const payload={
    part_name:warehouse_part.value,
    brand:warehouse_brand.value,
    quantity:Number(warehouse_quantity.value||0),
    min_quantity:Number(warehouse_min.value||0),
    shelf:warehouse_shelf.value
  };

  const r=await api('/api/warehouse/add-item',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });

  warehouseRes.innerText=r.message||'';

  if(r.ok){
    warehouse_part.value='';
    warehouse_brand.value='';
    warehouse_quantity.value='';
    warehouse_min.value='';
    warehouse_shelf.value='';
    await loadWarehouse();
    await preloadWarehouseAutocomplete();
  }
}

async function restockWarehouse(){
  const payload={
    item_id:Number(warehouse_restock_item.value||0),
    quantity:Number(warehouse_restock_quantity.value||0),
    comment:warehouse_restock_comment.value
  };

  const r=await api('/api/warehouse/restock',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });

  warehouseRes.innerText=r.message||'';

  if(r.ok){
    warehouse_restock_quantity.value='';
    warehouse_restock_comment.value='';
    await loadWarehouse();
  }
}

function togglePaymentsPanel(){
  const panel=document.getElementById('paymentsPanel');
  const button=document.getElementById('paymentsToggleButton');

  panel.classList.toggle('open');

  button.innerText=panel.classList.contains('open')
    ? 'Скрыть'
    : 'Открыть';
}

function toggleAddCarForm(){
  const panel=document.getElementById('addCarPanel');
  panel.classList.toggle('open');

  if(panel.classList.contains('open')){
    panel.scrollIntoView({behavior:'smooth',block:'start'});
    setTimeout(()=>document.getElementById('code')?.focus(),250);
  }
}

function toggleCarsList(){
  const wrap=document.getElementById('carsListWrap');
  const button=event?.currentTarget;

  wrap.classList.toggle('open');

  if(button){
    button.innerText=wrap.classList.contains('open')
      ? 'Скрыть список'
      : 'Показать список';
  }
}

async function addCar(){
  let payload={
    owner_type:owner_type.value,
    code:code.value,
    brand:brand.value,
    model:model.value,
    plate:plate.value,
    year:year.value,
    purchase_date:purchase_date.value,
    purchase_price:purchase_price.value,
    mileage:mileage.value,
    investor_name:investor_name.value,
    investor_percent:investor_percent.value,
    settlement_day:settlement_day.value
  };

  let r=await api('/api/add-car',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });

  carRes.innerText=r.message;

  if(r.ok){
    await load();
    document.getElementById('addCarPanel').classList.remove('open');
  }
}
async function load(){await loadSummary();await loadInvestorsSummary();await loadInvestors();await loadCars();await loadOps()}

msg.addEventListener('keydown',e=>{if(e.key==='Enter')add()});
preloadWarehouseAutocomplete();
setupWarehouseAutocomplete();
load();
</script>
</body>
</html>
'''
