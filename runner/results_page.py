"""Write a standalone HTML page from a conformance results.json file."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_results_page(results_path: Path, output_path: Path | None = None) -> Path:
    document = json.loads(results_path.read_text(encoding="utf-8"))
    repo_root = results_path.resolve().parents[2]
    destination = output_path or (repo_root / "dashboard" / "index.html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_page(document), encoding="utf-8")
    return destination


def render_page(document: dict[str, Any]) -> str:
    summary = document.get("summary") or {}
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    skipped = int(summary.get("skipped") or 0)
    total = int(summary.get("total") or (passed + failed + skipped))
    attempted = passed + failed
    rate = (passed / attempted * 100) if attempted else 0
    met = bool(document.get("benchmarkMet"))
    mode = str(document.get("mode") or "conformance")
    finished = str(document.get("finishedAt") or "")
    rows = []
    for plan in document.get("plans") or []:
        component = str(plan.get("component") or mode)
        for module in plan.get("modules") or []:
            rows.append(_row(component, module))
    benchmark = "Benchmark met" if met else "Benchmark not met"
    reasons = document.get("benchmarkReasons") or []
    reason_html = ""
    if reasons:
        items = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in reasons)
        reason_html = f"<ul class='reasons'>{items}</ul>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Conformance results — {html.escape(mode)}</title>
  <style>
    :root {{
      --ink: #1c1917;
      --muted: #57534e;
      --line: #e7e5e4;
      --paper: #fafaf9;
      --card: #ffffff;
      --pass: #166534;
      --pass-bg: #f0fdf4;
      --fail: #991b1b;
      --fail-bg: #fef2f2;
      --skip: #57534e;
      --skip-bg: #f5f5f4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 16px/1.5 "Segoe UI", sans-serif;
    }}
    main {{ max-width: 920px; margin: 0 auto; padding: 40px 20px 64px; }}
    header p {{ margin: 0; color: var(--muted); font-size: 14px; letter-spacing: 0.04em; text-transform: uppercase; }}
    h1 {{ font-size: 28px; font-weight: 650; margin: 8px 0 28px; }}
    .hero {{
      display: grid;
      grid-template-columns: 1.4fr 1fr 1fr 1fr;
      gap: 12px;
      margin-bottom: 28px;
    }}
    .stat {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 18px 18px 14px;
    }}
    .stat strong {{ display: block; font-size: 40px; line-height: 1; font-variant-numeric: tabular-nums; }}
    .stat span {{ color: var(--muted); font-size: 14px; }}
    .stat.pass strong {{ color: var(--pass); }}
    .stat.fail strong {{ color: var(--fail); }}
    .lead {{ grid-column: 1; }}
    .badge {{
      display: inline-block;
      margin-top: 10px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 13px;
      background: {('#f0fdf4' if met else '#fef2f2')};
      color: {('var(--pass)' if met else 'var(--fail)')};
    }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    .pill {{
      display: inline-block;
      min-width: 64px;
      text-align: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 650;
    }}
    .PASS {{ background: var(--pass-bg); color: var(--pass); }}
    .FAIL {{ background: var(--fail-bg); color: var(--fail); }}
    .SKIP {{ background: var(--skip-bg); color: var(--skip); }}
    .name {{ font-weight: 600; }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    .reasons {{ margin: 0 0 20px; color: var(--fail); }}
    footer {{ margin-top: 18px; color: var(--muted); font-size: 13px; }}
    @media (max-width: 720px) {{
      .hero {{ grid-template-columns: 1fr 1fr; }}
      .lead {{ grid-column: 1 / -1; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <p>OpenID conformance</p>
      <h1>{html.escape(mode)} test cases</h1>
    </header>
    <section class="hero">
      <article class="stat lead">
        <strong>{passed}</strong>
        <span>passed · {failed} failed · {skipped} skipped · {total} total</span>
        <div class="badge">{html.escape(benchmark)} · {rate:.0f}% of modules that ran</div>
      </article>
      <article class="stat pass"><strong>{passed}</strong><span>passed</span></article>
      <article class="stat fail"><strong>{failed}</strong><span>failed</span></article>
      <article class="stat"><strong>{skipped}</strong><span>skipped</span></article>
    </section>
    {reason_html}
    <table>
      <thead>
        <tr><th>Test case</th><th>Result</th><th>Suite result</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    <footer>Finished {html.escape(finished)}. Source: results/{html.escape(mode)}/results.json</footer>
  </main>
</body>
</html>
"""


def _row(component: str, module: dict[str, Any]) -> str:
    name = str(module.get("testModule") or "")
    mapped = str(module.get("mapped") or "FAIL")
    if mapped not in {"PASS", "FAIL", "SKIP"}:
        mapped = "FAIL"
    result = str(module.get("result") or "")
    reason = module.get("reason")
    detail = html.escape(result)
    if reason:
        detail += f"<div class='sub'>{html.escape(str(reason))}</div>"
    return (
        "<tr>"
        f"<td><div class='name'>{html.escape(_label(name))}</div>"
        f"<div class='sub'>{html.escape(component)} · {html.escape(name)}</div></td>"
        f"<td><span class='pill {mapped}'>{html.escape(mapped)}</span></td>"
        f"<td>{detail}</td>"
        "</tr>"
    )


def _label(name: str) -> str:
    for prefix in ("oid4vci-1_0-issuer-", "oid4vp-1final-verifier-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("-", " ")
