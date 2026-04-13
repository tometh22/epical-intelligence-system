"""HTML report builder v2 — parametrized from the Avianca v10 template.

Generates a self-contained HTML report following the exact editorial design
of the v10 reference report (light theme, Playfair + DM Sans + JetBrains Mono).

Design rules enforced (from spec):
  13. Professional-modern. Navy cover/transitions, light content.
  14. Typography: Playfair Display (titles) + DM Sans (body) + JetBrains Mono (data).
      Google Fonts via <link> tag, not @import.
  15. Chart.js charts ALWAYS inside div with position:relative and explicit height.
  16. KPI big numbers use DM Sans bold, not JetBrains Mono.
  17. Callout boxes: blue=insights, orange=so-what/readings, red=risks.
  18. Platform logos as SVG inline on platforms slide.
  19. Charts with Chart.js 4.4.1 via Cloudflare CDN.
"""

import html as _html
import json as _json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agents.shared.logger import get_logger

logger = get_logger("report-builder")

# ── Platform SVG icons (inline, spec rule 18) ────────────────────────

_PLATFORM_SVGS: Dict[str, str] = {
    "Twitter": '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>',
    "Facebook": '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>',
    "TikTok": '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>',
    "Instagram": '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/></svg>',
    "YouTube": '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 00-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 00.502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 002.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 002.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814z"/><path fill="#fff" d="M9.545 15.568V8.432L15.818 12z"/></svg>',
}

_PLATFORM_COLORS: Dict[str, str] = {
    "Twitter": "var(--cyan)",
    "Facebook": "#1877F2",
    "TikTok": "var(--magenta)",
    "Instagram": "#E4405F",
    "YouTube": "#FF0000",
}

# ── Number formatting (spec rule 7) ──────────────────────────────────

def _fmt(n: float) -> str:
    """Format large numbers: 692K, 29M, 233M. Spec rule 7."""
    if n is None:
        return "—"
    abs_n = abs(n)
    if abs_n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if abs_n >= 10_000_000:
        return f"{n / 1_000_000:.0f}M"
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs_n >= 10_000:
        return f"{n / 1_000:.0f}K"
    if abs_n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n):,}".replace(",", ".")


def _pct(value: float) -> str:
    """Format percentage to 1 decimal. Spec rule 7."""
    if value is None:
        return "—"
    return f"{value:.1f}%"


def _esc(text: str) -> str:
    """HTML-escape shorthand."""
    return _html.escape(str(text)) if text else ""


# ══════════════════════════════════════════════════════════════════════
# CSS — exact v10 design system
# ══════════════════════════════════════════════════════════════════════

def _build_css() -> str:
    """Return full <style> block matching the v10 template."""
    return """\
<style>
:root{--bg:#F5F5FA;--surface:#FFFFFF;--border:#DDDDE8;--text:#3B3B58;--muted:#71718F;--dim:#A0A0B8;--dark:#0F1635;--magenta:#D6336C;--cyan:#1098AD;--amber:#C27803;--green:#2B8A3E;--red:#DC2626;--shadow:0 1px 8px rgba(0,0,0,0.05);--display:'Playfair Display',Georgia,serif;--body:'DM Sans','Helvetica Neue',sans-serif;--mono:'JetBrains Mono',monospace}
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;scroll-snap-type:y mandatory}
body{background:var(--bg);color:var(--text);font-family:var(--body);line-height:1.78;overflow-x:hidden;-webkit-font-smoothing:antialiased}
@media print{.sl{min-height:auto!important;page-break-after:always;padding:40px!important}.cover{color:#0F1635!important;background:#fff!important}}
.sl{min-height:100vh;scroll-snap-align:start;display:flex;align-items:center;justify-content:center;padding:64px 48px;position:relative}
.si{max-width:1000px;width:100%}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:3px;text-transform:uppercase;color:var(--magenta);margin-bottom:14px}
.h1{font-family:var(--display);font-size:clamp(28px,4.5vw,46px);font-weight:700;color:var(--dark);line-height:1.15;margin-bottom:12px}
.h2{font-family:var(--display);font-size:clamp(20px,3vw,30px);font-weight:700;color:var(--dark);line-height:1.2;margin-bottom:10px}
.h3{font-size:15px;font-weight:700;color:var(--dark);margin-bottom:8px}
.sub{font-size:15px;color:var(--muted);font-style:italic;margin-bottom:30px;line-height:1.7;max-width:700px}
.p{font-size:15px;color:var(--text);line-height:1.85;margin-bottom:14px}
.p strong{color:var(--dark);font-weight:600}
.sm{font-size:13px;color:var(--muted);line-height:1.7}
.cover{flex-direction:column;background:linear-gradient(145deg,#0F1635,#1A2456);color:#fff}
.cover .tag{color:rgba(255,255,255,0.5)}.cover .h1{color:#fff;font-size:clamp(34px,5.5vw,56px);margin-bottom:20px}.cover .h1 em{color:#FF4081;font-style:normal}
.cover-sub{font-size:16px;color:rgba(255,255,255,0.6);max-width:620px;margin-bottom:48px;line-height:1.9;font-weight:300}
.cover-meta{font-family:var(--mono);font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:2px;border-top:1px solid rgba(255,255,255,0.08);padding-top:20px;margin-top:32px}
.tr{text-align:center;background:linear-gradient(145deg,#0F1635,#1A2456);color:#fff}
.tr .h1{color:#fff;max-width:660px;margin:0 auto 14px}.tr .sub{color:rgba(255,255,255,0.45);margin:0 auto}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:32px;align-items:start}.g2w{grid-template-columns:3fr 2fr}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;box-shadow:var(--shadow)}
.card-a{border-left:3px solid var(--magenta)}.card-a .h3{color:var(--magenta)}
.card-b{border-left:3px solid var(--cyan)}.card-b .h3{color:var(--cyan)}
.card-c{border-left:3px solid var(--green)}.card-c .h3{color:var(--green)}
.card-m{background:var(--bg);border-color:#D0D0E0}
.kpi-row{display:flex;gap:14px;margin:22px 0;flex-wrap:wrap}
.kpi{flex:1;min-width:125px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px;text-align:center;box-shadow:var(--shadow)}
.kpi-v{font-size:30px;font-weight:700;color:var(--dark)}.kpi-l{font-size:10px;text-transform:uppercase;letter-spacing:2px;color:var(--dim);margin-top:4px}
.chart-box{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;box-shadow:var(--shadow)}
.chart-label{font-family:var(--mono);font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--dim);margin-bottom:14px}
.insight{background:#E8F6FC;border:1px solid #B3DEF0;border-radius:10px;padding:18px 22px;margin-top:20px}
.insight p{font-size:14px;color:#0A5975;line-height:1.75;margin:0}
.sowhat{background:#FFF6EB;border:1px solid #FFD9A3;border-radius:10px;padding:18px 22px;margin-top:20px}
.sowhat-label{font-family:var(--mono);font-size:9px;letter-spacing:3px;text-transform:uppercase;color:var(--amber);margin-bottom:6px}
.sowhat p{font-size:14px;color:#6B3A00;line-height:1.75;margin:0}
.risk-box{background:#FFF0F0;border:1px solid #FFC5C5;border-radius:10px;padding:18px 22px;margin-top:20px}
.risk-box p{font-size:14px;color:#991B1B;line-height:1.75;margin:0}
.bar{display:flex;height:30px;border-radius:6px;overflow:hidden;margin:10px 0}
.bar div{display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:9px;color:#fff;letter-spacing:0.5px}
.spost{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin:10px 0;box-shadow:var(--shadow)}
.spost-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.spost-avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700}
.spost-user{font-size:13px;font-weight:600;color:var(--dark)}.spost-handle{font-size:11px;color:var(--dim)}
.spost-text{font-size:14px;line-height:1.7;color:var(--text);margin-bottom:10px}
.spost-meta{display:flex;gap:16px;font-size:11px;color:var(--dim)}
.spost-meta span{display:flex;align-items:center;gap:4px}
.nar{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:28px;margin-bottom:20px;box-shadow:var(--shadow)}
.nar-num{font-family:var(--display);font-size:56px;color:var(--bg);float:right;margin-top:-8px}
.nar-title{font-family:var(--display);font-size:22px;font-weight:700;color:var(--dark);margin-bottom:6px;line-height:1.25;max-width:82%}
.badge{font-family:var(--mono);font-size:9px;letter-spacing:2px;text-transform:uppercase;padding:4px 12px;border-radius:20px;display:inline-block;margin-bottom:14px}
.badge-g{background:#E6F9EF;color:var(--green)}.badge-o{background:#FFF6EB;color:var(--amber)}.badge-b{background:#E8F6FC;color:var(--cyan)}
.plat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;box-shadow:var(--shadow);border-top:3px solid var(--dim)}
.plat-icon{margin-bottom:8px;color:var(--dim)}
.plat-name{font-family:var(--display);font-size:20px;color:var(--dark)}.plat-n{font-family:var(--mono);font-size:15px;color:var(--cyan);margin:2px 0}
.sc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:20px}
.sc{border-radius:12px;padding:22px;border:1px solid var(--border);box-shadow:var(--shadow)}
.sc-letter{font-family:var(--display);font-size:28px}.sc-name{font-size:16px;font-weight:700;color:var(--dark);margin:4px 0}
.rec{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:14px;box-shadow:var(--shadow)}
.rec h3{font-family:var(--display);font-size:18px;font-weight:700;color:var(--dark);margin-bottom:8px;line-height:1.3}
.rec-signal{font-family:var(--mono);font-size:10px;color:var(--cyan);text-transform:uppercase;letter-spacing:1px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.spike{display:flex;gap:14px;margin:10px 0;align-items:flex-start}
.spike-dot{min-width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--display);font-size:14px;font-weight:700;color:#fff}
table{width:100%;border-collapse:collapse;margin:14px 0}
th{font-family:var(--mono);font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim);text-align:left;padding:8px 12px;border-bottom:2px solid var(--border)}
td{font-size:13px;padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top}
td:first-child{font-weight:600;color:var(--dark)}
.fu{opacity:0;transform:translateY(18px);transition:opacity 0.5s ease,transform 0.5s ease}.fu.vis{opacity:1;transform:translateY(0)}
.s2{transition-delay:.1s}.s3{transition-delay:.2s}.s4{transition-delay:.3s}
@media(max-width:768px){.sl{padding:40px 20px}.g2,.g3,.g4,.sc-grid{grid-template-columns:1fr}.kpi-row{flex-direction:column}}
</style>"""


# ══════════════════════════════════════════════════════════════════════
# Individual slide builders
# ══════════════════════════════════════════════════════════════════════

def _slide_cover(
    client_name: str,
    period: str,
    title: str,
    subtitle: str,
    total_raw: int,
    total_relevant: int,
    platforms_count: int,
    client_logo_url: str = "",
) -> str:
    """Slide 1: Cover (navy, logos, provocative title)."""
    logo_img = ""
    if client_logo_url:
        logo_img = f'<img src="{_esc(client_logo_url)}" alt="{_esc(client_name)}" style="height:24px;opacity:0.7" onerror="this.style.display=\'none\'">'

    return f"""\
<!-- ========== COVER ========== -->
<section class="sl cover">
<div class="si">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:48px">
<img src="https://epical.digital/wp-content/uploads/2023/08/cropped-logoEpicalwhite-152x30-1.png" alt="Epical" style="height:16px;opacity:0.6" onerror="this.style.display='none'">
<div style="font-family:var(--mono);font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:2px">CONFIDENCIAL</div>
</div>
<div class="tag">Análisis de inteligencia reputacional · preparado para {_esc(client_name)}</div>
<h1 class="h1">{title}</h1>
<p class="cover-sub">{_esc(subtitle)}</p>
<div class="cover-meta">PERÍODO: {_esc(period.upper())} &nbsp;·&nbsp; {_fmt(total_raw)} MENCIONES PROCESADAS &nbsp;·&nbsp; {_fmt(total_relevant)} RELEVANTES &nbsp;·&nbsp; {platforms_count} PLATAFORMAS</div>
{f'<div style="margin-top:28px">{logo_img}</div>' if logo_img else ''}
</div>
</section>"""


def _slide_exec_summary(
    findings: List[Dict[str, str]],
    implication_title: str = "",
    implication_body: str = "",
    client_role: str = "",
) -> str:
    """Slide 2: Executive summary with 3 finding cards."""
    card_classes = ["card-a", "card-b", "card-c"]
    cards_html = ""
    for i, f in enumerate(findings[:3]):
        cls = card_classes[i] if i < len(card_classes) else ""
        cards_html += (
            f'<div class="card {cls}"><div class="h3">HALLAZGO {i + 1}</div>'
            f'<p class="p" style="font-size:14px;margin:0">{_esc(f.get("text", ""))}</p></div>\n'
        )

    sowhat_html = ""
    if implication_body:
        label = f"Implicancia para {_esc(client_role)}" if client_role else "Implicancia estratégica"
        sowhat_html = f"""\
<div class="sowhat fu s3" style="margin-top:24px"><div class="sowhat-label">{label}</div>
<p>{implication_body}</p></div>"""

    return f"""\
<!-- ========== EXEC SUMMARY ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Resumen ejecutivo</div>
<div class="h1 fu">Tres hallazgos que cambian la lectura</div>
<p class="sub fu s2">Lo que distingue este análisis de un reporte de monitoreo estándar.</p>
<div class="g3 fu s2">
{cards_html}</div>
{sowhat_html}
</div></section>"""


def _slide_methodology(
    pipeline_rows: List[Dict[str, str]],
    sidebar_title: str = "",
    sidebar_body: str = "",
) -> str:
    """Slide 4: Methodology (data funnel, transparency)."""
    rows_html = ""
    for row in pipeline_rows:
        rows_html += (
            f'<tr><td>{_esc(row.get("stage", ""))}</td>'
            f'<td>{_esc(row.get("description", ""))}</td>'
            f'<td style="text-align:right;font-family:var(--mono)">{_esc(row.get("result", ""))}</td></tr>\n'
        )

    sidebar_html = ""
    if sidebar_title:
        sidebar_html = f"""\
<div><div class="card card-m"><div class="h3">{_esc(sidebar_title)}</div>
<p class="p" style="font-size:13px;margin:0">{_esc(sidebar_body)}</p></div></div>"""

    return f"""\
<!-- ========== METHODOLOGY ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Nota metodológica</div>
<div class="h1 fu">Cómo se produjo este análisis</div>
<p class="sub fu s2">Transparencia sobre qué datos usamos, qué descartamos, y por qué.</p>
<div class="g2 g2w fu s3">
<div>
<table>
<thead><tr><th>Etapa</th><th>Descripción</th><th style="text-align:right">Resultado</th></tr></thead>
<tbody>
{rows_html}</tbody>
</table>
</div>
{sidebar_html}
</div>
</div></section>"""


def _slide_data_kpis(
    total_relevant: int,
    sentiment: Dict[str, Any],
    reach_data: Optional[Dict[str, Any]] = None,
    engagement_total: int = 0,
    insight_text: str = "",
) -> str:
    """Slide 5: The Data — KPIs + sentiment charts."""
    # Build KPI cards (rule 16: DM Sans bold for big numbers, not JetBrains Mono)
    kpis = [{"value": _fmt(total_relevant), "label": "Relevantes", "color": ""}]

    for key, val in sentiment.items():
        if not isinstance(val, dict):
            continue
        count = val.get("count", 0)
        pct = val.get("percentage", 0)
        klower = key.lower()
        if klower in ("negative", "negativo"):
            kpis.append({"value": _fmt(count), "label": f"Negativas ({_pct(pct)})", "color": "var(--red)"})
        elif klower in ("neutral", "neutro"):
            kpis.append({"value": _fmt(count), "label": f"Neutrales ({_pct(pct)})", "color": ""})
        elif klower in ("positive", "positivo"):
            kpis.append({"value": _fmt(count), "label": f"Positivas ({_pct(pct)})", "color": "var(--green)"})

    if reach_data:
        dedup = reach_data.get("total_reach_formatted", _fmt(reach_data.get("total_reach_deduplicated", 0)))
        kpis.append({"value": dedup, "label": "Alcance (dedup.)", "color": "var(--cyan)"})

    if engagement_total:
        kpis.append({"value": _fmt(engagement_total), "label": "Interacciones", "color": ""})

    kpi_html = ""
    for k in kpis:
        style = f' style="color:{k["color"]}"' if k["color"] else ""
        kpi_html += f'<div class="kpi"><div class="kpi-v"{style}>{k["value"]}</div><div class="kpi-l">{_esc(k["label"])}</div></div>\n'

    insight_html = ""
    if insight_text:
        insight_html = f'<div class="insight fu s4"><p>{insight_text}</p></div>'

    return f"""\
<!-- ========== THE DATA ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Los datos</div>
<div class="h1 fu">{_fmt(total_relevant)} menciones relevantes: la foto real</div>
<div class="kpi-row fu s2">
{kpi_html}</div>
<div class="g2 fu s3">
<div class="chart-box"><div class="chart-label">Distribución de sentimiento</div><div style="position:relative;height:280px"><canvas id="sentChart"></canvas></div></div>
<div class="chart-box"><div class="chart-label">Volumen diario</div><div style="position:relative;height:280px"><canvas id="volMiniChart"></canvas></div></div>
</div>
{insight_html}
</div></section>"""


def _slide_transition(title: str, subtitle: str = "") -> str:
    """Transition slide (navy background)."""
    sub = f'<p class="sub fu s2">{_esc(subtitle)}</p>' if subtitle else ""
    return f"""\
<section class="sl tr"><div class="h1 fu">{title}</div>{sub}</section>"""


def _slide_actor(
    actor_name: str,
    mention_count: int,
    mention_pct: float,
    title: str,
    body_paragraphs: List[str],
    sentiment_bar: Dict[str, float],
    reading: str = "",
    sample_posts: Optional[List[Dict[str, str]]] = None,
    criticism_table: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Slides 7-9: One slide per actor."""
    # Body paragraphs
    body_html = ""
    for p in body_paragraphs:
        body_html += f'<p class="p">{p}</p>\n'

    # Criticism breakdown table
    if criticism_table:
        body_html += '<table><thead><tr><th>Tipo de crítica</th><th style="text-align:right">%</th></tr></thead><tbody>\n'
        for row in criticism_table:
            body_html += f'<tr><td>{_esc(row["type"])}</td><td style="text-align:right">{_esc(row["pct"])}</td></tr>\n'
        body_html += '</tbody></table>\n'

    # So-what reading (rule 8: "Señal →")
    sowhat_html = ""
    if reading:
        sowhat_html = f'<div class="sowhat"><div class="sowhat-label">Lectura estratégica</div><p>{reading}</p></div>'

    # Sentiment bar
    bar_parts = ""
    for label, pct in sorted(sentiment_bar.items(), key=lambda x: x[1], reverse=True):
        if pct < 1:
            continue
        klower = label.lower()
        if klower in ("negative", "negativo"):
            color = "var(--red)"
            txt = f"{_pct(pct)} NEG"
        elif klower in ("positive", "positivo"):
            color = "var(--green)"
            txt = f"{_pct(pct)} POS"
        else:
            color = "var(--dim)"
            txt = f"{_pct(pct)}" if pct > 5 else ""
        bar_parts += f'<div style="width:{pct}%;background:{color}">{txt if pct > 8 else ""}</div>'

    bar_html = f'<div class="card" style="margin-bottom:10px"><div class="chart-label">Sentimiento sobre {_esc(actor_name)}</div><div class="bar">{bar_parts}</div></div>'

    # Sample posts
    posts_html = ""
    if sample_posts:
        for post in sample_posts[:3]:
            avatar_bg = "linear-gradient(135deg,#667eea,#764ba2)"
            platform = post.get("platform", "")
            if platform.lower() == "tiktok":
                avatar_bg = "linear-gradient(135deg,#f09433,#e6683c)"
            elif platform.lower() in ("twitter", "x"):
                avatar_bg = "linear-gradient(135deg,#1DA1F2,#0d8ecf)"
            elif platform.lower() == "facebook":
                avatar_bg = "#4267B2"

            eng_display = ""
            eng = post.get("engagement", "")
            if eng:
                eng_display = f'<span>❤️ {_esc(str(eng))}</span>'

            posts_html += f"""\
<div class="spost">
<div class="spost-head"><div class="spost-avatar" style="background:{avatar_bg}">💬</div><div><div class="spost-user">{_esc(post.get("author", ""))}</div><div class="spost-handle">{_esc(platform)} · {_esc(post.get("date", ""))}{f" · {_esc(str(eng))} interacciones" if eng else ""}</div></div></div>
<div class="spost-text">{_esc(post.get("text", "")[:300])}</div>
<div class="spost-meta">{eng_display}</div>
</div>"""

    return f"""\
<!-- ========== ACTOR: {_esc(actor_name.upper())} ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Sobre {_esc(actor_name)} — {_fmt(mention_count)} menciones ({_pct(mention_pct)})</div>
<div class="h1 fu">{title}</div>
<div class="g2 g2w fu s2">
<div>
{body_html}
{sowhat_html}
</div>
<div>
{bar_html}
{posts_html}
</div>
</div>
</div></section>"""


def _slide_catalyst(
    tangential_data: Dict[str, Any],
    sample_posts: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Slide 10: Catalyst effect (OPTIONAL — only if tangential analysis detects catalyst)."""
    total = tangential_data.get("total_tangential", 0)
    neg = tangential_data.get("negative_tangential", 0)
    strength = tangential_data.get("catalyst_strength", "none")

    if not tangential_data.get("catalyst_detected", False) or total == 0:
        return ""

    themes = tangential_data.get("top_themes", [])
    themes_text = ", ".join(t["theme"] for t in themes[:5]) if themes else "temas variados"

    posts_html = ""
    if sample_posts:
        for post in sample_posts[:2]:
            posts_html += f"""\
<div class="spost"><div class="spost-head"><div class="spost-avatar" style="background:#4267B2">✈️</div><div><div class="spost-user">{_esc(post.get("author", "Comentario"))}</div><div class="spost-handle">{_esc(post.get("platform", ""))} · {_esc(post.get("date", ""))}</div></div></div>
<div class="spost-text">{_esc(post.get("text", "")[:300])}</div>
<div class="spost-meta"><span>❤️ {_esc(str(post.get("engagement", "")))}</span></div></div>"""

    return f"""\
<!-- ========== CATALYST ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Hallazgo no obvio</div>
<div class="h1 fu">El efecto catalizador: el incidente le dio micrófono a la insatisfacción acumulada</div>
<p class="sub fu s2">{_fmt(total)} menciones tangenciales negativas revelan un problema que trasciende el caso.</p>
<div class="g2 fu s2">
<div>
<p class="p">Además de las menciones relevantes, detectamos <strong>{_fmt(neg)} menciones tangenciales negativas</strong> — quejas sin relación directa con el incidente pero que aparecieron durante el mismo período.</p>
<p class="p">El incidente funcionó como <strong>catalizador de insatisfacción latente</strong>: personas que tenían una queja guardada vieron la marca era tendencia y aprovecharon para hacerla visible.</p>
<p class="p">Composición: {_esc(themes_text)}.</p>
</div>
<div>
{posts_html}
</div>
</div>
<div class="risk-box fu s3"><p><strong>Patrón predecible:</strong> cada vez que la marca sea tendencia en redes, este banco de insatisfacción se reactiva. No es un problema comunicacional — es un indicador operativo que se puede llevar como evidencia cuantificada.</p></div>
</div></section>"""


def _slide_platforms(
    platform_data: List[Dict[str, Any]],
    insight_text: str = "",
) -> str:
    """Slide 11: Platforms with logos (SVG inline) and engagement share."""
    # Build grid (max 4 per row via g4)
    cols = min(len(platform_data), 4)
    grid_class = f"g{cols}" if cols <= 4 else "g4"

    cards_html = ""
    for plat in platform_data[:6]:
        name = plat.get("platform", "")
        mentions = plat.get("mentions", 0)
        eng_share = plat.get("engagement_share", 0)
        color = _PLATFORM_COLORS.get(name, "var(--dim)")
        svg = _PLATFORM_SVGS.get(name, "")

        desc = plat.get("description", "")
        desc_html = f'<p class="sm" style="margin-top:6px">{_esc(desc)}</p>' if desc else ""

        cards_html += f"""\
<div class="plat" style="border-top-color:{color}">
<div class="plat-icon" style="color:{color}">{svg}</div>
<div class="plat-name">{_esc(name)}</div>
<div class="plat-n">{_fmt(mentions)} ({_pct(eng_share)} engagement)</div>
{desc_html}
</div>
"""

    insight_html = ""
    if insight_text:
        insight_html = f'<div class="insight fu s3"><p>{insight_text}</p></div>'

    return f"""\
<!-- ========== PLATFORMS ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Lectura por plataforma</div>
<div class="h1 fu">Cada plataforma juega un partido diferente</div>
<div class="{grid_class} fu s2">
{cards_html}</div>
{insight_html}
</div></section>"""


def _slide_timeline(
    spikes: List[Dict[str, Any]],
    insight_text: str = "",
) -> str:
    """Slide 12: Timeline with spike annotations."""
    spike_labels = "ABCDEFGH"
    spike_colors = ["var(--dim)", "var(--red)", "var(--red)", "var(--magenta)",
                    "var(--cyan)", "var(--cyan)", "var(--dim)", "var(--dim)"]

    # Build spike annotation items (2 columns)
    left_spikes = ""
    right_spikes = ""
    for i, spike in enumerate(spikes[:8]):
        letter = spike_labels[i] if i < len(spike_labels) else str(i + 1)
        color = spike_colors[i] if i < len(spike_colors) else "var(--dim)"
        desc = spike.get("description", f"{spike.get('date', '')} — {_fmt(spike.get('mentions', 0))} menciones")
        detail = spike.get("detail", "")

        item = f"""\
<div class="spike"><div class="spike-dot" style="background:{color}">{letter}</div><div>
<p style="font-family:var(--mono);font-size:13px;margin:0;color:var(--dark)">{_esc(spike.get("date", ""))} — {_fmt(spike.get("mentions", 0))} menciones</p>
<p class="sm" style="margin:0">{_esc(detail or desc)}</p>
</div></div>"""

        if i % 2 == 0:
            left_spikes += item
        else:
            right_spikes += item

    sowhat_html = ""
    if insight_text:
        sowhat_html = f'<div class="sowhat fu s4"><div class="sowhat-label">Hallazgo sobre timing</div><p>{insight_text}</p></div>'

    return f"""\
<!-- ========== TIMELINE ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Evolución temporal</div>
<div class="h1 fu">La línea de tiempo de la conversación</div>
<div class="chart-box fu s2"><div style="position:relative;height:200px"><canvas id="volChart"></canvas></div></div>
<div class="g2 fu s3" style="margin-top:20px">
<div>{left_spikes}</div>
<div>{right_spikes}</div>
</div>
{sowhat_html}
</div></section>"""


def _slide_comunicado_impact(
    impact_data: Dict[str, Any],
) -> str:
    """Slide 13: Comunicado/event impact (OPTIONAL — only if event_date provided)."""
    if not impact_data or not impact_data.get("event_date"):
        return ""

    pre = impact_data.get("pre", {})
    post = impact_data.get("post", {})
    delta = impact_data.get("delta", {})
    peak = impact_data.get("peak_day", {})
    recovery = impact_data.get("recovery_days")

    recovery_text = f"Recuperación a niveles pre-evento en {recovery} días." if recovery else "Sin recuperación completa en el período analizado."

    return f"""\
<!-- ========== COMUNICADO IMPACT ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Impacto del comunicado</div>
<div class="h1 fu">Antes y después del {_esc(impact_data["event_date"])}</div>
<div class="g2 fu s2">
<div class="card"><div class="h3">Pre-evento</div>
<div class="kpi-row">
<div class="kpi"><div class="kpi-v">{_fmt(pre.get("mentions", 0))}</div><div class="kpi-l">Menciones</div></div>
<div class="kpi"><div class="kpi-v">{_fmt(pre.get("engagement", 0))}</div><div class="kpi-l">Engagement</div></div>
<div class="kpi"><div class="kpi-v">{pre.get("avg_daily_mentions", 0):.0f}/día</div><div class="kpi-l">Promedio</div></div>
</div></div>
<div class="card"><div class="h3">Post-evento</div>
<div class="kpi-row">
<div class="kpi"><div class="kpi-v" style="color:var(--red)">{_fmt(post.get("mentions", 0))}</div><div class="kpi-l">Menciones</div></div>
<div class="kpi"><div class="kpi-v" style="color:var(--red)">{_fmt(post.get("engagement", 0))}</div><div class="kpi-l">Engagement</div></div>
<div class="kpi"><div class="kpi-v" style="color:var(--red)">{post.get("avg_daily_mentions", 0):.0f}/día</div><div class="kpi-l">Promedio</div></div>
</div></div>
</div>
<div class="kpi-row fu s3">
<div class="kpi"><div class="kpi-v" style="color:var(--red)">+{_pct(delta.get("mentions_pct", 0))}</div><div class="kpi-l">Δ Menciones</div></div>
<div class="kpi"><div class="kpi-v" style="color:var(--red)">+{_pct(delta.get("engagement_pct", 0))}</div><div class="kpi-l">Δ Engagement</div></div>
<div class="kpi"><div class="kpi-v">{peak.get("date", "—")}</div><div class="kpi-l">Pico ({_fmt(peak.get("mentions", 0))})</div></div>
</div>
<div class="insight fu s4"><p>{_esc(recovery_text)}</p></div>
</div></section>"""


def _slide_narratives(
    narratives: List[Dict[str, str]],
) -> str:
    """Slides 15-17: Narrative cards."""
    if not narratives:
        return ""

    badge_classes = ["badge-g", "badge-o", "badge-b"]
    cards_html = ""
    for i, narr in enumerate(narratives[:3]):
        badge_cls = badge_classes[i] if i < len(badge_classes) else "badge-b"
        num = f"{i + 1:02d}"
        cards_html += f"""\
<div class="nar fu {'s2' if i == 0 else 's3' if i == 1 else 's4'}"><div class="nar-num">{num}</div>
<div class="nar-title">{_esc(narr.get("title", ""))}</div>
<div class="badge {badge_cls}">{_esc(narr.get("badge", ""))}</div>
<p class="p">{narr.get("body", "")}</p></div>
"""

    return f"""\
<!-- ========== NARRATIVES ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Las narrativas en juego</div>
{cards_html}
</div></section>"""


def _slide_scenarios(
    scenarios: List[Dict[str, str]],
) -> str:
    """Slide 18: Scenarios at 30 days."""
    if not scenarios:
        return ""

    scenario_styles = [
        {"bg": "#FFF8F8", "border": "var(--red)", "color": "var(--red)"},
        {"bg": "#FFF8F0", "border": "var(--amber)", "color": "var(--amber)"},
        {"bg": "#F0F8FF", "border": "var(--cyan)", "color": "var(--cyan)"},
    ]
    letters = ["A", "B", "C"]

    cards_html = ""
    for i, sc in enumerate(scenarios[:3]):
        style = scenario_styles[i] if i < len(scenario_styles) else scenario_styles[-1]
        letter = letters[i] if i < len(letters) else str(i + 1)
        cards_html += f"""\
<div class="sc" style="background:{style['bg']};border-top:3px solid {style['border']}">
<div class="sc-letter" style="color:{style['color']}">{letter}</div>
<div class="sc-name">{_esc(sc.get("name", ""))}</div>
<p class="p" style="font-size:13px;margin-top:6px">{_esc(sc.get("description", ""))}</p>
<p class="sm" style="color:{style['color']};font-weight:600;padding-top:8px;border-top:1px solid {style['border']}33;margin:0">{_esc(sc.get("outcome", ""))}</p>
</div>"""

    return f"""\
<!-- ========== SCENARIOS ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Proyección a 30 días</div>
<div class="h1 fu">Tres escenarios según nivel de acción</div>
<div class="sc-grid fu s2">
{cards_html}
</div>
</div></section>"""


def _slide_strategic_readings(
    readings: List[Dict[str, str]],
) -> str:
    """Slide 19: Strategic readings with 'Señal →' tags (rule 8)."""
    if not readings:
        return ""

    recs_html = ""
    delays = ["s2", "s3", "s3", "s4"]
    for i, rec in enumerate(readings[:6]):
        delay = delays[i] if i < len(delays) else "s4"
        signal = rec.get("signal", "")
        signal_html = f'<div class="rec-signal">Señal → {_esc(signal)}</div>' if signal else ""
        recs_html += f"""\
<div class="rec fu {delay}"><h3>{_esc(rec.get("title", ""))}</h3>
<p class="p" style="font-size:14px">{rec.get("body", "")}</p>
{signal_html}</div>
"""

    return f"""\
<!-- ========== STRATEGIC READINGS ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Lecturas estratégicas</div>
<div class="h1 fu">Señales que los datos emiten</div>
<p class="sub fu s2">No son instrucciones — son lecturas de lo que la conversación sugiere como dirección estratégica.</p>
{recs_html}
</div></section>"""


def _slide_applications(
    applications: List[Dict[str, str]],
    client_role: str = "",
) -> str:
    """Slide 20: Practical applications for the client."""
    if not applications:
        return ""

    mid = (len(applications) + 1) // 2
    left = applications[:mid]
    right = applications[mid:]

    def _cards(items: List[Dict[str, str]]) -> str:
        html = ""
        for item in items:
            html += f'<div class="card" style="margin-bottom:10px"><div class="h3">{_esc(item.get("title", ""))}</div><p class="sm">{_esc(item.get("body", ""))}</p></div>\n'
        return html

    role_label = f" para {_esc(client_role)}" if client_role else ""

    return f"""\
<!-- ========== APPLICATIONS ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Uso práctico</div>
<div class="h1 fu">Aplicaciones concretas{role_label}</div>
<div class="g2 fu s2">
<div>{_cards(left)}</div>
<div>{_cards(right)}</div>
</div>
</div></section>"""


def _slide_closing(
    standard_reading: str,
    deep_reading: str,
    closing_question: str = "",
    client_name: str = "",
    client_logo_url: str = "",
) -> str:
    """Slides 21-22: Closing (standard vs deep) + thank you."""
    sowhat_html = ""
    if closing_question:
        sowhat_html = f"""\
<div class="sowhat fu s3" style="margin-top:28px"><div class="sowhat-label">La pregunta que queda</div>
<p>{closing_question}</p></div>"""

    client_logo_img = ""
    if client_logo_url:
        client_logo_img = f"""\
<div style="width:1px;height:24px;background:var(--border)"></div>
<img src="{_esc(client_logo_url)}" alt="{_esc(client_name)}" style="height:20px;opacity:0.5" onerror="this.style.display='none'">"""

    return f"""\
<!-- ========== CLOSING ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Cierre</div>
<div class="h1 fu">La diferencia entre información y decisión</div>
<div class="g2 fu s2">
<div class="card card-m"><div class="h3" style="color:var(--dim)">Monitoreo estándar</div>
<p class="p" style="font-size:14px">{standard_reading}</p>
<p class="sm">Diagnóstico superficial. Estrategia reactiva.</p></div>
<div class="card card-b"><div class="h3">Análisis profundo</div>
<p class="p" style="font-size:14px">{deep_reading}</p>
<p class="sm" style="color:var(--cyan)">Diagnóstico preciso. Estrategia informada.</p></div>
</div>
{sowhat_html}
<div style="display:flex;justify-content:center;align-items:center;gap:40px;margin-top:56px" class="fu s4">
<img src="https://epical.digital/wp-content/uploads/2023/08/cropped-logoEpicalwhite-152x30-1.png" alt="Epical" style="height:16px;filter:brightness(0.3);opacity:0.5" onerror="this.style.display='none'">
{client_logo_img}
</div>
<p style="text-align:center;font-size:11px;color:var(--dim);margin-top:12px">Social & Consumer Intelligence aplicada a decisiones de negocio · epical.digital</p>
</div></section>"""


# ══════════════════════════════════════════════════════════════════════
# Chart.js script generation (rule 15, 19)
# ══════════════════════════════════════════════════════════════════════

def _build_charts_script(
    sentiment: Dict[str, Any],
    timeline_data: List[Dict[str, Any]],
    spikes: List[Dict[str, Any]],
    engagement_by_platform: List[Dict[str, Any]],
) -> str:
    """Generate Chart.js initialization script.

    Rule 15: charts ALWAYS inside div with position:relative + height.
    Rule 19: Chart.js 4.4.1 via Cloudflare CDN.
    """
    # Color constants
    GREEN = "#2B8A3E"
    RED = "#DC2626"
    GRAY = "#B0B0C8"
    CYAN = "#1098AD"

    # Sentiment donut data
    sent_labels = []
    sent_data = []
    sent_colors = []

    for key, val in sentiment.items():
        if not isinstance(val, dict):
            continue
        sent_labels.append(key.capitalize())
        sent_data.append(val.get("count", 0))
        klower = key.lower()
        if klower in ("positive", "positivo"):
            sent_colors.append(GREEN)
        elif klower in ("negative", "negativo"):
            sent_colors.append(RED)
        else:
            sent_colors.append(GRAY)

    # Volume chart data
    vol_labels = [d.get("date", "")[-5:] for d in timeline_data]  # MM-DD
    vol_data = [d.get("mentions", 0) for d in timeline_data]

    # Spike dates for point highlighting
    spike_dates = {s.get("date", "") for s in spikes}
    point_colors = []
    point_sizes = []
    for d in timeline_data:
        date_str = d.get("date", "")
        if date_str in spike_dates:
            point_colors.append(RED)
            point_sizes.append(6)
        else:
            point_colors.append(GRAY)
            point_sizes.append(2)

    return f"""\
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
var RED='#DC2626',GREEN='#2B8A3E',GRAY='#B0B0C8',DARK='#0F1635',PINK='#D6336C',CYAN='#1098AD',AMBER='#C27803',BDR='#E0E0EE';

/* Sentiment chart */
(function(){{
var el=document.getElementById('sentChart');
if(!el)return;
new Chart(el,{{type:'doughnut',data:{{labels:{_json.dumps(sent_labels)},datasets:[{{data:{_json.dumps(sent_data)},backgroundColor:{_json.dumps(sent_colors)},borderWidth:0}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom',labels:{{color:DARK,font:{{family:'DM Sans',size:11}},padding:16,usePointStyle:true,pointStyle:'circle'}}}}}}}}}});
}})();

/* Volume mini chart (in data slide) */
(function(){{
var el=document.getElementById('volMiniChart');
if(!el)return;
new Chart(el,{{type:'bar',data:{{labels:{_json.dumps(vol_labels)},datasets:[{{data:{_json.dumps(vol_data)},backgroundColor:CYAN+'44',borderColor:CYAN,borderWidth:1,borderRadius:3}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:DARK,font:{{family:'JetBrains Mono',size:9}},maxRotation:45}},grid:{{display:false}}}},y:{{ticks:{{color:GRAY,font:{{family:'JetBrains Mono',size:9}}}},grid:{{color:BDR}}}}}}}}}});
}})();

/* Volume timeline chart (full) */
(function(){{
var el=document.getElementById('volChart');
if(!el)return;
new Chart(el,{{type:'line',data:{{labels:{_json.dumps(vol_labels)},datasets:[{{data:{_json.dumps(vol_data)},borderColor:CYAN,backgroundColor:'rgba(16,152,173,0.08)',fill:true,tension:0.35,borderWidth:2.5,pointRadius:{_json.dumps(point_sizes)},pointBackgroundColor:{_json.dumps(point_colors)},pointBorderColor:'transparent'}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:DARK,font:{{family:'JetBrains Mono',size:10}}}},grid:{{color:BDR}}}},y:{{ticks:{{color:GRAY,font:{{family:'JetBrains Mono',size:9}}}},grid:{{color:BDR}}}}}}}}}});
}})();

/* Fade-in observer */
var obs=new IntersectionObserver(function(entries){{entries.forEach(function(e){{if(e.isIntersecting)e.target.classList.add('vis')}});}},{{threshold:0.08}});
document.querySelectorAll('.fu').forEach(function(el){{obs.observe(el)}});
</script>"""


# ══════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════

def build_report_html(
    client_name: str,
    period: str,
    report_text: str,
    metrics: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    output_path: Union[str, Path],
    logo_path: Optional[Union[str, Path]] = None,
    theme: str = "light",
    brand_color: str = "#FF1B6B",
    report_type: str = "crisis",
    # New v2 parameters for richer data
    report_sections: Optional[Dict[str, Any]] = None,
    event_date: Optional[str] = None,
    client_role: str = "",
    client_logo_url: str = "",
) -> Path:
    """Generate a self-contained HTML report based on the v10 editorial template.

    This is the v2 builder — parametrized from the Avianca reference report.
    Same public API as the original build_report_html for backward compatibility,
    with additional optional parameters for richer output.

    Args:
        client_name: Client name.
        period: Reporting period (e.g. "Marzo-Abril 2026").
        report_text: Claude-generated narrative (used as fallback if report_sections not provided).
        metrics: Full metrics dict from MetricsCalculator + pipeline.
        anomalies: Anomaly list from detect_anomalies.
        output_path: Destination file path.
        logo_path: Local path to client logo (not used in v2, prefer client_logo_url).
        theme: "light" (default) or "dark" (v2 always uses light content + navy transitions).
        brand_color: Client brand color hex.
        report_type: "crisis", "campaign", or "monitoring".
        report_sections: Pre-parsed narrative sections dict. If None, builds from report_text.
        event_date: Optional event/comunicado date for impact analysis slide.
        client_role: E.g. "la Dirección de Comunicaciones" for personalized labels.
        client_logo_url: URL to client logo for cover/closing.

    Returns:
        Path to the generated .html file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Parse sections from report_text if not provided ──────────
    if report_sections is None:
        report_sections = _parse_sections_from_text(report_text or "")

    # ── Extract metrics ──────────────────────────────────────────
    total_mentions = metrics.get("total_mentions", 0)
    sentiment = metrics.get("sentiment_breakdown", {})

    # Fix <na> labels
    sentiment = {("Sin clasificar" if k == "<na>" else k): v for k, v in sentiment.items()}

    timeline_data = metrics.get("timeline", {}).get("daily", [])
    spikes = metrics.get("spikes", [])
    engagement_by_platform = metrics.get("engagement_by_platform", [])
    reach_data = metrics.get("reach_deduplicated", {})
    tangential_data = metrics.get("tangential_analysis", {})
    comunicado_data = metrics.get("comunicado_impact", {})
    actor_metrics = metrics.get("actor_metrics", {})
    brand_criticism = metrics.get("brand_criticism", {})

    # Total engagement
    eng_total = 0
    for col in ("total_likes", "total_comments", "total_shares"):
        eng_total += metrics.get(col, 0)

    # ── Extract narrative sections ───────────────────────────────
    sec = report_sections
    cover_title = sec.get("cover_title", f"Inteligencia reputacional<br><em>{_esc(client_name)}</em>")
    cover_subtitle = sec.get("cover_subtitle", "Análisis profundo de la conversación digital.")
    findings = sec.get("findings", [])
    exec_implication = sec.get("exec_implication", "")
    narratives = sec.get("narratives", [])
    scenarios = sec.get("scenarios", [])
    readings = sec.get("readings", [])
    applications = sec.get("applications", [])
    methodology_rows = sec.get("methodology_rows", [])
    actors_data = sec.get("actors", [])
    data_insight = sec.get("data_insight", "")
    platform_insight = sec.get("platform_insight", "")
    timeline_insight = sec.get("timeline_insight", "")
    closing_standard = sec.get("closing_standard", "")
    closing_deep = sec.get("closing_deep", "")
    closing_question = sec.get("closing_question", "")

    # ── Build default methodology if not provided ────────────────
    if not methodology_rows:
        methodology_rows = [
            {"stage": "Recolección", "description": "Social listening + scrapping directo de perfiles", "result": _fmt(total_mentions)},
            {"stage": "Clasificación IA", "description": "Modelos propietarios de clasificación: relevancia, sentimiento, dirección", "result": _fmt(total_mentions)},
        ]
        # Add sentiment reclassification stats if available
        reclass = metrics.get("reclassification_stats", {})
        if reclass:
            methodology_rows.append({
                "stage": "Reclasificación",
                "description": f"Reglas: {reclass.get('rules', 0)}, IA: {reclass.get('ai', 0)}",
                "result": f"{reclass.get('remaining_pct', 0)}% restante",
            })

    # ── Build default platform data if engagement_by_platform empty
    if not engagement_by_platform:
        top_sources = metrics.get("top_sources", [])
        for src in top_sources[:6]:
            name = src[0] if isinstance(src, (list, tuple)) else str(src)
            count = src[1] if isinstance(src, (list, tuple)) and len(src) > 1 else 0
            engagement_by_platform.append({
                "platform": str(name),
                "mentions": int(count),
                "engagement_share": round(int(count) / max(total_mentions, 1) * 100, 1),
            })

    # ── Build actor slides from actor_metrics if not in sections ─
    if not actors_data and actor_metrics:
        for actor_key, actor_m in actor_metrics.items():
            if actor_key in ("combined", "otros"):
                continue
            am_total = actor_m.get("total_mentions", 0)
            if am_total == 0:
                continue
            am_sent = actor_m.get("sentiment_breakdown", {})
            bar = {}
            for sk, sv in am_sent.items():
                if isinstance(sv, dict):
                    bar[sk] = sv.get("percentage", 0)
            actors_data.append({
                "name": actor_key.capitalize(),
                "mentions": am_total,
                "pct": round(am_total / max(total_mentions, 1) * 100, 1),
                "title": f"Percepción sobre {actor_key.capitalize()}",
                "body": [],
                "sentiment_bar": bar,
                "reading": "",
                "posts": [],
            })

    # ── Assemble slides ──────────────────────────────────────────
    slides: List[str] = []

    # 1. Cover
    platforms_count = len(engagement_by_platform)
    slides.append(_slide_cover(
        client_name=client_name,
        period=period,
        title=cover_title,
        subtitle=cover_subtitle,
        total_raw=total_mentions,
        total_relevant=total_mentions,
        platforms_count=platforms_count,
        client_logo_url=client_logo_url,
    ))

    # 2. Executive summary
    if findings:
        slides.append(_slide_exec_summary(
            findings=findings,
            implication_body=exec_implication,
            client_role=client_role,
        ))

    # 3. Methodology
    slides.append(_slide_methodology(
        pipeline_rows=methodology_rows,
        sidebar_title=sec.get("methodology_sidebar_title", ""),
        sidebar_body=sec.get("methodology_sidebar_body", ""),
    ))

    # 4. The Data (KPIs)
    slides.append(_slide_data_kpis(
        total_relevant=total_mentions,
        sentiment=sentiment,
        reach_data=reach_data,
        engagement_total=eng_total,
        insight_text=data_insight,
    ))

    # 5. Transition: actors
    if actors_data:
        actor_names = [a.get("name", "") for a in actors_data[:3]]
        slides.append(_slide_transition(
            title="La conversación tiene actores distintos.<br>Cada uno requiere una lectura diferente.",
            subtitle=f"Actores analizados: {', '.join(actor_names)}." if actor_names else "",
        ))

    # 6-8. Actor slides
    for actor in actors_data[:5]:
        slides.append(_slide_actor(
            actor_name=actor.get("name", ""),
            mention_count=actor.get("mentions", 0),
            mention_pct=actor.get("pct", 0),
            title=actor.get("title", ""),
            body_paragraphs=actor.get("body", []),
            sentiment_bar=actor.get("sentiment_bar", {}),
            reading=actor.get("reading", ""),
            sample_posts=actor.get("posts"),
            criticism_table=actor.get("criticism_table"),
        ))

    # 9. Catalyst effect (OPTIONAL)
    if tangential_data.get("catalyst_detected"):
        slides.append(_slide_catalyst(
            tangential_data=tangential_data,
            sample_posts=sec.get("catalyst_posts"),
        ))

    # 10. Platforms
    if engagement_by_platform:
        slides.append(_slide_platforms(
            platform_data=engagement_by_platform,
            insight_text=platform_insight,
        ))

    # 11. Timeline
    if timeline_data:
        slides.append(_slide_timeline(
            spikes=spikes,
            insight_text=timeline_insight,
        ))

    # 12. Comunicado impact (OPTIONAL)
    if comunicado_data and comunicado_data.get("event_date"):
        slides.append(_slide_comunicado_impact(comunicado_data))
    elif event_date and "comunicado_impact" not in metrics:
        # If event_date passed but not computed yet, skip
        pass

    # 13. Transition: narratives
    if narratives:
        slides.append(_slide_transition(
            title="Los datos definen el presente.<br>Las narrativas definen cómo se recuerda.",
            subtitle=f"{len(narratives)} narrativas compiten por dar forma a la memoria colectiva.",
        ))

    # 14-16. Narratives
    if narratives:
        slides.append(_slide_narratives(narratives))

    # 17. Scenarios
    if scenarios:
        slides.append(_slide_scenarios(scenarios))

    # 18. Strategic readings
    if readings:
        slides.append(_slide_strategic_readings(readings))

    # 19. Applications
    if applications:
        slides.append(_slide_applications(applications, client_role=client_role))

    # 20-21. Closing
    slides.append(_slide_closing(
        standard_reading=closing_standard or f"{_fmt(total_mentions)} menciones procesadas con lectura superficial.",
        deep_reading=closing_deep or "Análisis profundo que revela lo que un dashboard no muestra.",
        closing_question=closing_question,
        client_name=client_name,
        client_logo_url=client_logo_url,
    ))

    # ── Assemble full HTML ───────────────────────────────────────
    body_html = "\n\n".join(s for s in slides if s)

    charts_script = _build_charts_script(
        sentiment=sentiment,
        timeline_data=timeline_data,
        spikes=spikes,
        engagement_by_platform=engagement_by_platform,
    )

    full_html = f"""\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(client_name)} — Inteligencia Reputacional | Epical</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
{_build_css()}
</head>
<body>

{body_html}

<!-- ========== SCRIPTS ========== -->
{charts_script}
</body>
</html>
"""

    output_path.write_text(full_html, encoding="utf-8")
    logger.info("HTML v2 report generated: %s (%d bytes, %d slides)",
                output_path, len(full_html), len(slides))
    return output_path


# ══════════════════════════════════════════════════════════════════════
# Section parser (from Claude-generated text)
# ══════════════════════════════════════════════════════════════════════

def _strip_signal_prefix(s: str) -> str:
    """Remove ALL 'Señal →' / 'Signal →' prefixes from a signal string.

    The HTML template adds its own 'Señal →' prefix, so the raw value
    should contain only the principle text, no prefix.
    """
    import re as _re
    result = s.strip()
    # Strip repeatedly in case of "Señal → Señal → ..."
    while _re.match(r"^(?:Señal|Signal)\s*→\s*", result, flags=_re.IGNORECASE):
        result = _re.sub(r"^(?:Señal|Signal)\s*→\s*", "", result, count=1, flags=_re.IGNORECASE).strip()
    return result


def _parse_sections_from_text(text: str) -> Dict[str, Any]:
    """Parse Claude-generated report text into structured sections dict.

    Supports the === delimited format from report_generator.py and
    falls back to markdown heading parsing.

    Returns dict with keys matching the report_sections parameter of
    build_report_html.
    """
    import re

    sections: Dict[str, Any] = {
        "cover_title": "",
        "cover_subtitle": "",
        "findings": [],
        "exec_implication": "",
        "narratives": [],
        "scenarios": [],
        "readings": [],
        "applications": [],
        "methodology_rows": [],
        "actors": [],
        "data_insight": "",
        "platform_insight": "",
        "timeline_insight": "",
        "closing_standard": "",
        "closing_deep": "",
        "closing_question": "",
    }

    if not text.strip():
        return sections

    # ── Try structured === format first ──────────────────────────
    if "===" in text:
        # Extract framework thesis as cover
        thesis_match = re.search(r"FRAMEWORK_THESIS:\s*(.+)", text)
        if thesis_match:
            sections["cover_subtitle"] = thesis_match.group(1).strip()

        name_match = re.search(r"FRAMEWORK_NAME:\s*(.+)", text)
        if name_match:
            sections["cover_title"] = name_match.group(1).strip()

        # Extract executive cards as findings
        for i in range(1, 4):
            card_match = re.search(
                rf"===EXECUTIVE_CARD_{i}===\s*\n(?:TITLE:\s*([^\n]+)\n)?(?:BODY:\s*)?(.+?)(?====|\Z)",
                text, re.DOTALL,
            )
            if card_match:
                title = (card_match.group(1) or "").strip()
                body = card_match.group(2).strip()
                sections["findings"].append({"title": title, "text": body[:500]})

        # Extract narratives
        narr_pattern = re.compile(
            r"===NARRATIVE_(\d+)===\s*\n(?:TITLE:\s*([^\n]+)\n)?(?:BADGE:\s*([^\n]+)\n)?(?:BODY:\s*)?(.+?)(?====|\Z)",
            re.DOTALL,
        )
        for m in narr_pattern.finditer(text):
            sections["narratives"].append({
                "title": (m.group(2) or "").strip(),
                "badge": (m.group(3) or "").strip(),
                "body": m.group(4).strip()[:800],
            })

        # Extract scenarios
        sc_pattern = re.compile(
            r"===SCENARIO_(\w+)===\s*\n(?:NAME:\s*([^\n]+)\n)?(?:DESCRIPTION:\s*)?(.+?)(?:OUTCOME:\s*([^\n]+))?(?====|\Z)",
            re.DOTALL,
        )
        for m in sc_pattern.finditer(text):
            sections["scenarios"].append({
                "name": (m.group(2) or "").strip(),
                "description": m.group(3).strip()[:500],
                "outcome": (m.group(4) or "").strip(),
            })

        # Extract signals/readings
        sig_pattern = re.compile(
            r"===SIGNAL_(\d+)===\s*\n(?:TITLE:\s*([^\n]+)\n)?(?:BODY:\s*)?(.+?)(?:SIGNAL:\s*([^\n]+))?(?====|\Z)",
            re.DOTALL,
        )
        for m in sig_pattern.finditer(text):
            sections["readings"].append({
                "title": (m.group(2) or "").strip(),
                "body": m.group(3).strip()[:600],
                "signal": _strip_signal_prefix(m.group(4) or ""),
            })

        # Extract perception/actor sections
        actor_pattern = re.compile(
            r"===PERCEPTION_(\w+)===\s*\n(?:EDITORIAL_TITLE:\s*([^\n]+)\n)?(?:EDITORIAL_SUBTITLE:\s*([^\n]+)\n)?(?:BODY:\s*)?(.+?)(?====|\Z)",
            re.DOTALL,
        )
        for m in actor_pattern.finditer(text):
            actor_key = m.group(1).strip()
            if actor_key.upper() == "BRAND":
                continue  # Brand perception handled separately
            sections["actors"].append({
                "name": actor_key.capitalize(),
                "title": (m.group(2) or "").strip(),
                "body": [p.strip() for p in m.group(4).strip().split("\n\n") if p.strip()],
                "reading": (m.group(3) or "").strip(),
            })

    # ── Fallback: markdown heading parsing ───────────────────────
    elif "#" in text:
        current_section = ""
        current_content = []

        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                # Save previous section
                if current_section and current_content:
                    _assign_markdown_section(sections, current_section, "\n".join(current_content))
                current_section = stripped[3:].strip().lower()
                current_content = []
            elif stripped.startswith("### "):
                current_content.append(line)
            else:
                current_content.append(line)

        if current_section and current_content:
            _assign_markdown_section(sections, current_section, "\n".join(current_content))

    return sections


def _assign_markdown_section(sections: Dict[str, Any], heading: str, content: str) -> None:
    """Map a markdown heading to the appropriate sections dict key."""
    heading_lower = heading.lower()
    content = content.strip()

    if any(k in heading_lower for k in ("resumen", "ejecutivo", "summary")):
        # Parse numbered findings
        import re
        items = re.split(r"\n\d+\.\s+", content)
        for item in items:
            item = item.strip()
            if item and len(item) > 20:
                sections["findings"].append({"title": "", "text": item[:500]})

    elif any(k in heading_lower for k in ("narrativa", "narrative")):
        # Parse sub-headings as narratives
        import re
        parts = re.split(r"###\s+", content)
        badges = ["Dominante", "Minoritaria · Riesgo", "Emergente · Oportunidad"]
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            sections["narratives"].append({
                "title": title,
                "badge": badges[i] if i < len(badges) else "",
                "body": body[:800],
            })

    elif any(k in heading_lower for k in ("escenario", "scenario", "proyección")):
        import re
        parts = re.split(r"###\s+", content)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            sections["scenarios"].append({
                "name": lines[0].strip(),
                "description": lines[1].strip()[:500] if len(lines) > 1 else "",
                "outcome": "",
            })

    elif any(k in heading_lower for k in ("lectura", "reading", "señal", "signal", "recomend")):
        import re
        parts = re.split(r"###\s+", content)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            signal_match = re.search(r"(?:Señal|Signal)\s*→\s*(.+)", part)
            sections["readings"].append({
                "title": lines[0].strip(),
                "body": lines[1].strip()[:600] if len(lines) > 1 else "",
                "signal": _strip_signal_prefix(signal_match.group(1)) if signal_match else "",
            })

    elif any(k in heading_lower for k in ("aplicacion", "application", "uso práctico")):
        import re
        parts = re.split(r"###\s+", content)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            sections["applications"].append({
                "title": lines[0].strip(),
                "body": lines[1].strip()[:300] if len(lines) > 1 else "",
            })
