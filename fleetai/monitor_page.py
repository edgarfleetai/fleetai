"""Owner-only live map of the fleet (read-only, positions from /api/wialon/positions)."""

MONITOR_HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Мониторинг — FleetAI</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>
:root{--bg:#0b0d0c;--panel:#14171a;--line:#262b2f;--fg:#eef2ee;--muted:#9aa39c;--lime:#c8f560;--warn:#f5b860;--bad:#f07a6a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:14px 16px}h1{font-size:20px;margin:0 auto 0 0}
a{color:var(--muted)}.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:99px;padding:6px 12px;cursor:pointer;font:inherit}.chip.on{background:var(--lime);color:#111;border-color:transparent}
main{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:12px;padding:0 16px 16px}@media(max-width:860px){main{grid-template-columns:1fr}}
#map{height:calc(100vh - 90px);min-height:420px;border-radius:14px;border:1px solid var(--line)}
aside{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px;overflow:auto;max-height:calc(100vh - 90px)}
.row{display:flex;gap:10px;align-items:center;padding:9px 6px;border-bottom:1px solid var(--line);cursor:pointer}.row:last-child{border:0}
.dot{width:10px;height:10px;border-radius:50%;flex:none}.t{flex:1;min-width:0}.t b{display:block}.t span{color:var(--muted);font-size:12.5px}
.note{color:var(--muted);font-size:12.5px;padding:6px}.err{color:var(--bad)}
.leaflet-container{background:#1b1f22}.lbl{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:2px 6px;font-weight:600;box-shadow:none}
.lbl:before{display:none}
</style></head><body>
<header><h1>Мониторинг</h1><div class="chips" id="cities"></div><span class="note" id="upd">Загрузка…</span><a href="/">← Главная</a></header>
<main><div id="map" role="img" aria-label="Карта машин"></div><aside><div id="list"></div><div class="note">Только чтение из Wialon. Команды машинам отсюда не отправляются.</div></aside></main>
<script>
(() => {
'use strict';
const CITIES = [["Все",55.73,50.75,8],["Казань",55.79,49.12,12],["Наб. Челны",55.73,52.40,12],["Елабуга",55.76,52.05,13],["Нижнекамск",55.635,51.82,13]];
const STALE = 15 * 60;
const map = L.map('map', {zoomControl: true}).setView([55.73, 50.75], 8);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© участники OpenStreetMap'}).addTo(map);
const cities = document.getElementById('cities');
CITIES.forEach(([n, la, lo, z], i) => {
  const b = document.createElement('button'); b.className = 'chip' + (i ? '' : ' on'); b.textContent = n;
  b.onclick = () => { map.setView([la, lo], z); cities.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c === b)); };
  cities.appendChild(b);
});
const markers = new Map();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function ago(t) { if (!t) return 'нет данных'; const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? 'только что' : s < 3600 ? Math.round(s / 60) + ' мин назад' : s < 86400 ? Math.round(s / 3600) + ' ч назад' : Math.round(s / 86400) + ' дн назад'; }
function state(u) { if (u.lat == null) return ['нет позиции', 'var(--muted)']; if (!u.time || Date.now() / 1000 - u.time > STALE) return ['нет связи', 'var(--warn)']; return u.speed_kmh > 3 ? ['едет · ' + u.speed_kmh + ' км/ч', 'var(--lime)'] : ['стоит', '#7fb8f5']; }
async function load() {
  try {
    const r = await fetch('/api/wialon/positions', {credentials: 'same-origin', cache: 'no-store'});
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.message || ('HTTP ' + r.status));
    const list = document.getElementById('list'); list.innerHTML = '';
    d.units.forEach(u => {
      const [txt, col] = state(u);
      const row = document.createElement('div'); row.className = 'row';
      row.innerHTML = `<i class="dot" style="background:${col}"></i><div class="t"><b>${esc(u.name)}</b><span>${esc(txt)} · ${esc(ago(u.time))}</span></div>`;
      if (u.lat != null) {
        let m = markers.get(u.id);
        if (!m) { m = L.circleMarker([u.lat, u.lon], {radius: 8, weight: 2, color: '#0b0d0c', fillOpacity: 1}).addTo(map).bindTooltip('', {permanent: true, direction: 'right', className: 'lbl', offset: [8, 0]}); markers.set(u.id, m); }
        m.setLatLng([u.lat, u.lon]).setStyle({fillColor: col}).setTooltipContent(esc(u.name));
        row.onclick = () => map.setView([u.lat, u.lon], 15);
      }
      list.appendChild(row);
    });
    document.getElementById('upd').textContent = 'Обновлено ' + new Date().toLocaleTimeString('ru-RU');
    document.getElementById('upd').classList.remove('err');
  } catch (e) {
    const u = document.getElementById('upd'); u.textContent = 'Ошибка: ' + e.message; u.classList.add('err');
  }
}
load(); setInterval(load, 30000);
})();
</script></body></html>"""
