from pathlib import Path
import html, json, shutil

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "incidents"
DIST = ROOT / "site" / "dist"
DIST.mkdir(parents=True, exist_ok=True)

records = []
for f in sorted(ART.glob("*/incident.json"), reverse=True):
    try: records.append(json.loads(f.read_text()))
    except Exception: pass

passed = sum(bool(r.get("evaluation", {}).get("pass")) for r in records)
accuracy = round((passed / len(records) * 100), 1) if records else 0
cards = []
for r in records:
    iid = r["id"]
    s = r["scenario"]
    d = r.get("diagnosis", {})
    ev = r.get("evaluation", {})
    status = "PASS" if ev.get("pass") else "FAIL"
    cards.append(f'''<a class="card" href="incidents/{iid}.html"><div class="badge {status.lower()}">{status}</div><h3>{html.escape(s['title'])}</h3><p>{html.escape(iid)}</p><p><b>AI RCA:</b> {html.escape(str(d.get('root_cause','unknown')))}</p></a>''')

css = '''body{font-family:Inter,ui-sans-serif,system-ui;background:#0b1020;color:#e8ecf3;margin:0}.wrap{max-width:1100px;margin:auto;padding:48px 24px}h1{font-size:48px;margin-bottom:8px}.sub{color:#9ca9bf}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:32px 0}.stat,.card{background:#131b2e;border:1px solid #26324a;border-radius:16px;padding:20px}.n{font-size:34px;font-weight:800}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}.card{display:block;color:inherit;text-decoration:none}.badge{display:inline-block;padding:5px 9px;border-radius:999px;font-size:12px;font-weight:800;background:#26324a}.pass{background:#153c2b}.fail{background:#4b2026}pre{white-space:pre-wrap;background:#0a0f1b;padding:16px;border-radius:12px;overflow:auto}img{max-width:100%;border-radius:12px} @media(max-width:700px){.stats{grid-template-columns:1fr}h1{font-size:36px}}'''

index = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>OpsSherlock</title><style>{css}</style></head><body><main class="wrap"><h1>🔎 OpsSherlock</h1><p class="sub">Local AI SRE laboratory · reproducible incidents · evidence-backed RCA · public postmortems</p><section class="stats"><div class="stat"><div class="n">{len(records)}</div><div>Incidents</div></div><div class="stat"><div class="n">{accuracy}%</div><div>RCA pass rate</div></div><div class="stat"><div class="n">{len(records)-passed}</div><div>AI failures exposed</div></div></section><h2>Incident archive</h2><section class="grid">{''.join(cards) or '<p>No incidents published yet. Run <code>make incident</code>.</p>'}</section></main></body></html>'''
(DIST / "index.html").write_text(index)
(DIST / "incidents").mkdir(exist_ok=True)

for r in records:
    iid = r["id"]
    post = ART / iid / "postmortem.md"
    body = html.escape(post.read_text() if post.exists() else json.dumps(r, indent=2))
    page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{iid}</title><style>{css}</style></head><body><main class="wrap"><p><a href="../index.html" style="color:#b9c8ff">← Incident archive</a></p><h1>{iid}</h1><pre>{body}</pre></main></body></html>'''
    (DIST / "incidents" / f"{iid}.html").write_text(page)
print(f"built {len(records)} incident pages -> {DIST}")
