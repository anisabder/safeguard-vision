# Read-only web dashboard for Safe Guard.
# Shows state, Uno status, gas level and recent events. No camera feed and no photos,
# so faces are never published. Optional access key: DASH_TOKEN.
import json, os
from flask import Flask, jsonify, request, abort, Response

PATH = os.environ.get("SG_STATUS", "status.json")
TOKEN = os.environ.get("DASH_TOKEN", "")
app = Flask(__name__)

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Safe Guard</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:16px}
h1{font-size:22px;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:12px}
.card{background:#1e293b;border-radius:12px;padding:14px}
.label{font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
.big{font-size:28px;font-weight:700;margin-top:6px}
.badge{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700}
.IDLE{background:#14532d;color:#bbf7d0}.VERIFY{background:#713f12;color:#fde68a}
.ALARM{background:#7f1d1d;color:#fecaca}.OFFLINE{background:#334155;color:#e2e8f0}
.bar{height:14px;background:#334155;border-radius:7px;overflow:hidden;margin-top:8px}
.fill{height:100%;width:0;background:#22c55e;transition:width .5s}
.events{list-style:none;padding:0;margin:0}
.events li{padding:8px 0;border-bottom:1px solid #334155;display:flex;gap:12px}
.t{color:#94a3b8;min-width:64px;font-variant-numeric:tabular-nums}
.alarm{color:#f87171}.warn{color:#fbbf24}.ok{color:#4ade80}.info{color:#93c5fd}
.stale{color:#f87171;font-size:14px;min-height:20px}
</style></head><body>
<h1>Safe Guard: live status</h1>
<div class="grid">
  <div class="card"><div class="label">System state</div>
    <div class="big"><span id="state" class="badge">-</span></div>
    <div id="verify" class="label" style="margin-top:8px"></div></div>
  <div class="card"><div class="label">Sensor board</div><div class="big" id="uno">-</div></div>
  <div class="card"><div class="label">Gas level (0 to 1023)</div>
    <div class="big" id="gas">-</div>
    <div class="bar"><div class="fill" id="gasbar"></div></div>
    <div class="label" id="gasnote" style="margin-top:8px"></div></div>
</div>
<div class="card"><div class="label">Recent events</div><ul class="events" id="events"></ul></div>
<p class="stale" id="stale"></p>
<script>
const key = new URLSearchParams(location.search).get('key') || '';
function render(d) {
  const st = document.getElementById('state');
  st.textContent = d.state; st.className = 'badge ' + d.state;
  document.getElementById('verify').textContent =
    d.state === 'VERIFY' ? 'Checking the area for ' + d.verify_left + ' s' : '';
  document.getElementById('uno').textContent = d.uno || '-';
  const g = d.gas_level;
  document.getElementById('gas').textContent = (g == null) ? '-' : g;
  const fill = document.getElementById('gasbar');
  fill.style.width = (g == null ? 0 : Math.min(100, g / 10.23)) + '%';
  fill.style.background = d.gas_active ? '#ef4444' : '#22c55e';
  document.getElementById('gasnote').textContent = d.gas_active ? 'Gas alarm active' : 'Normal';
  const ul = document.getElementById('events');
  ul.textContent = '';
  (d.events || []).slice().reverse().forEach(e => {
    const li = document.createElement('li');
    const t = document.createElement('span'); t.className = 't'; t.textContent = e.time;
    const x = document.createElement('span'); x.className = e.kind; x.textContent = e.text;
    li.append(t, x); ul.append(li);
  });
}
async function tick() {
  const stale = document.getElementById('stale');
  try {
    const r = await fetch('/api/status?key=' + encodeURIComponent(key));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    render(d);
    const age = Date.now() / 1000 - (d.ts || 0);
    stale.textContent = age > 5 ? 'No update from the PC for ' + Math.round(age) + ' s' : '';
  } catch (e) {
    stale.textContent = 'Cannot reach the dashboard (' + e.message + ')';
  }
}
tick();
setInterval(tick, 1000);
</script></body></html>"""

def load():
    try:
        with open(PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"state": "OFFLINE", "uno": "no data", "events": [], "ts": 0}

@app.before_request
def check_key():
    if TOKEN and request.args.get("key") != TOKEN:
        abort(403)

@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")

@app.route("/api/status")
def api_status():
    return jsonify(load())

if __name__ == "__main__":
    # bound to 127.0.0.1 on purpose: the public address comes from the tunnel, not your network
    app.run(host="127.0.0.1", port=8000)
