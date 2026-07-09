from flask import Flask, request, jsonify
import os, time, json, requests, threading

_ENV = {}
def load_env():
    env = {}
    try:
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    k, _, v = line.partition('=')
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except: pass
    return env

_ENV.update(load_env())

app = Flask(__name__)

GITHUB_TOKEN = _ENV.get('GITHUB_TOKEN', '')
GITHUB_OWNER = _ENV.get('GITHUB_OWNER', 'zidanebarkat')
GITHUB_REPO = _ENV.get('GITHUB_REPO', 'strm01')
config_path = 'fb_config.json'
log_buffer = []
log_lock = threading.Lock()

DEFAULTS = {
    'source_url': 'https://strm01.vip/?m=30724&lang=ar',
    'fb_key': '',
    'github_token': GITHUB_TOKEN,
    'github_owner': GITHUB_OWNER,
    'github_repo': GITHUB_REPO,
}

def load_config():
    try:
        with open(config_path) as f:
            return {**DEFAULTS, **json.load(f)}
    except:
        return dict(DEFAULTS)

def save_config(cfg):
    with open(config_path, 'w') as f:
        json.dump(cfg, f)

def log(msg):
    with log_lock:
        ts = time.strftime('%H:%M:%S')
        log_buffer.append(f'[{ts}] {msg}')
        if len(log_buffer) > 200:
            log_buffer[:] = log_buffer[-200:]

def trigger_workflow(source_url, fb_key):
    cfg = load_config()
    token = cfg.get('github_token') or GITHUB_TOKEN
    owner = cfg.get('github_owner') or GITHUB_OWNER
    repo = cfg.get('github_repo') or GITHUB_REPO
    if not token or not owner or not repo:
        return None, 'Missing GitHub config'
    url = f'https://api.github.com/repos/{owner}/{repo}/actions/workflows/stream.yml/dispatches'
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json'}
    inputs = {'source_url': source_url, 'fb_key': fb_key}
    r = requests.post(url, json={'ref': 'main', 'inputs': inputs}, headers=headers)
    if r.status_code not in (204, 201, 200):
        return None, f'GitHub API error: {r.status_code} {r.text[:200]}'
    return 'triggered', None

def cancel_active_run():
    cfg = load_config()
    token = cfg.get('github_token') or GITHUB_TOKEN
    owner = cfg.get('github_owner') or GITHUB_OWNER
    repo = cfg.get('github_repo') or GITHUB_REPO
    if not token or not owner or not repo:
        return
    for status in ('in_progress', 'queued', 'pending'):
        url = f'https://api.github.com/repos/{owner}/{repo}/actions/workflows/stream.yml/runs?status={status}&per_page=1'
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json'}
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            runs = r.json().get('workflow_runs', [])
            if runs:
                rid = runs[0]['id']
                requests.post(f'https://api.github.com/repos/{owner}/{repo}/actions/runs/{rid}/cancel',
                    headers=headers)
                log(f'Cancelled run {rid}')
                return rid
    return None

def get_active_run():
    cfg = load_config()
    token = cfg.get('github_token') or GITHUB_TOKEN
    owner = cfg.get('github_owner') or GITHUB_OWNER
    repo = cfg.get('github_repo') or GITHUB_REPO
    if not token or not owner or not repo:
        return None
    for status in ('in_progress', 'queued', 'pending'):
        url = f'https://api.github.com/repos/{owner}/{repo}/actions/workflows/stream.yml/runs?status={status}&per_page=1'
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json'}
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            runs = r.json().get('workflow_runs', [])
            if runs:
                return runs[0]
    return None

@app.route('/')
def index():
    return HTML_PANEL

@app.route('/preview')
def preview_page():
    try:
        with open('preview.html') as f:
            return f.read()
    except:
        return 'preview.html not found', 404

@app.route('/config', methods=['POST'])
def update_config():
    data = request.get_json(force=True)
    cfg = load_config()
    for k in DEFAULTS:
        if k in data:
            cfg[k] = data[k]
    save_config(cfg)
    return jsonify({'ok': True, 'config': cfg})

@app.route('/status')
def get_status():
    cfg = load_config()
    run = get_active_run()
    live = run is not None
    return jsonify({
        'live': live, 'config': cfg,
        'run_id': run.get('id') if run else None,
        'run_status': run.get('status') if run else None,
        'run_started': run.get('run_started_at') if run else None,
    })

@app.route('/start')
def start_stream():
    cfg = load_config()
    source = cfg.get('source_url', '')
    fb_key = cfg.get('fb_key', '')
    if not source:
        return jsonify({'ok': False, 'error': 'No source URL'})
    if not fb_key:
        return jsonify({'ok': False, 'error': 'No Facebook stream key'})
    cancel_active_run()
    msg, err = trigger_workflow(source, fb_key)
    if err:
        return jsonify({'ok': False, 'error': err})
    log('Workflow triggered')
    return jsonify({'ok': True, 'msg': msg})

@app.route('/stop')
def stop_stream():
    rid = cancel_active_run()
    if rid:
        log(f'Stopped run {rid}')
        return jsonify({'ok': True})
    log('Nothing to stop')
    return jsonify({'ok': True, 'msg': 'nothing running'})

@app.route('/logs')
def get_logs():
    with log_lock:
        return '\n'.join(log_buffer[-100:]), 200, {'Content-Type': 'text/plain'}

@app.route('/workflow_logs')
def workflow_logs():
    cfg = load_config()
    token = cfg.get('github_token') or GITHUB_TOKEN
    owner = cfg.get('github_owner') or GITHUB_OWNER
    repo = cfg.get('github_repo') or GITHUB_REPO
    run = get_active_run()
    if not run:
        return jsonify({'ok': True, 'logs': 'No active run'})
    rid = run['id']
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json'}
    r = requests.get(f'https://api.github.com/repos/{owner}/{repo}/actions/runs/{rid}/jobs',
        headers=headers)
    if r.status_code == 200:
        jobs = r.json().get('jobs', [])
        if jobs and jobs[0].get('logs_url'):
            r2 = requests.get(jobs[0]['logs_url'], headers=headers)
            if r2.status_code == 200:
                lines = r2.text.split('\n')
                return jsonify({'ok': True, 'logs': '\n'.join(lines[-200:])})
    return jsonify({'ok': True, 'logs': f'Run {rid} - status: {run.get("status")}'})

@app.route('/resolve')
def resolve_source():
    from urllib.parse import urlparse
    cfg = load_config()
    url = cfg.get('source_url', '')
    if not url:
        return jsonify({'ok': False, 'error': 'No source URL'}), 400
    import subprocess
    try:
        r = subprocess.run(['yt-dlp', '--socket-timeout', '15', '-g', url],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
            if lines:
                return jsonify({'ok': True, 'hls': lines[-1], 'source': url})
    except: pass
    return jsonify({'ok': False, 'error': 'Not live'}), 400

HTML_PANEL = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>strm01 - Facebook Stream Panel</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9}
.container{max-width:700px;margin:0 auto;padding:20px}
h1{font-size:22px;margin-bottom:20px;color:#fff}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:16px}
.card h2{font-size:16px;margin-bottom:12px;color:#f0f6fc}
.form-group{margin-bottom:12px}
.form-group label{display:block;font-size:13px;color:#8b949e;margin-bottom:4px}
.form-group input{width:100%;padding:8px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px}
.form-group input:focus{outline:none;border-color:#58a6ff}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 24px;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-green{background:#238636;color:#fff}
.btn-green:hover:not(:disabled){background:#2ea043}
.btn-red{background:#da3633;color:#fff}
.btn-red:hover:not(:disabled){background:#f85149}
.btn-blue{background:#1f6feb;color:#fff}
.btn-blue:hover:not(:disabled){background:#388bfd}
.btn-grey{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-grey:hover:not(:disabled){background:#30363d}
.btn-sm{padding:6px 14px;font-size:13px}
.actions{display:flex;gap:12px;margin:12px 0;flex-wrap:wrap}
.status-bar{display:flex;align-items:center;gap:16px;padding:12px 16px;background:#0d1117;border:1px solid #30363d;border-radius:6px;margin-bottom:16px}
.status-dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}
.status-dot.live{background:#3fb950;box-shadow:0 0 8px #3fb950}
.status-dot.stopped{background:#f85149}
.log-box{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;height:300px;overflow-y:auto;font-family:monospace;font-size:12px;line-height:1.5;white-space:pre-wrap}
.log-box .info{color:#8b949e}
.log-box .err{color:#f85149}
.log-box .ok{color:#3fb950}
</style>
</head>
<body>
<div class="container">
<h1>strm01 &#8594; Facebook</h1>
<div class="status-bar">
  <span><span class="status-dot" id="statusDot"></span><span class="status-text" id="statusText">Checking...</span></span>
</div>
<div class="card">
  <h2>Config</h2>
  <div class="form-group">
    <label>Source URL</label>
    <input type="url" name="source_url" id="source_url" placeholder="https://strm01.vip/?m=30724&lang=ar">
  </div>
  <div class="form-group">
    <label>Facebook Stream Key</label>
    <input type="password" name="fb_key" id="fb_key" placeholder="Facebook stream key">
  </div>
  <div class="form-group">
    <label>GitHub Token</label>
    <input type="password" name="github_token" id="github_token" placeholder="ghp_...">
  </div>
</div>
<div class="actions">
  <button class="btn btn-green" id="btnGoLive" onclick="goLive()">&#9654; Start Stream</button>
  <button class="btn btn-red" id="btnStop" onclick="stopStream()" disabled>&#9632; Stop</button>
  <button class="btn btn-blue btn-sm" onclick="saveConfig()">&#128190; Save</button>
  <button class="btn btn-grey btn-sm" onclick="testSource()">&#128269; Test Source</button>
  <button class="btn btn-grey btn-sm" onclick="fetchWorkflowLogs()">&#128196; Logs</button>
</div>
<div id="testResult" style="font-size:12px;color:#8b949e;margin-top:8px"></div>
<div class="card">
  <h2>Logs</h2>
  <div class="log-box" id="logBox">Waiting...</div>
</div>
</div>
<script>
function applyForm(c) {
  if (!c) return;
  for (const [k,v] of Object.entries(c)) {
    const el = document.getElementById(k);
    if (el) el.value = v;
  }
}
function readForm() {
  const d = {};
  document.querySelectorAll('input').forEach(el => {
    if (el.name) d[el.name] = el.value;
  });
  return d;
}
function saveConfig(cb) {
  fetch('/config', {method:'POST', body:JSON.stringify(readForm()), headers:{'Content-Type':'application/json'}})
    .then(r=>r.json()).then(d=>{ addLog('Saved','ok'); if(cb) cb(); })
    .catch(e=>{ addLog('Save failed','err'); if(cb) cb(); });
}
function testSource() {
  const el = document.getElementById('testResult');
  el.textContent = 'Checking...';
  fetch('/resolve').then(r=>r.json()).then(d=>{
    el.textContent = d.ok ? '✓ Live' : '✗ Not live';
  }).catch(()=>el.textContent='✗ Failed');
}
function goLive() {
  document.getElementById('btnGoLive').disabled = true;
  addLog('Starting...','info');
  saveConfig(() => {
    fetch('/start').then(r=>r.json()).then(d=>{
      if(!d.ok) { addLog('Error: '+d.error,'err'); document.getElementById('btnGoLive').disabled = false; }
    }).catch(e=>{ addLog('Start failed','err'); document.getElementById('btnGoLive').disabled = false; });
  });
}
function stopStream() {
  document.getElementById('btnStop').disabled = true;
  addLog('Stopping...','info');
  fetch('/stop').then(r=>r.json()).then(d=>{
    addLog(d.ok ? 'Stopped' : 'Error: '+d.error, d.ok ? 'ok' : 'err');
  }).catch(e=>addLog('Stop failed','err'));
}
function addLog(msg,cls='info') {
  const box = document.getElementById('logBox');
  box.innerHTML += '<span class="'+cls+'">['+new Date().toLocaleTimeString()+'] '+msg+'</span>\n';
  box.scrollTop = box.scrollHeight;
}
function updateStatus() {
  fetch('/status').then(r=>r.json()).then(d=>{
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    if(d.live) {
      dot.className = 'status-dot live';
      txt.textContent = '\u25cf LIVE' + (d.run_id ? ' (run '+d.run_id+')' : '');
      document.getElementById('btnGoLive').disabled = true;
      document.getElementById('btnStop').disabled = false;
    } else {
      dot.className = 'status-dot stopped';
      txt.textContent = '\u25cb Stopped';
      document.getElementById('btnGoLive').disabled = false;
      document.getElementById('btnStop').disabled = true;
    }
    if(d.config) applyForm(d.config);
  }).catch(()=>{});
}
function fetchWorkflowLogs() {
  addLog('Fetching workflow logs...','info');
  fetch('/workflow_logs').then(r=>r.json()).then(d=>{
    addLog('--- Workflow Logs ---','ok');
    if(d.logs) document.getElementById('logBox').innerHTML += d.logs.substring(-3000) + '\n';
  }).catch(e=>{ addLog('Failed: '+e,'err'); });
}
fetch('/status').then(r=>r.json()).then(d=>{ if(d.config) applyForm(d.config); });
setInterval(updateStatus, 3000);
setInterval(function(){
  fetch('/logs').then(r=>r.text()).then(t=>{
    const box = document.getElementById('logBox');
    if(t) box.innerHTML = t;
    box.scrollTop = box.scrollHeight;
  }).catch(()=>{});
}, 2000);
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
