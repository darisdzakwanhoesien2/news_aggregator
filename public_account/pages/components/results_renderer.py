import json
import streamlit.components.v1 as components

def render(result_json, height=800):
    # Safely escape JSON for inclusion in JS context
    def _safe_json_for_js(obj):
        return json.dumps(obj).replace('</', '<\\/')

    payload = _safe_json_for_js(result_json or {})
    # Use a plain string and replace a unique placeholder to avoid Python f-string
    # interpolation issues with JS template literals (${...}) in the HTML.
    html_template = """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Verification Results</title>
<style>
  :root{/*bg:#fff;--muted:#6b7280;--card:#f8fafc;--accent:#2563eb;--good:#16a34a;--warn:#f59e0b;--bad:#ef4444;*/}
  body{font-family:Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; margin:12px; background:var(--bg); color:#111}
  .row{display:flex;gap:12px;flex-wrap:wrap}
  .card{background:linear-gradient(180deg,#fff,#fbfdff);padding:14px;border-radius:10px;border:1px solid #e6eef8;box-shadow:0 2px 6px rgba(16,24,40,0.04)}
  .metric{
    min-width:160px;padding:16px;border-radius:8px;background:#fff;border:1px solid #eef2ff;
  }
  .metric h3{margin:0;color:var(--muted);font-weight:600;font-size:13px}
  .metric p{margin:6px 0 0;font-size:20px;font-weight:800;color:var(--accent)}
  .pill{display:inline-block;padding:6px 10px;border-radius:999px;background:#eef2ff;color:var(--accent);font-weight:700}
  .pillar-grid{display:flex;gap:10px;flex-wrap:wrap}
  .pillar-card{flex:1;min-width:180px;padding:12px;border-radius:8px;background:#fff;border:1px solid #f1f5f9}
  table{width:100%;border-collapse:collapse;margin-top:8px}
  th,td{text-align:left;padding:8px;border-bottom:1px solid #f3f4f6;font-size:13px}
  pre{background:#0f172a;color:#f8fafc;padding:12px;border-radius:8px;overflow:auto;max-height:320px}
  .btn{display:inline-block;padding:8px 12px;border-radius:8px;background:var(--accent);color:white;text-decoration:none}
  details summary{cursor:pointer;font-weight:700;margin-bottom:6px}
  .evidence{font-size:13px;color:#0f172a;background:#f8fafc;padding:8px;border-radius:6px;border:1px dashed #e6eef8}
  .small{font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<div id="app" class="card"></div>

<script>
const RESULT = __RESULT_PAYLOAD__;

function mkMetric(title, value, hint='') {
  return `<div class="metric card"><h3>${title}</h3><p title="${hint}">${value}</p></div>`;
}

function renderTop(container, result) {
  const scores = result.scores || [];
  const company = result.company || '—';
  // compute aggregated totals
  let totalFinal = 0, totalMax = 0;
  scores.forEach(r => {
    totalFinal += Number(r['Final Score'] || r['Final_Score'] || 0);
    totalMax += Number(r['Max Score'] || r['Max_Score'] || r['MaxScore'] || 0);
  });
  const pct = totalMax ? Math.round(totalFinal / totalMax * 1000)/10 : 0;
  container.innerHTML += `
    <div class="row" style="align-items:center;margin-bottom:12px">
      <div style="flex:1">
        <h2 style="margin:0">${company} <span class="pill">Session: ${result.session_id || '—'}</span></h2>
        <div class="small">User: <code>${result.username || result.user || ''}</code> · ${new Date(result.timestamp || Date.now()).toLocaleString()}</div>
      </div>
      <div style="display:flex;gap:8px">
        ${mkMetric('Final Score', `${totalFinal.toFixed(1)} / ${totalMax.toFixed(1)}`, 'Final / Max')}
        ${mkMetric('% Verified', `${pct}%`)}
        ${mkMetric('Questions', scores.length)}
      </div>
    </div>
  `;
}

function renderPillars(container, result) {
  const scores = result.scores || [];
  const pillars = {};
  scores.forEach(r => {
    const p = r.Pillar || r.pillar || 'Other';
    if (!pillars[p]) pillars[p] = {final:0, max:0, questions:0};
    const fin = Number(r['Final Score'] || r['Final_Score'] || 0);
    const mx  = Number(r['Max Score'] || r['Max_Score'] || r['MaxScore'] || 0);
    pillars[p].final += fin;
    pillars[p].max += mx;
    pillars[p].questions += 1;
  });
  let html = '<div class="pillar-grid">';
  Object.keys(pillars).forEach(k => {
    const p = pillars[k];
    const pct = p.max ? Math.round(p.final / p.max * 1000)/10 : 0;
    html += `<div class="pillar-card"><strong>${k}</strong><div style="margin-top:8px"><div class="small">Questions: ${p.questions}</div><div style="margin-top:8px"><strong>${p.final.toFixed(1)}</strong> / ${p.max.toFixed(1)} — <span class="small">${pct}%</span></div></div></div>`;
  });
  html += '</div>';
  container.innerHTML += `<h3>Pillar breakdown</h3>` + html;
}

function renderTable(container, result) {
  const scores = result.scores || [];
  if (!scores.length) return;
  const cols = Object.keys(scores[0]);
  let html = '<table><thead><tr>';
  cols.forEach(c => html += `<th>${c}</th>`);
  html += '</tr></thead><tbody>';
  scores.forEach(r => {
    html += '<tr>';
    cols.forEach(c => html += `<td>${String(r[c] ?? '')}</td>`);
    html += '</tr>';
  });
  html += '</tbody></table>';
  container.innerHTML += `<h3>Score table</h3>` + html;
}

function renderDetail(container, result) {
  const scores = result.scores || [];
  if (!scores.length) return;
  let html = '';
  scores.forEach(r => {
    const id = r.ID || r.id || '';
    const q = r.Question || r.question || '';
    const stt = r.Status || r.status || '';
    const conf = r.Confidence || r.confidence || '';
    const evidence = r['Evidence Quote'] || r.evidence_quote || '';
    html += `<details class="card"><summary>${id} — ${q.slice(0,120)}</summary><div style="padding:8px"><div class="small"><strong>Status:</strong> ${stt} · <strong>Confidence:</strong> ${conf}</div><p><strong>Selected:</strong> ${r.Selected || r.selected || ''}</p>`;
    if (evidence) html += `<div class="evidence">${evidence}</div>`;
    if (r.Reasoning || r.reasoning) html += `<pre>${String(r.Reasoning || r.reasoning)}</pre>`;
    html += `</div></details>`;
  });
  container.innerHTML += `<h3>Question detail</h3>` + html;
}

function renderRaw(container, result) {
  const raw = JSON.stringify(result.verifications || result, null, 2);
  container.innerHTML += `<h3>Raw LLM / Verifications JSON</h3><pre>${raw}</pre>`;
}

function renderDownloads(container, result) {
  const j = JSON.stringify(result, null, 2);
  const csvRows = [];
  const scores = result.scores || [];
  if (scores.length) {
    const cols = Object.keys(scores[0]);
    csvRows.push(cols.join(','));
    scores.forEach(r => {
      csvRows.push(cols.map(c => `"${String((r[c]??'')).replace(/"/g,'""')}"`).join(','));
    });
  }
  const csv = csvRows.join('\\n');
  container.innerHTML += `<div style="margin-top:8px"><a class="btn" id="dlJson">Download JSON</a> <a class="btn" id="dlCsv">Download CSV</a></div>`;
  document.getElementById('dlJson').onclick = () => {
    const blob = new Blob([j], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `${(result.company||'session') }_${(result.session_id||'sess')}_verification.json`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };
  document.getElementById('dlCsv').onclick = () => {
    const blob = new Blob([csv], {type: 'text/csv'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `${(result.company||'session') }_${(result.session_id||'sess')}_scores.csv`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };
}

// bootstrap
const app = document.getElementById('app');
app.innerHTML = '';
renderTop(app, RESULT);
renderPillars(app, RESULT);
renderDownloads(app, RESULT);
renderTable(app, RESULT);
renderDetail(app, RESULT);
renderRaw(app, RESULT);
</script>
</body>
</html>
"""
    # Inject payload safely (payload already escaped for </ sequences)
    html_template = html_template.replace("__RESULT_PAYLOAD__", payload)
    components.html(html_template, height=height, scrolling=True)