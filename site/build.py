from pathlib import Path
from collections import defaultdict
import html
import json
import re
import shutil
import statistics

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "incidents"
DIST = ROOT / "site" / "dist"

if DIST.exists():
    shutil.rmtree(DIST)
(DIST / "incidents").mkdir(parents=True, exist_ok=True)
(DIST / "assets").mkdir(parents=True, exist_ok=True)

records = []
for f in sorted(ART.glob("*/incident.json"), key=lambda p: p.stat().st_mtime, reverse=True):
    try:
        records.append(json.loads(f.read_text()))
    except Exception as exc:
        print(f"warning: skipping unreadable incident {f}: {exc}")


def esc(value):
    return html.escape(str(value if value is not None else ""))


def pct(n, d):
    return round(n / d * 100, 1) if d else 0.0


def fmt_duration(ns):
    if not ns:
        return "n/a"
    return f"{float(ns) / 1_000_000_000:.2f}s"


def parse_confidence(value):
    """Return a normalized 0..1 float, or None when the model did not return one."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            raw = value.strip()
            if raw.endswith("%"):
                return max(0.0, min(1.0, float(raw[:-1]) / 100.0))
            value = float(raw)
        value = float(value)
        if value > 1.0 and value <= 100.0:
            value /= 100.0
        return max(0.0, min(1.0, value))
    except (TypeError, ValueError):
        return None


def diagnosis_for(record):
    """Normalize historical/current incident schemas into one portal contract."""
    candidates = [
        record.get("diagnosis"),
        record.get("ai_diagnosis"),
        record.get("investigation", {}).get("diagnosis") if isinstance(record.get("investigation"), dict) else None,
        record.get("analysis", {}).get("diagnosis") if isinstance(record.get("analysis"), dict) else None,
        record.get("result", {}).get("diagnosis") if isinstance(record.get("result"), dict) else None,
    ]
    raw = next((x for x in candidates if isinstance(x, dict) and x), {})

    affected_service = (
        raw.get("affected_service")
        or raw.get("service")
        or raw.get("affected_component")
        or raw.get("component")
    )
    root_cause = raw.get("root_cause") or raw.get("cause") or raw.get("summary")
    remediation = raw.get("remediation") or raw.get("recommended_remediation")
    action = raw.get("remediation_action") or raw.get("action") or "none"
    evidence = raw.get("evidence") or raw.get("evidence_cited") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    elif not isinstance(evidence, list):
        evidence = []

    return {
        "affected_service": affected_service,
        "root_cause": root_cause,
        "confidence": parse_confidence(raw.get("confidence")),
        "evidence": evidence,
        "remediation": remediation,
        "remediation_action": action,
        "safety_note": raw.get("safety_note"),
        "error": raw.get("error"),
        "raw": raw,
    }


def confidence_text(value):
    return "not returned" if value is None else f"{value * 100:.0f}%"


def inline_md(text):
    text = esc(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return text


def markdown_to_html(markdown):
    """Small, dependency-free renderer for OpsSherlock-generated postmortems."""
    lines = markdown.splitlines()
    out, para, list_items = [], [], []
    in_code = False
    code = []

    def flush_para():
        if para:
            out.append(f"<p>{inline_md(' '.join(x.strip() for x in para))}</p>")
            para.clear()

    def flush_list():
        if list_items:
            out.append("<ul>" + "".join(f"<li>{inline_md(x)}</li>" for x in list_items) + "</ul>")
            list_items.clear()

    for line in lines:
        if line.startswith("```"):
            flush_para(); flush_list()
            if in_code:
                out.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
                code.clear(); in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush_para(); flush_list(); continue
        if line.startswith("### "):
            flush_para(); flush_list(); out.append(f"<h4>{inline_md(line[4:])}</h4>"); continue
        if line.startswith("## "):
            flush_para(); flush_list(); out.append(f"<h3>{inline_md(line[3:])}</h3>"); continue
        if line.startswith("# "):
            flush_para(); flush_list(); out.append(f"<h2>{inline_md(line[2:])}</h2>"); continue
        if line.startswith("> "):
            flush_para(); flush_list(); out.append(f"<blockquote>{inline_md(line[2:])}</blockquote>"); continue
        if re.match(r"^[-*] ", line):
            flush_para(); list_items.append(line[2:].strip()); continue
        para.append(line.rstrip("  "))

    flush_para(); flush_list()
    if in_code:
        out.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
    return "\n".join(out)


passed = sum(bool(r.get("evaluation", {}).get("pass")) for r in records)
failed = len(records) - passed
automated = [r for r in records if r.get("automation")]
recovered = sum(
    bool(r.get("automation", {}).get("authorization", {}).get("approved"))
    and bool(r.get("automation", {}).get("recovery", {}).get("pass"))
    for r in automated
)
policy_denied = sum(not bool(r.get("automation", {}).get("authorization", {}).get("approved")) for r in automated)

scenario_stats = defaultdict(lambda: {"runs": 0, "passed": 0, "recovered": 0})
model_stats = defaultdict(lambda: {"runs": 0, "passed": 0, "confidence": [], "eval_tokens": [], "durations": []})
for r in records:
    scenario = r.get("scenario", {})
    key = scenario.get("title") or r.get("id", "unknown")
    scenario_stats[key]["runs"] += 1
    scenario_stats[key]["passed"] += bool(r.get("evaluation", {}).get("pass"))
    scenario_stats[key]["recovered"] += bool(r.get("automation", {}).get("authorization", {}).get("approved")) and bool(r.get("automation", {}).get("recovery", {}).get("pass"))
    run = r.get("run", {})
    model = run.get("model") or run.get("model_stats", {}).get("model") or "unknown"
    m = model_stats[model]
    m["runs"] += 1
    m["passed"] += bool(r.get("evaluation", {}).get("pass"))
    conf = diagnosis_for(r)["confidence"]
    if conf is not None:
        m["confidence"].append(conf)
    ms = run.get("model_stats", {})
    if ms.get("eval_count") is not None: m["eval_tokens"].append(ms["eval_count"])
    if ms.get("total_duration_ns") is not None: m["durations"].append(ms["total_duration_ns"])

benchmark = {
    "incidents": len(records),
    "rca_passes": passed,
    "rca_pass_rate": pct(passed, len(records)),
    "failed_diagnoses": failed,
    "automated_incidents": len(automated),
    "verified_recoveries": recovered,
    "policy_denials": policy_denied,
    "scenarios": {k: {**v, "rca_pass_rate": pct(v["passed"], v["runs"]), "recovery_rate": pct(v["recovered"], v["runs"])} for k, v in scenario_stats.items()},
    "models": {k: {"runs": v["runs"], "rca_passes": v["passed"], "rca_pass_rate": pct(v["passed"], v["runs"]), "average_confidence": round(statistics.mean(v["confidence"]), 3) if v["confidence"] else None, "average_eval_tokens": round(statistics.mean(v["eval_tokens"]), 1) if v["eval_tokens"] else None, "average_duration_seconds": round(statistics.mean(v["durations"]) / 1_000_000_000, 2) if v["durations"] else None} for k, v in model_stats.items()},
}
(DIST / "benchmark.json").write_text(json.dumps(benchmark, indent=2))

css = '''
:root{color-scheme:dark;--bg:#080d18;--panel:#111a2c;--panel2:#0d1525;--line:#26344f;--muted:#95a4bd;--text:#eef3fb;--good:#50d890;--bad:#ff7185;--warn:#ffc861;--accent:#91a9ff}*{box-sizing:border-box}body{font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;background:radial-gradient(circle at top,#17213b 0,#080d18 32rem);color:var(--text);margin:0}.wrap{max-width:1180px;margin:auto;padding:52px 24px 80px}a{color:var(--accent)}h1{font-size:48px;letter-spacing:-1.5px;margin:0 0 8px}.sub{color:var(--muted);font-size:18px;margin:0 0 30px}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:30px 0}.stat,.card,.panel{background:rgba(17,26,44,.93);border:1px solid var(--line);border-radius:17px;padding:20px;box-shadow:0 15px 50px rgba(0,0,0,.16)}.n{font-size:32px;font-weight:850}.label{color:var(--muted);margin-top:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}.card{display:block;color:inherit;text-decoration:none;transition:transform .15s,border-color .15s}.card:hover{transform:translateY(-2px);border-color:#4d6090}.badge{display:inline-block;padding:5px 9px;border-radius:999px;font-size:12px;font-weight:850;letter-spacing:.3px;background:#26324a}.pass{background:#153c2b;color:#80e6ad}.fail{background:#4b2026;color:#ff9ca8}.denied{background:#473819;color:#ffd877}.section{margin-top:42px}.section h2{font-size:25px}.muted{color:var(--muted)}table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line)}th{color:#b8c5da;background:var(--panel2);font-size:13px;text-transform:uppercase;letter-spacing:.4px}tr:last-child td{border-bottom:none}.compare{display:grid;grid-template-columns:1fr 1fr;gap:16px}.kv{display:grid;grid-template-columns:150px 1fr;gap:8px 12px}.kv div:nth-child(odd){color:var(--muted)}pre{white-space:pre-wrap;background:#070c16;border:1px solid var(--line);padding:16px;border-radius:12px;overflow:auto}.shots{display:grid;grid-template-columns:1fr;gap:20px}.shot img{display:block;width:100%;border-radius:13px;border:1px solid var(--line);background:#050914}.timeline{border-left:2px solid var(--line);margin-left:10px;padding-left:20px}.event{margin:0 0 17px}.event strong{margin-right:8px}.topline{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.small{font-size:13px}.postmortem{max-width:900px;margin:0 auto}.postmortem h2{font-size:30px;margin:0 0 24px}.postmortem h3{font-size:22px;margin:30px 0 10px;padding-top:6px;border-top:1px solid var(--line)}.postmortem h4{font-size:18px}.postmortem p,.postmortem li{line-height:1.7}.postmortem blockquote{margin:20px 0;padding:10px 18px;border-left:3px solid var(--accent);background:var(--panel2);color:#cbd6e8}.postmortem code{background:#070c16;padding:2px 6px;border-radius:5px}.rawlinks{margin-top:24px;padding-top:18px;border-top:1px solid var(--line)}.footer{margin-top:50px;color:var(--muted);font-size:13px}@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.compare{grid-template-columns:1fr}}@media(max-width:600px){.stats{grid-template-columns:1fr}h1{font-size:37px}.kv{grid-template-columns:1fr}}
'''

cards, fail_cards = [], []
for r in records:
    iid = r.get("id", "unknown"); s = r.get("scenario", {}); d = diagnosis_for(r); ev = r.get("evaluation", {}); ok = bool(ev.get("pass")); auto = r.get("automation", {}); auth = auto.get("authorization", {}); recovery = auto.get("recovery", {})
    auto_text = "manual / investigation only"
    if auto:
        if auth.get("approved") and recovery.get("pass"): auto_text = "automated recovery verified"
        elif not auth.get("approved"): auto_text = "unsafe/unsupported action blocked"
        else: auto_text = "remediation did not verify"
    diagnosis_summary = d["root_cause"] or (f"Model error: {d['error']}" if d["error"] else "No structured root cause returned")
    card = f'''<a class="card" href="incidents/{esc(iid)}/"><div class="topline"><span class="badge {'pass' if ok else 'fail'}">{'RCA PASS' if ok else 'RCA FAIL'}</span>{'<span class="badge denied">POLICY BLOCK</span>' if auto and not auth.get('approved') else ''}</div><h3>{esc(s.get('title','Unknown incident'))}</h3><p class="muted small">{esc(iid)}</p><p><b>AI:</b> {esc(diagnosis_summary)}</p><p class="muted"><b>Confidence:</b> {esc(confidence_text(d['confidence']))} · {esc(auto_text)}</p></a>'''
    cards.append(card)
    if not ok: fail_cards.append(card)

scenario_rows = ''.join(f"<tr><td>{esc(name)}</td><td>{v['runs']}</td><td>{pct(v['passed'],v['runs'])}%</td><td>{pct(v['recovered'],v['runs'])}%</td></tr>" for name, v in sorted(scenario_stats.items())) or '<tr><td colspan="4">No benchmark data yet.</td></tr>'
model_rows = ''.join(f"<tr><td><code>{esc(name)}</code></td><td>{v['runs']}</td><td>{pct(v['passed'],v['runs'])}%</td><td>{round(statistics.mean(v['confidence']),3) if v['confidence'] else 'n/a'}</td><td>{round(statistics.mean(v['eval_tokens']),1) if v['eval_tokens'] else 'n/a'}</td><td>{round(statistics.mean(v['durations'])/1_000_000_000,2) if v['durations'] else 'n/a'}</td></tr>" for name, v in sorted(model_stats.items())) or '<tr><td colspan="6">No model data yet.</td></tr>'

index = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>OpsSherlock · AI SRE Benchmark</title><style>{css}</style></head><body><main class="wrap"><h1>🔎 OpsSherlock</h1><p class="sub">AI SRE lab · deterministic failures · telemetry-first diagnosis · policy-controlled remediation · evidence-backed postmortems</p><section class="stats"><div class="stat"><div class="n">{len(records)}</div><div class="label">Incidents</div></div><div class="stat"><div class="n">{pct(passed,len(records))}%</div><div class="label">RCA pass rate</div></div><div class="stat"><div class="n">{failed}</div><div class="label">Failed diagnoses exposed</div></div><div class="stat"><div class="n">{recovered}/{len(automated)}</div><div class="label">Verified automated recoveries</div></div><div class="stat"><div class="n">{policy_denied}</div><div class="label">Policy blocks</div></div></section><section class="section"><h2>Incident archive</h2><div class="grid">{''.join(cards) or '<p>No incidents published yet.</p>'}</div></section><section class="section"><h2>Scenario benchmark</h2><table><thead><tr><th>Scenario</th><th>Runs</th><th>RCA pass</th><th>Verified recovery</th></tr></thead><tbody>{scenario_rows}</tbody></table></section><section class="section"><h2>Model runs</h2><table><thead><tr><th>Model</th><th>Runs</th><th>RCA pass</th><th>Avg confidence</th><th>Avg output tokens</th><th>Avg runtime</th></tr></thead><tbody>{model_rows}</tbody></table></section><section class="section"><h2>Failed-diagnosis gallery</h2><p class="muted">Failures are intentionally public: a benchmark is only useful if wrong diagnoses and blocked remediations remain visible.</p><div class="grid">{''.join(fail_cards) or '<p>No failed diagnoses recorded yet.</p>'}</div></section><p class="footer">Generated from immutable incident artifacts. Machine-readable aggregate: <a href="benchmark.json">benchmark.json</a>.</p></main></body></html>'''
(DIST / "index.html").write_text(index)

for r in records:
    iid = r.get("id", "unknown"); idir = ART / iid; out = DIST / "incidents" / iid; out.mkdir(parents=True, exist_ok=True)
    evidence_src = idir / "evidence"
    if evidence_src.exists(): shutil.copytree(evidence_src, out / "evidence", dirs_exist_ok=True)
    (out / "incident.json").write_text(json.dumps(r, indent=2))
    for name in ("timeline.json", "timeline.md", "postmortem.md"):
        src = idir / name
        if src.exists(): shutil.copy2(src, out / name)

    s = r.get("scenario", {}); d = diagnosis_for(r); ev = r.get("evaluation", {}); run = r.get("run", {}); ms = run.get("model_stats", {}); auto = r.get("automation", {}); auth = auto.get("authorization", {}); recovery = auto.get("recovery", {}); timeline = r.get("timeline", [])
    evidence_images = []
    for manifest in sorted((idir / "evidence").glob("*-manifest.json")) if (idir / "evidence").exists() else []:
        try:
            doc = json.loads(manifest.read_text())
            for shot in doc.get("screenshots", []):
                if shot.get("status") == "captured" and (idir / shot["file"]).exists(): evidence_images.append((doc.get("phase", "evidence"), shot))
        except Exception: pass
    shots_html = ''.join(f'''<div class="shot"><h3>{esc(phase.title())} · {esc(shot.get('label'))}</h3><a href="{esc(shot.get('file'))}"><img loading="lazy" src="{esc(shot.get('file'))}" alt="Grafana {esc(shot.get('label'))} screenshot"></a></div>''' for phase, shot in evidence_images) or '<p class="muted">No Grafana screenshots were captured for this run.</p>'
    timeline_html = ''.join(f'''<div class="event"><div><strong>{esc(row.get('phase'))}</strong><span class="badge">{esc(row.get('status'))}</span></div><div>{esc(row.get('detail'))}</div><div class="muted small">{esc(row.get('timestamp'))}</div></div>''' for row in timeline) or '<p class="muted">No automated timeline recorded.</p>'
    evidence_items = ''.join(f"<li>{esc(x)}</li>" for x in d["evidence"]) or '<li>No model-cited evidence was returned.</li>'
    model_error = f'''<p class="badge fail">Model output error: {esc(d['error'])}</p>''' if d["error"] else ""
    post_path = idir / "postmortem.md"
    postmortem_html = markdown_to_html(post_path.read_text()) if post_path.exists() else '<p class="muted">No postmortem was generated for this incident.</p>'
    status = "PASS" if ev.get("pass") else "FAIL"
    affected = d["affected_service"] or "not returned"
    root_cause = d["root_cause"] or "No structured root cause returned by the model."
    page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{esc(iid)} · OpsSherlock</title><style>{css}</style></head><body><main class="wrap"><p><a href="../../index.html">← Incident archive</a></p><div class="topline"><span class="badge {'pass' if ev.get('pass') else 'fail'}">RCA {status}</span>{'<span class="badge denied">POLICY BLOCK</span>' if auto and not auth.get('approved') else ''}</div><h1>{esc(s.get('title',iid))}</h1><p class="sub">{esc(iid)} · severity {esc(s.get('severity','n/a'))}</p><section class="compare"><div class="panel"><h2>AI diagnosis</h2>{model_error}<div class="kv"><div>Affected service</div><div><b>{esc(affected)}</b></div><div>Root cause</div><div>{esc(root_cause)}</div><div>Confidence</div><div>{esc(confidence_text(d['confidence']))}</div><div>Action</div><div><code>{esc(d['remediation_action'])}</code></div></div><h3>Evidence cited</h3><ul>{evidence_items}</ul></div><div class="panel"><h2>Ground truth & evaluation</h2><div class="kv"><div>Affected service</div><div><b>{esc(s.get('expected',{}).get('affected_service','unknown'))}</b></div><div>Root cause</div><div>{esc(s.get('expected',{}).get('root_cause','unknown'))}</div><div>Service match</div><div>{esc(ev.get('service_match'))}</div><div>RCA match</div><div>{esc(ev.get('root_cause_match'))}</div></div><h3>Policy response</h3><div class="kv"><div>Decision</div><div>{'APPROVED' if auth.get('approved') else ('DENIED' if auto else 'n/a')}</div><div>Reason</div><div>{esc(auth.get('reason','n/a'))}</div><div>Recovery</div><div>{'VERIFIED' if auth.get('approved') and recovery.get('pass') else ('NOT VERIFIED' if auto else 'n/a')}</div></div></div></section><section class="section panel"><h2>Model run metadata</h2><div class="kv"><div>Model</div><div><code>{esc(run.get('model','unknown'))}</code></div><div>Agent</div><div><code>{esc(run.get('agent_version','unknown'))}</code></div><div>Output tokens</div><div>{esc(ms.get('eval_count','n/a'))}</div><div>Prompt tokens</div><div>{esc(ms.get('prompt_eval_count','n/a'))}</div><div>Total model time</div><div>{fmt_duration(ms.get('total_duration_ns'))}</div><div>Telemetry</div><div>{esc(', '.join(run.get('telemetry_sources',[])))}</div></div></section><section class="section"><h2>Grafana evidence</h2><div class="shots">{shots_html}</div></section><section class="section panel"><h2>Incident timeline</h2><div class="timeline">{timeline_html}</div></section><section class="section panel postmortem"><h2>Postmortem</h2>{postmortem_html}<div class="rawlinks"><strong>Raw artifacts:</strong> <a href="incident.json">incident.json</a> · <a href="timeline.json">timeline.json</a> · <a href="postmortem.md">postmortem.md</a></div></section></main></body></html>'''
    (out / "index.html").write_text(page)

print(f"built {len(records)} incident pages -> {DIST}")
