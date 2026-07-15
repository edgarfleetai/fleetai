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
.warehouse-form{display:grid;grid-template-columns:repeat(7,minmax(120px,1fr));gap:8px;align-items:end}
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

.warehouse-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.warehouse-actions button{font-size:12px;padding:7px 10px}
.warehouse-editor{display:none;margin-top:10px;padding-top:10px;border-top:1px solid #e5e7eb}
.warehouse-editor.open{display:block}
.warehouse-editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.warehouse-editor-grid input{min-width:0}
.warehouse-editor-full{grid-column:1/-1}

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

/* =========================================================
   FLEETAI — MINIMAL / PREMIUM THEME
   ========================================================= */

:root{
  --page:#f4f3f1;
  --surface:#ffffff;
  --surface-soft:#faf9f7;
  --surface-muted:#f0efed;

  --text:#1f1d1a;
  --text-soft:#6f6a64;
  --text-faint:#9a958f;

  --line:#e6e2de;
  --line-strong:#d7d1cb;

  --primary:#35312d;
  --primary-hover:#211e1b;
  --primary-soft:#ebe8e4;

  --danger:#a73a3a;
  --danger-soft:#fff3f2;

  --warning:#8a6c36;
  --warning-soft:#fbf6ea;

  --success:#4d6757;
  --success-soft:#eef5f0;

  --shadow-sm:0 1px 2px rgba(31,29,26,.04);
  --shadow-md:0 10px 28px rgba(31,29,26,.07);
  --shadow-lg:0 20px 50px rgba(31,29,26,.10);

  --radius-sm:10px;
  --radius-md:14px;
  --radius-lg:20px;
}

*{
  box-sizing:border-box;
}

html{
  scroll-behavior:smooth;
}

body{
  margin:0;
  background:
    radial-gradient(circle at top left, rgba(255,255,255,.9), transparent 28%),
    var(--page);
  color:var(--text);
  font-family:
    Inter,
    ui-sans-serif,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  line-height:1.5;
}

body::before{
  content:"";
  position:fixed;
  inset:0 0 auto 0;
  height:1px;
  background:rgba(255,255,255,.9);
  z-index:1000;
}

h1,h2,h3,h4{
  color:var(--text);
  letter-spacing:-.02em;
}

h1{
  font-size:30px;
  font-weight:750;
  margin:0 0 6px;
}

h2{
  font-size:20px;
  font-weight:700;
}

h3{
  font-size:16px;
  font-weight:700;
}

p{
  color:var(--text-soft);
}

a{
  color:var(--text);
}

/* ---------- PAGE WIDTH ---------- */

body > *{
  max-width:1440px;
  margin-left:auto;
  margin-right:auto;
}

body > h1,
body > .top-actions,
body > #summary,
body > #fleetStatus,
body > .card,
body > #carCard{
  width:calc(100% - 40px);
}

/* ---------- CARDS ---------- */

.card,
.warehouse-item,
.daycard,
.status-column,
.investor-card,
.car-card{
  background:rgba(255,255,255,.92);
  border:1px solid var(--line);
  border-radius:var(--radius-lg);
  box-shadow:var(--shadow-sm);
}

.card{
  padding:20px;
  margin-top:14px;
}

.card:hover,
.warehouse-item:hover,
.daycard:hover,
.status-column:hover{
  box-shadow:var(--shadow-md);
  transition:box-shadow .2s ease, border-color .2s ease;
}

.section-head{
  align-items:center;
  padding-bottom:2px;
}

.section-head h2{
  margin:0;
}

/* ---------- TOP ACTIONS ---------- */

.top-actions{
  position:sticky;
  top:12px;
  z-index:40;
  display:flex;
  justify-content:flex-end;
  pointer-events:none;
}

.top-actions button{
  pointer-events:auto;
}

.icon-button{
  width:42px;
  height:42px;
  border-radius:14px;
  font-size:22px;
  background:var(--primary);
  box-shadow:var(--shadow-md);
}

/* ---------- BUTTONS ---------- */

button{
  appearance:none;
  border:1px solid transparent;
  border-radius:12px;
  padding:9px 14px;
  background:var(--primary);
  color:#fff;
  font-weight:650;
  font-size:14px;
  cursor:pointer;
  transition:
    background .16s ease,
    border-color .16s ease,
    color .16s ease,
    transform .16s ease,
    box-shadow .16s ease;
}

button:hover{
  background:var(--primary-hover);
  transform:translateY(-1px);
  box-shadow:0 8px 20px rgba(31,29,26,.12);
}

button:active{
  transform:translateY(0);
  box-shadow:none;
}

button.secondary,
.section-toggle{
  background:var(--surface);
  color:var(--text);
  border-color:var(--line-strong);
}

button.secondary:hover,
.section-toggle:hover{
  background:var(--surface-soft);
  border-color:#bfb8b1;
}

button.danger{
  background:var(--surface);
  color:var(--danger);
  border-color:#e8c7c5;
}

button.danger:hover{
  background:var(--danger-soft);
  border-color:#d7a5a2;
}

button.small{
  padding:7px 10px;
  border-radius:10px;
  font-size:12px;
}

/* ---------- INPUTS ---------- */

input,
select,
textarea{
  width:100%;
  min-height:42px;
  border:1px solid var(--line-strong);
  border-radius:12px;
  background:rgba(255,255,255,.96);
  color:var(--text);
  padding:10px 12px;
  font:inherit;
  outline:none;
  transition:
    border-color .16s ease,
    box-shadow .16s ease,
    background .16s ease;
}

input::placeholder,
textarea::placeholder{
  color:var(--text-faint);
}

input:focus,
select:focus,
textarea:focus{
  border-color:#8e8881;
  box-shadow:0 0 0 4px rgba(53,49,45,.08);
  background:#fff;
}

/* ---------- SUMMARY ---------- */

.grid{
  gap:10px !important;
}

.stat,
.investor-kpi,
.flow-item,
.metric{
  background:rgba(255,255,255,.94);
  border:1px solid var(--line);
  border-radius:16px;
  box-shadow:var(--shadow-sm);
}

.stat{
  padding:16px;
  color:var(--text-soft);
  font-size:13px;
}

.stat b{
  display:block;
  margin-top:6px;
  color:var(--text);
  font-size:22px;
  font-weight:760;
}

/* ---------- STATUS BOARD ---------- */

.status-board{
  gap:10px;
}

.status-column{
  padding:16px;
}

.status-column.downtime{
  background:var(--warning-soft);
  border-color:#eadcc0;
}

.status-title{
  font-size:14px;
}

.status-ok{
  color:var(--success);
}

.status-off{
  color:var(--warning);
}

.status-list{
  gap:7px;
}

.car-status-chip{
  background:var(--surface-soft);
  border:1px solid var(--line);
  border-radius:12px;
  padding:9px 11px;
}

.car-status-chip.off{
  background:#f8efe2;
}

.car-status-chip:hover{
  border-color:#bdb6af;
  box-shadow:var(--shadow-sm);
}

/* ---------- TABLES ---------- */

table{
  width:100%;
  border-collapse:separate;
  border-spacing:0;
  overflow:hidden;
  border:1px solid var(--line);
  border-radius:14px;
  background:var(--surface);
}

th{
  background:var(--surface-soft);
  color:var(--text-soft);
  font-size:12px;
  font-weight:700;
  letter-spacing:.01em;
  text-align:left;
  padding:11px 12px;
  border-bottom:1px solid var(--line);
}

td{
  color:var(--text);
  padding:11px 12px;
  border-bottom:1px solid #efedea;
  vertical-align:top;
}

tr:last-child td{
  border-bottom:none;
}

tbody tr:hover td{
  background:#fbfaf8;
}

/* ---------- BADGES ---------- */

.badge{
  display:inline-flex;
  align-items:center;
  gap:5px;
  border-radius:999px;
  padding:5px 9px;
  background:var(--primary-soft);
  color:#4e4944;
  font-size:11px;
  font-weight:700;
}

.badge-working{
  background:var(--success-soft);
  color:var(--success);
}

.badge-downtime{
  background:var(--warning-soft);
  color:var(--warning);
}

.good{
  color:var(--success) !important;
}

.bad{
  color:var(--danger) !important;
}

.raw{
  color:var(--text-soft) !important;
}

/* ---------- MAIN COMMAND ---------- */

.command-box{
  gap:10px;
}

.command-box .msg{
  min-height:46px;
  font-size:15px;
}

.command-box > button{
  min-height:46px;
  padding-left:20px;
  padding-right:20px;
}

.warehouse-suggestions{
  border-color:var(--line);
  border-radius:16px;
  box-shadow:var(--shadow-lg);
  overflow:hidden;
}

.warehouse-suggestion{
  padding:12px 14px;
}

.warehouse-suggestion:hover,
.warehouse-suggestion.active{
  background:var(--surface-soft);
}

/* ---------- WAREHOUSE ---------- */

.warehouse-grid{
  gap:10px;
}

.warehouse-item{
  padding:16px;
}

.warehouse-name{
  font-size:15px;
  font-weight:720;
}

.warehouse-stock{
  font-size:28px;
  font-weight:760;
  letter-spacing:-.03em;
}

.warehouse-item.low{
  background:var(--warning-soft);
  border-color:#eadcc0;
}

.warehouse-actions{
  gap:6px;
}

.warehouse-actions button{
  background:var(--surface);
  color:var(--text);
  border-color:var(--line);
}

.warehouse-actions button:hover{
  background:var(--surface-soft);
}

.warehouse-actions button.danger{
  color:var(--danger);
}

/* ---------- INVESTOR AREA ---------- */

.investor-summary-grid{
  gap:10px !important;
}

.investor-kpi{
  padding:15px;
}

.investor-kpi span{
  color:var(--text-soft);
}

.investor-kpi b{
  color:var(--text);
}

.investor-card{
  padding:18px;
}

.investor-flow{
  gap:8px;
}

.flow-item,
.metric{
  padding:12px;
}

/* ---------- CALENDAR / EVENTS ---------- */

.calendar{
  gap:10px;
}

.daycard{
  padding:14px;
}

.event{
  border:1px solid var(--line);
  background:var(--surface-soft);
  border-radius:12px;
  padding:11px;
  margin-top:8px;
}

.event.income{
  background:var(--success-soft);
  border-color:#d7e5db;
}

.event.expense,
.event.repair,
.event.service{
  background:#faf7f3;
}

.event.downtime{
  background:var(--warning-soft);
}

/* ---------- SCROLLBARS ---------- */

*{
  scrollbar-width:thin;
  scrollbar-color:#c9c3bd transparent;
}

*::-webkit-scrollbar{
  width:8px;
  height:8px;
}

*::-webkit-scrollbar-thumb{
  background:#c9c3bd;
  border-radius:999px;
}

/* ---------- MOBILE ---------- */

@media(max-width:800px){
  body > h1,
  body > .top-actions,
  body > #summary,
  body > #fleetStatus,
  body > .card,
  body > #carCard{
    width:calc(100% - 20px);
  }

  h1{
    font-size:24px;
  }

  .card{
    padding:15px;
    border-radius:16px;
  }

  .stat{
    padding:13px;
  }

  .stat b{
    font-size:19px;
  }

  table{
    display:block;
    overflow-x:auto;
    white-space:nowrap;
  }

  .command-box > button{
    width:100%;
  }
}


/* ===== APP SHELL / SIDEBAR ===== */

body > *{
  max-width:none !important;
  width:auto !important;
  margin:0 !important;
}

.app-shell{
  min-height:100vh;
  display:grid;
  grid-template-columns:250px minmax(0,1fr);
}

.app-sidebar{
  position:fixed;
  inset:0 auto 0 0;
  width:250px;
  display:flex;
  flex-direction:column;
  padding:22px 16px;
  background:#1e1d1b;
  color:#fff;
  border-right:1px solid rgba(255,255,255,.06);
  z-index:100;
}

.brand-block{
  display:flex;
  align-items:center;
  gap:12px;
  padding:4px 8px 26px;
}

.brand-mark{
  width:38px;
  height:38px;
  display:grid;
  place-items:center;
  border-radius:12px;
  background:#f1efeb;
  color:#24211e;
  font-size:18px;
  font-weight:800;
}

.brand-name{
  font-size:16px;
  font-weight:750;
  letter-spacing:-.01em;
}

.brand-subtitle{
  margin-top:2px;
  color:#9f9a94;
  font-size:11px;
}

.app-nav{
  display:flex;
  flex-direction:column;
  gap:4px;
}

.nav-item{
  width:100%;
  display:flex;
  align-items:center;
  gap:12px;
  padding:11px 12px;
  background:transparent;
  color:#aaa59f;
  border:1px solid transparent;
  border-radius:11px;
  box-shadow:none;
  text-align:left;
}

.nav-item:hover{
  background:rgba(255,255,255,.06);
  color:#fff;
  box-shadow:none;
  transform:none;
}

.nav-item.active{
  background:#f1efeb;
  color:#26231f;
}

.nav-icon{
  width:20px;
  text-align:center;
  font-size:17px;
}

.sidebar-footer{
  margin-top:auto;
  padding:16px 8px 2px;
}

.system-status{
  display:flex;
  align-items:center;
  gap:8px;
  color:#8f8a84;
  font-size:11px;
}

.status-dot{
  width:7px;
  height:7px;
  border-radius:50%;
  background:#6d8a75;
  box-shadow:0 0 0 4px rgba(109,138,117,.12);
}

.app-main{
  grid-column:2;
  min-width:0;
  padding:30px 34px 60px;
}

.wrap{
  max-width:1500px;
  margin:0 auto;
}

.mobile-topbar{
  display:none;
}

.app-page{
  display:none;
  animation:pageFade .18s ease;
}

.app-page.active{
  display:block;
}

.app-page-linked.active{
  display:block;
}

@keyframes pageFade{
  from{opacity:0;transform:translateY(4px)}
  to{opacity:1;transform:none}
}

.page-heading{
  display:flex;
  justify-content:space-between;
  align-items:flex-end;
  gap:20px;
  margin:2px 0 20px;
}

.page-heading h1{
  margin:3px 0 3px;
  font-size:31px;
}

.page-heading p{
  margin:0;
  font-size:14px;
}

.eyebrow{
  color:#8b857e;
  font-size:10px;
  font-weight:800;
  letter-spacing:.12em;
}

.page-primary-action{
  white-space:nowrap;
}

.top-actions{
  display:none !important;
}

.analytics-grid{
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:10px;
}

.analytics-prompt{
  min-height:150px;
  display:flex;
  flex-direction:column;
  align-items:flex-start;
  justify-content:flex-end;
  text-align:left;
  background:#fff;
  color:var(--text);
  border:1px solid var(--line);
  box-shadow:var(--shadow-sm);
}

.analytics-prompt:hover{
  background:#faf9f7;
  border-color:#cfc9c2;
  box-shadow:var(--shadow-md);
}

.analytics-prompt-icon{
  margin-bottom:auto;
  color:#8d877f;
  font-size:24px;
}

.analytics-prompt strong{
  font-size:15px;
}

.analytics-prompt small{
  margin-top:4px;
  color:var(--text-soft);
  font-weight:400;
  line-height:1.4;
}

.analytics-console{
  margin-top:12px;
}

.analytics-input-row{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  gap:9px;
}

.analytics-answer{
  min-height:160px;
  margin:14px 0 0;
  padding:16px;
  overflow:auto;
  border:1px solid var(--line);
  border-radius:14px;
  background:#f8f7f5;
  color:#35312d;
  white-space:pre-wrap;
  font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
}

@media(max-width:1050px){
  .analytics-grid{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }
}

@media(max-width:800px){
  .app-shell{
    display:block;
  }

  .app-sidebar{
    transform:translateX(-100%);
    transition:transform .2s ease;
    box-shadow:var(--shadow-lg);
  }

  .app-sidebar.open{
    transform:translateX(0);
  }

  .app-main{
    padding:70px 10px 40px;
  }

  .mobile-topbar{
    position:fixed;
    inset:0 0 auto 0;
    z-index:80;
    height:54px;
    display:flex;
    align-items:center;
    gap:12px;
    padding:0 14px;
    background:rgba(255,255,255,.92);
    backdrop-filter:blur(12px);
    border-bottom:1px solid var(--line);
    font-weight:700;
  }

  .mobile-menu-button{
    width:36px;
    height:36px;
    padding:0;
    background:#292622;
  }

  .page-heading{
    align-items:flex-start;
    flex-direction:column;
  }

  .page-heading h1{
    font-size:25px;
  }

  .analytics-grid{
    grid-template-columns:1fr;
  }

  .analytics-prompt{
    min-height:115px;
  }

  .analytics-input-row{
    grid-template-columns:1fr;
  }
}


.selected-warehouse-chips{
  display:none;
  align-items:center;
  flex-wrap:wrap;
  gap:7px;
  margin-top:10px;
}

.selected-warehouse-chips.open{
  display:flex;
}

.selected-warehouse-label{
  color:var(--text-soft);
  font-size:12px;
  font-weight:650;
}

.selected-warehouse-chip{
  display:inline-flex;
  align-items:center;
  gap:7px;
  max-width:100%;
  padding:7px 9px 7px 11px;
  border:1px solid var(--line-strong);
  border-radius:999px;
  background:var(--surface-soft);
  color:var(--text);
  font-size:12px;
  font-weight:650;
}

.selected-warehouse-chip button{
  width:20px;
  height:20px;
  min-height:0;
  padding:0;
  border-radius:50%;
  background:#dedad5;
  color:#5d5751;
  line-height:1;
  box-shadow:none;
}

.selected-warehouse-chip button:hover{
  background:#cec8c1;
  transform:none;
  box-shadow:none;
}

.warehouse-suggestion-variant{
  margin-top:2px;
  color:var(--text-soft);
  font-size:11px;
  font-weight:500;
}


/* ===== MONTHLY FINANCE COMPARISON ===== */

.fleet-finance-strip{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:10px;
  margin-bottom:12px;
}

.fleet-finance-card{
  min-width:0;
  padding:16px 18px;
  border:1px solid var(--line);
  border-radius:16px;
  background:rgba(255,255,255,.94);
  box-shadow:var(--shadow-sm);
}

.fleet-finance-title{
  color:var(--text-soft);
  font-size:12px;
  font-weight:650;
}

.fleet-finance-value{
  margin-top:6px;
  color:var(--text);
  font-size:25px;
  font-weight:760;
  letter-spacing:-.03em;
}

.fleet-finance-compare{
  display:flex;
  align-items:center;
  gap:7px;
  margin-top:8px;
  color:var(--text-soft);
  font-size:11px;
}

.finance-trend{
  width:23px;
  height:23px;
  display:inline-grid;
  place-items:center;
  flex:0 0 23px;
  border-radius:7px;
  font-size:15px;
  font-weight:800;
}

.finance-trend.up{
  color:#496454;
  background:#edf4ef;
}

.finance-trend.down{
  color:#a04848;
  background:#fbefee;
}

.finance-trend.flat{
  color:#756f68;
  background:#f0eeeb;
}

@media(max-width:800px){
  .fleet-finance-strip{
    grid-template-columns:1fr;
  }
}


/* ===== MONTHLY MILEAGE INDICATOR ===== */

.mileage-cell{
  display:flex;
  flex-direction:column;
  align-items:flex-start;
  gap:5px;
  min-width:145px;
}

.mileage-increase{
  display:inline-flex;
  align-items:center;
  min-height:24px;
  padding:4px 8px;
  border-radius:8px;
  font-size:11px;
  font-weight:750;
  white-space:nowrap;
}

.mileage-current{
  color:var(--text);
  font-size:13px;
  font-weight:650;
}

.mileage-neutral{
  color:#69645e;
  background:#efedea;
}

.mileage-green{
  color:#3f674d;
  background:#eaf4ed;
}

.mileage-yellow{
  color:#806427;
  background:#faf1d6;
}

.mileage-red{
  color:#a33e3e;
  background:#fbeaea;
}


.driver-debt{
  color:#a33e3e;
  font-weight:750;
}

.driver-status-overdue{
  display:inline-flex;
  padding:5px 8px;
  border-radius:8px;
  background:#fbeaea;
  color:#a33e3e;
  font-size:12px;
  font-weight:700;
}


.overdue-period-list{
  display:flex;
  flex-direction:column;
  gap:7px;
  min-width:230px;
}

.overdue-period-row{
  display:flex;
  justify-content:space-between;
  gap:12px;
  padding:8px 10px;
  border:1px solid #efcfcc;
  border-radius:10px;
  background:#fff5f4;
}

.overdue-period-row strong{
  color:#a33e3e;
  white-space:nowrap;
}


.overdue-period-payment{
  display:flex;
  flex-direction:column;
  align-items:flex-end;
  gap:6px;
}

.overdue-period-payment button{
  padding:6px 9px;
  font-size:11px;
}

</style>
</head>

<body>
<div class="app-shell">
  <aside class="app-sidebar">
    <div class="brand-block">
      <div class="brand-mark">F</div>
      <div>
        <div class="brand-name">FleetAI</div>
        <div class="brand-subtitle">Управление автопарком</div>
      </div>
    </div>

    <nav class="app-nav">
      <button class="nav-item active" data-page="dashboard" onclick="showAppPage('dashboard',this)">
        <span class="nav-icon">⌂</span>
        <span>Главная</span>
      </button>
      <button class="nav-item" data-page="fleet" onclick="showAppPage('fleet',this)">
        <span class="nav-icon">◈</span>
        <span>Машины</span>
      </button>
      <button class="nav-item" data-page="investors" onclick="showAppPage('investors',this)">
        <span class="nav-icon">₽</span>
        <span>Инвесторы</span>
      </button>
      <button class="nav-item" data-page="warehouse" onclick="showAppPage('warehouse',this)">
        <span class="nav-icon">□</span>
        <span>Склад</span>
      </button>
      <button class="nav-item" data-page="drivers" onclick="showAppPage('drivers',this)">
        <span class="nav-icon">◎</span>
        <span>Водители</span>
      </button>
      <button class="nav-item" data-page="analytics" onclick="showAppPage('analytics',this)">
        <span class="nav-icon">↗</span>
        <span>Аналитика</span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <div class="system-status">
        <span class="status-dot"></span>
        Система работает
      </div>
    </div>
  </aside>

  <main class="app-main">
    <div class="mobile-topbar">
      <button class="mobile-menu-button" onclick="toggleMobileSidebar()">☰</button>
      <span>FleetAI</span>
    </div>

    <div class="wrap">
<section id="page-dashboard" class="app-page active">
<div class="page-heading">
  <div>
    <div class="eyebrow">ОБЗОР АВТОПАРКА</div>
    <h1>Панель управления</h1>
    <p>Главные показатели, статусы машин и быстрая запись операций.</p>
  </div>
</div>

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

  <div id="selectedWarehouseChips" class="selected-warehouse-chips"></div>
  <p id="res"></p>
</div>
</section>

<section id="page-investors" class="app-page">
<div class="page-heading">
  <div>
    <div class="eyebrow">КАПИТАЛ И ВЫПЛАТЫ</div>
    <h1>Инвесторы</h1>
    <p>Начисления, удержания, долги и расчётные периоды.</p>
  </div>
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

</section>

<section id="page-drivers" class="app-page">
<div class="page-heading">
  <div>
    <div class="eyebrow">ПЛАТЕЖИ И ГРАФИК</div>
    <h1>Водители</h1>
    <p>Еженедельные расчёты, даты оплат и уведомления.</p>
  </div>
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

      <label>Аренда в сутки
        <input id="payment_daily_rent" type="number" min="0" placeholder="2000">
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

</section>

<section id="page-fleet" class="app-page">
<div class="page-heading fleet-page-heading">
  <div>
    <div class="eyebrow">АВТОПАРК</div>
    <h1>Машины</h1>
    <p>Состояние, ремонты, пробег и история каждой машины.</p>
  </div>
  <button class="page-primary-action" onclick="toggleAddCarForm()">+ Добавить машину</button>
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

</section>

<section id="page-warehouse" class="app-page">
<div class="page-heading">
  <div>
    <div class="eyebrow">ЗАПЧАСТИ И ОСТАТКИ</div>
    <h1>Склад</h1>
    <p>Наличие, исполнения, бренды, приход и списания.</p>
  </div>
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
      <input
        id="warehouse_variant"
        placeholder="Исполнение: задние барабанные"
      >
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

</section>

<section id="page-fleet-continuation" class="app-page app-page-linked" data-linked-page="fleet">

<div class="fleet-finance-strip" id="fleetMonthlyFinance">
  <div class="fleet-finance-card">
    <div class="fleet-finance-title">Доход за месяц</div>
    <div class="fleet-finance-value" id="monthIncome">—</div>
    <div class="fleet-finance-compare">
      <span id="monthIncomeTrend" class="finance-trend flat">→</span>
      <span id="monthIncomePrevious">Прошлый месяц: —</span>
    </div>
  </div>

  <div class="fleet-finance-card">
    <div class="fleet-finance-title">Расход за месяц</div>
    <div class="fleet-finance-value" id="monthExpenses">—</div>
    <div class="fleet-finance-compare">
      <span id="monthExpensesTrend" class="finance-trend flat">→</span>
      <span id="monthExpensesPrevious">Прошлый месяц: —</span>
    </div>
  </div>

  <div class="fleet-finance-card">
    <div class="fleet-finance-title">Прибыль за месяц</div>
    <div class="fleet-finance-value" id="monthProfit">—</div>
    <div class="fleet-finance-compare">
      <span id="monthProfitTrend" class="finance-trend flat">→</span>
      <span id="monthProfitPrevious">Прошлый месяц: —</span>
    </div>
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
</section>

<section id="page-analytics" class="app-page">
<div class="page-heading">
  <div>
    <div class="eyebrow">ИСТОРИЯ И ЗАКОНОМЕРНОСТИ</div>
    <h1>Аналитика</h1>
    <p>Задавай вопросы системе о ремонтах, деталях и частоте поломок.</p>
  </div>
</div>

<div class="analytics-grid">
  <button class="analytics-prompt" onclick="askAnalytics('Какие детали чаще всего ломаются?')">
    <span class="analytics-prompt-icon">↗</span>
    <strong>Частые поломки</strong>
    <small>Какие детали меняются чаще всего</small>
  </button>
  <button class="analytics-prompt" onclick="askAnalytics('Какие детали меняются реже всего?')">
    <span class="analytics-prompt-icon">↓</span>
    <strong>Редкие замены</strong>
    <small>Что служит дольше остальных деталей</small>
  </button>
  <button class="analytics-prompt" onclick="askAnalytics('Кому мы меняли рулевой наконечник последний раз?')">
    <span class="analytics-prompt-icon">⌕</span>
    <strong>Поиск по истории</strong>
    <small>Последняя замена конкретной детали</small>
  </button>
  <button class="analytics-prompt" onclick="askAnalytics('Как часто меняли стойку стабилизатора?')">
    <span class="analytics-prompt-icon">◷</span>
    <strong>Интервалы замен</strong>
    <small>Средний срок и пробег детали</small>
  </button>
</div>

<div class="card analytics-console">
  <h2>Спросить FleetAI</h2>
  <p class="raw">Например: «Какие детали чаще ломаются?» или «Когда меняли помпу последний раз?»</p>
  <div class="analytics-input-row">
    <input id="analyticsQuestion" placeholder="Введите вопрос по истории автопарка">
    <button onclick="askAnalytics()">Спросить</button>
  </div>
  <pre id="analyticsAnswer" class="analytics-answer">Ответ появится здесь.</pre>
</div>
</section>

    </div>
  </main>
</div>

<script>

function showAppPage(page,button){
  document.querySelectorAll('.app-page').forEach(section=>{
    section.classList.remove('active');
  });

  const mainPage=document.getElementById(`page-${page}`);
  if(mainPage){
    mainPage.classList.add('active');
  }

  document.querySelectorAll(
    `.app-page-linked[data-linked-page="${page}"]`
  ).forEach(section=>{
    section.classList.add('active');
  });

  document.querySelectorAll('.nav-item').forEach(item=>{
    item.classList.remove('active');
  });

  const navButton=button || document.querySelector(
    `.nav-item[data-page="${page}"]`
  );

  if(navButton){
    navButton.classList.add('active');
  }

  document.querySelector('.app-sidebar')?.classList.remove('open');
  window.scrollTo({top:0,behavior:'smooth'});

  if(page==='warehouse'){
    loadWarehouse();
  }
}

function toggleMobileSidebar(){
  document.querySelector('.app-sidebar')?.classList.toggle('open');
}

async function askAnalytics(question){
  const input=document.getElementById('analyticsQuestion');
  const output=document.getElementById('analyticsAnswer');
  const text=(question || input?.value || '').trim();

  if(!text){
    output.textContent='Введите вопрос.';
    return;
  }

  if(input){
    input.value=text;
  }

  output.textContent='Ищу ответ по истории...';

  try{
    const result=await api('/api/ask-history',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text})
    });

    output.textContent=result.message || 'Ответ не найден.';
  }catch(error){
    output.textContent='Не удалось выполнить анализ.';
  }
}

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
    payment_daily_rent.value='';
    payment_date.value='';
    payment_weekday.value='0';
    return;
  }
  payment_driver.value=car.driver||'';
  payment_daily_rent.value=car.daily_rent||'';
  payment_date.value=car.next_payment_date||'';
  payment_weekday.value=String(car.payment_weekday||0);
});

async function saveDriverPayment(){
  if(!payment_car.value){paymentRes.innerText='Сначала выбери машину';return}
  if(!payment_daily_rent.value){paymentRes.innerText='Укажи стоимость аренды в сутки';return}
  if(!payment_date.value){paymentRes.innerText='Укажи ближайшую дату оплаты';return}

  const payload={
    car_code:payment_car.value,
    driver:payment_driver.value,
    daily_rent:Number(payment_daily_rent.value),
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


async function markDriverPeriodPaid(
  carCode,
  periodStart,
  periodEnd
){
  if(!confirm(
    `Закрыть период ${periodStart} — ${periodEnd}?`
  )){
    return;
  }

  try{
    const result=await api('/api/mark-driver-period-paid',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        car_code:carCode,
        period_start:periodStart,
        period_end:periodEnd
      })
    });

    paymentRes.innerText=result.message||'';

    if(result.ok){
      await loadCars();
    }
  }catch(error){
    paymentRes.innerText=
      'Не удалось закрыть период: '+error;
  }
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

function overduePeriodsHtml(carCode,calc){
  const periods=calc.overdue_periods||[];

  if(!periods.length){
    return '<span class="raw">Нет долга</span>';
  }

  return `
    <div class="overdue-period-list">
      ${periods.map((period,index)=>`
        <div class="overdue-period-row">
          <div>
            <b>Неделя ${index+1}</b>
            <div class="raw">${period.label||''}</div>
            <div class="raw">
              ${period.payable_days||0} оплачиваемых дней ·
              простой ${period.downtime_days||0} дн.
            </div>
          </div>

          <div class="overdue-period-payment">
            <strong>${rub(period.amount||0)}</strong>

            ${
              index===0
                ? `
                  <button
                    class="small"
                    onclick="markDriverPeriodPaid(
                      '${carCode}',
                      '${period.period_start}',
                      '${period.period_end}'
                    )"
                  >
                    Оплачено
                  </button>
                `
                : `
                  <span class="raw">
                    Сначала предыдущая
                  </span>
                `
            }
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderDriverPayments(carsList){
  const configured=carsList.filter(
    car=>
      Number(car.daily_rent)>0 ||
      Number(car.weekly_payment)>0
  );

  if(!configured.length){
    driverPayments.innerHTML=
      '<tr><td>Расчёты водителей пока не настроены</td></tr>';
    return;
  }

  driverPayments.innerHTML=`
    <tr>
      <th>Машина</th>
      <th>Водитель</th>
      <th>Ставка</th>
      <th>Просроченные недели</th>
      <th>Текущий период</th>
      <th>Начислено сейчас</th>
      <th>Дата расчёта</th>
      <th>Статус</th>
      <th>Действие</th>
    </tr>

    ${configured.map(car=>{
      const calc=car.driver_payment||{};
      const current=calc.current_period||{};

      const rate=Number(
        calc.effective_daily_rent ||
        car.effective_daily_rent ||
        car.daily_rent ||
        0
      );

      const rateNote=
        calc.rate_source==='weekly_prorated'
          ? '<div class="raw">из недельной ставки</div>'
          : '';

      return `
        <tr>
          <td>${car.code}</td>
          <td>${car.driver||'Не указан'}</td>

          <td>
            ${rub(rate)} / сутки
            ${rateNote}
          </td>

          <td>
            ${overduePeriodsHtml(car.code,calc)}
          </td>

          <td>
            <div>
              <b>${current.label||'—'}</b>
            </div>
            <div class="raw">
              ${current.payable_days||0} оплачиваемых дней ·
              простой ${current.downtime_days||0} дн.
            </div>
          </td>

          <td>
            <b>${rub(calc.current_amount||0)}</b>
            <div class="raw">
              начисляется по дням
            </div>
          </td>

          <td>
            ${calc.next_payment_date||car.next_payment_date||'—'}
          </td>

          <td>
            ${
              Number(calc.overdue_periods_count||0)>0
                ? `<span class="driver-status-overdue">
                    ${calc.overdue_periods_count}
                    просроч. нед.
                  </span>`
                : paymentStatus(
                    calc.next_payment_date ||
                    car.next_payment_date
                  )
            }
          </td>

          <td>
            ${
              Number(calc.overdue_periods_count||0)>0
                ? '<span class="raw">Закрой недели по очереди</span>'
                : `
                  <button onclick="markPaymentPaid('${car.code}')">
                    Оплачено
                  </button>
                `
            }
          </td>
        </tr>
      `;
    }).join('')}
  `;
}

async function loadCars(){
  try{

  let c=await api('/api/cars');

  if(!Array.isArray(c)){
    throw new Error(
      c?.message || 'Сервер не вернул список машин'
    );
  }

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
        <td>${mileageCell(x)}</td>
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

  }catch(error){
    console.error('Ошибка загрузки машин:',error);

    paymentCar.innerHTML=
      '<option value="">Ошибка загрузки машин</option>';

    driverPayments.innerHTML=`
      <tr>
        <td class="bad">
          ${error.message || error}
        </td>
      </tr>
    `;

    cars.innerHTML=`
      <tr>
        <td class="bad">
          ${error.message || error}
        </td>
      </tr>
    `;
  }
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
  showAppPage('fleet');
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

let monthlyMileageByCar={};
let warehouseAutocompleteItems=[];
let warehouseSuggestionIndex=-1;
let warehouseAutocompleteTimer=null;
let selectedWarehouseItemIds=[];

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
  const variant=normalizeWarehouseSearch(item.variant);
  const haystack=(name+' '+brand+' '+variant).trim();

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
            ${item.part_name}
            ${item.brand?' · '+item.brand:''}
            ${item.variant?`<div class="warehouse-suggestion-variant">${item.variant}</div>`:''}
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

function renderSelectedWarehouseChips(){
  const box=document.getElementById('selectedWarehouseChips');

  if(!box){
    return;
  }

  const selected=warehouseAutocompleteItems.filter(
    item=>selectedWarehouseItemIds.includes(Number(item.id))
  );

  if(!selected.length){
    box.innerHTML='';
    box.classList.remove('open');
    return;
  }

  box.classList.add('open');
  box.innerHTML=`
    <div class="selected-warehouse-label">
      Будет списано со склада:
    </div>
    ${selected.map(item=>`
      <span class="selected-warehouse-chip">
        ${item.part_name}
        ${item.brand?' · '+item.brand:''}
        ${item.variant?' · '+item.variant:''}
        <button
          type="button"
          onclick="removeSelectedWarehouseItem(${item.id})"
          title="Убрать"
        >×</button>
      </span>
    `).join('')}
  `;
}

function removeSelectedWarehouseItem(itemId){
  selectedWarehouseItemIds=selectedWarehouseItemIds.filter(
    id=>Number(id)!==Number(itemId)
  );
  renderSelectedWarehouseChips();
}

function selectWarehouseSuggestion(itemId){
  const item=warehouseAutocompleteItems.find(
    value=>Number(value.id)===Number(itemId)
  );

  if(!item){
    return;
  }

  const numericId=Number(item.id);

  if(!selectedWarehouseItemIds.includes(numericId)){
    selectedWarehouseItemIds.push(numericId);
  }

  // Название детали больше не добавляется в строку.
  // Пользовательский текст остаётся коротким и не смешивается
  // с длинным складским названием.
  renderSelectedWarehouseChips();

  document
    .getElementById('warehouseSuggestions')
    .classList.remove('open');

  document.getElementById('msg').focus();
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
    if(!input.value.trim() && !selectedWarehouseItemIds.length){
      renderSelectedWarehouseChips();
    }

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

async function add(){
  let m=msg.value;

  try{
    let r=await api('/api/add',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        message:m,
        warehouse_item_ids:selectedWarehouseItemIds
      })
    });

    res.innerText=r.message||JSON.stringify(r);

    if(r.ok){
      msg.value='';
      selectedWarehouseItemIds=[];
      renderSelectedWarehouseChips();
      await preloadWarehouseAutocomplete();
    }

    load();
  }catch(e){
    res.innerText='Ошибка: '+e;
  }
}


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
        ${i.part_name} ${i.brand||''}${i.variant?' · '+i.variant:''} — ${i.quantity} шт.
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
        ${i.variant?`<div class="raw">${i.variant}</div>`:''}
      </div>
      <div class="warehouse-stock">${i.quantity} шт.</div>
      <div class="raw">
        Минимум: ${i.min_quantity} шт.
        ${i.shelf?` · Полка: ${i.shelf}`:''}
      </div>
      ${i.low_stock?'<p class="bad">⚠️ Нужно пополнить</p>':''}

      <div class="warehouse-actions">
        <button onclick="openWarehouseEditor(${i.id})">Исправить</button>
        <button onclick="manualWarehouseWriteOff(${i.id})">Списать</button>
        <button class="danger" onclick="deleteWarehouseItem(${i.id})">Удалить</button>
      </div>

      <div id="warehouse_editor_${i.id}" class="warehouse-editor">
        <div class="warehouse-editor-grid">
          <input id="warehouse_edit_part_${i.id}" value="${String(i.part_name||'').replaceAll('"','&quot;')}" placeholder="Название">
          <input id="warehouse_edit_brand_${i.id}" value="${String(i.brand||'').replaceAll('"','&quot;')}" placeholder="Бренд">
          <input id="warehouse_edit_variant_${i.id}" value="${String(i.variant||'').replaceAll('"','&quot;')}" placeholder="Исполнение">
          <input id="warehouse_edit_shelf_${i.id}" value="${String(i.shelf||'').replaceAll('"','&quot;')}" placeholder="Полка">
          <input id="warehouse_edit_min_${i.id}" type="number" min="0" value="${i.min_quantity||0}" placeholder="Минимум">
          <input id="warehouse_edit_quantity_${i.id}" type="number" min="0" value="${i.quantity||0}" placeholder="Фактический остаток">
          <input id="warehouse_edit_comment_${i.id}" class="warehouse-editor-full" value="${String(i.comment||'').replaceAll('"','&quot;')}" placeholder="Комментарий">
        </div>

        <div class="warehouse-actions">
          <button onclick="saveWarehouseItemEdit(${i.id})">Сохранить</button>
          <button onclick="closeWarehouseEditor(${i.id})">Отмена</button>
        </div>
      </div>
    </div>
  `).join('');
}


function openWarehouseEditor(itemId){
  document.getElementById(`warehouse_editor_${itemId}`)?.classList.add('open');
}

function closeWarehouseEditor(itemId){
  document.getElementById(`warehouse_editor_${itemId}`)?.classList.remove('open');
}

async function saveWarehouseItemEdit(itemId){
  const currentItem=warehouseAutocompleteItems.find(item=>Number(item.id)===Number(itemId));
  const newQuantity=Number(document.getElementById(`warehouse_edit_quantity_${itemId}`).value||0);

  let result=await api('/api/warehouse/update-item',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      item_id:itemId,
      part_name:document.getElementById(`warehouse_edit_part_${itemId}`).value,
      brand:document.getElementById(`warehouse_edit_brand_${itemId}`).value,
      variant:document.getElementById(`warehouse_edit_variant_${itemId}`).value,
      shelf:document.getElementById(`warehouse_edit_shelf_${itemId}`).value,
      min_quantity:Number(document.getElementById(`warehouse_edit_min_${itemId}`).value||0),
      comment:document.getElementById(`warehouse_edit_comment_${itemId}`).value
    })
  });

  if(!result.ok){
    warehouseRes.innerText=result.message||'Ошибка';
    return;
  }

  if(currentItem && Number(currentItem.quantity||0)!==newQuantity){
    result=await api('/api/warehouse/adjust',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        item_id:itemId,
        new_quantity:newQuantity,
        comment:'Исправление остатка через карточку склада'
      })
    });
  }

  warehouseRes.innerText=result.message||'Изменения сохранены';
  await loadWarehouse();
  await preloadWarehouseAutocomplete();
}

async function manualWarehouseWriteOff(itemId){
  const quantityText=prompt('Сколько штук списать?','1');
  if(quantityText===null)return;

  const quantity=Number(quantityText);
  if(!Number.isInteger(quantity)||quantity<=0){
    alert('Укажи целое количество больше нуля');
    return;
  }

  const comment=prompt('Причина списания: брак, потеря, использовано вручную','Ручное списание');
  if(comment===null)return;

  const result=await api('/api/warehouse/write-off',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({item_id:itemId,quantity,comment})
  });

  warehouseRes.innerText=result.message||'';
  if(result.ok){
    await loadWarehouse();
    await preloadWarehouseAutocomplete();
  }
}

async function deleteWarehouseItem(itemId){
  if(!confirm('Удалить позицию? Это возможно только при остатке 0.'))return;

  const result=await api(`/api/warehouse/delete-item/${itemId}`,{method:'POST'});
  warehouseRes.innerText=result.message||'';

  if(result.ok){
    await loadWarehouse();
    await preloadWarehouseAutocomplete();
  }
}

async function addWarehouseItem(){
  const payload={
    part_name:warehouse_part.value,
    brand:warehouse_brand.value,
    variant:warehouse_variant.value,
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
    warehouse_variant.value='';
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
async function safeLoadSection(name, loader){
  try{
    await loader();
    return true;
  }catch(error){
    console.error(`Ошибка загрузки раздела ${name}:`,error);
    return false;
  }
}

async function load(){
  // Машины и водители загружаются первыми и независимо от инвесторов.
  // Ошибка одного раздела больше не останавливает остальные.
  await safeLoadSection(
    'месячный пробег',
    loadMonthlyMileage
  );

  await safeLoadSection(
    'машины и водители',
    loadCars
  );

  await Promise.all([
    safeLoadSection('главные показатели',loadSummary),
    safeLoadSection('итоги инвесторов',loadInvestorsSummary),
    safeLoadSection('инвесторы',loadInvestors),
    safeLoadSection('сравнение месяцев',loadMonthlyFleetFinance),
    safeLoadSection('последние операции',loadOps)
  ]);
}


if(document.getElementById('driverPayments')){
  driverPayments.innerHTML=`
    <tr>
      <td class="raw">Загрузка расчётов водителей…</td>
    </tr>
  `;
}

msg.addEventListener('keydown',e=>{if(e.key==='Enter')add()});
preloadWarehouseAutocomplete();
setupWarehouseAutocomplete();
load();
</script>
</body>
</html>
'''
