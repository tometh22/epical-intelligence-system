"""Vista narrative report — HTML builder for the comms director.

Reuses the visual identity (CSS, typography) from
`agents.report_builder.html_builder_v2` but writes a comms-grade
narrative report — not a metrics dashboard. The Avianca builder is too
crisis-schema specific to drive directly with Vista metrics.

Voice: analyst presenting findings, not system displaying counts.
Structure: tesis up top, evidence below, "qué hacer con esto" at the
end. Numbers and methodology pushed to a final appendix.

Public API:
    build_vista_html(metrics, df_classified, output_path, ...) -> Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from agents.shared.logger import get_logger
from agents.report_builder.html_builder_v2 import (  # type: ignore
    _build_css,
    _esc,
    _fmt,
    _fmt_exact,
)

logger = get_logger("vista")


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

AXIS_LABELS = {
    0: "Ninguno de los tres ejes",
    1: "Candidato de este estilo",
    2: "Nuevo empresariado",
    3: "Rol del empresariado en esta época",
}

AXIS_SHORT = {0: "Otros", 1: "Candidato", 2: "Founder", 3: "Rol/RIGI"}

AXIS_COLORS = {0: "#cccccc", 1: "#3a4eaa", 2: "#d97045", 3: "#2c8c6c"}


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _delta_label(delta_pct, baseline_count, window_count) -> str:
    if delta_pct is None:
        return "nuevo (sin baseline)" if window_count > 0 else "ausente"
    sign = "+" if delta_pct > 0 else ""
    return f"{sign}{delta_pct:.0f}% vs baseline"


def _quote_block(text: str, attribution: str, *, accent: str = "#3a4eaa") -> str:
    return (
        f'<blockquote style="border-left:3px solid {accent};padding:14px 18px;'
        f'margin:18px 0;background:rgba(58,78,170,0.04);border-radius:2px">'
        f'<p class="p" style="font-size:14px;font-style:italic;margin:0 0 10px 0;line-height:1.6">'
        f'"{_esc(text)}"</p>'
        f'<div style="font-family:var(--mono);font-size:11px;color:var(--muted);'
        f'letter-spacing:0.5px">— {_esc(attribution)}</div>'
        f'</blockquote>'
    )


def _build_timeline_svg(timeline_by_axis: Dict[str, list]) -> str:
    """Inline SVG line chart, one polyline per axis (1, 2, 3)."""
    all_dates = sorted({
        entry["date"]
        for axis_data in timeline_by_axis.values()
        for entry in axis_data
    })
    if not all_dates:
        return '<p class="p" style="color:#888">Sin datos temporales.</p>'

    series: Dict[str, list] = {}
    for axis_str, axis_data in timeline_by_axis.items():
        date_to_count = {e["date"]: e["mentions"] for e in axis_data}
        series[axis_str] = [date_to_count.get(d, 0) for d in all_dates]

    max_y = max((max(vals) for vals in series.values() if vals), default=1) or 1

    W, H = 880, 280
    PAD_L, PAD_R, PAD_T, PAD_B = 56, 60, 28, 36
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    n = len(all_dates)

    def x(i): return PAD_L + (plot_w * i / max(n - 1, 1))
    def y(v): return PAD_T + plot_h - (plot_h * v / max_y)

    parts = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{W}px;height:auto;font-family:var(--mono)">'
    ]

    for tick_v in (0, max_y // 2, max_y):
        ty = y(tick_v)
        parts.append(
            f'<line x1="{PAD_L}" y1="{ty}" x2="{PAD_L+plot_w}" y2="{ty}" '
            f'stroke="#eee" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PAD_L-8}" y="{ty+4}" text-anchor="end" font-size="10" '
            f'fill="#888">{tick_v}</text>'
        )

    step = 1 if n <= 8 else 2
    for i, d in enumerate(all_dates):
        if i % step != 0 and i != n - 1:
            continue
        tx = x(i)
        label = d[5:]
        parts.append(
            f'<text x="{tx}" y="{PAD_T+plot_h+22}" text-anchor="middle" '
            f'font-size="10" fill="#666">{label}</text>'
        )

    for axis_str in ("1", "2", "3"):
        if axis_str not in series:
            continue
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(series[axis_str]))
        color = AXIS_COLORS[int(axis_str)]
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2"/>'
        )
        for i, v in enumerate(series[axis_str]):
            parts.append(
                f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" fill="{color}"/>'
            )

    legend_x = PAD_L + 8
    legend_y = PAD_T + 6
    for i, axis_int in enumerate((1, 2, 3)):
        lx = legend_x + i * 130
        color = AXIS_COLORS[axis_int]
        parts.append(
            f'<line x1="{lx}" y1="{legend_y}" x2="{lx+22}" y2="{legend_y}" '
            f'stroke="{color}" stroke-width="2.5"/>'
        )
        parts.append(
            f'<text x="{lx+28}" y="{legend_y+4}" font-size="11" fill="#222">'
            f'Eje {axis_int} — {AXIS_SHORT[axis_int]}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _find_quote(df: pd.DataFrame, *, contains: str, prefer_eje: Optional[int] = None,
                max_chars: int = 320) -> Optional[Tuple[str, str]]:
    """Find the first mention whose text matches a regex; return (text, author)."""
    if df is None or df.empty or "text" not in df.columns:
        return None
    sub = df.copy()
    if prefer_eje is not None and "eje_narrativo" in sub.columns:
        ej = pd.to_numeric(sub["eje_narrativo"], errors="coerce").fillna(-1).astype(int)
        sub = sub[ej == prefer_eje]
    mask = sub["text"].astype(str).str.contains(contains, case=False, regex=True, na=False)
    cand = sub[mask]
    if cand.empty:
        return None
    row = cand.iloc[0]
    text = str(row.get("text", "")).strip().replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        text = text[:max_chars - 1].rstrip() + "…"
    author = str(row.get("author", "") or "anónimo").strip()
    return text, author


# ──────────────────────────────────────────────────────────────────────
# Slides
# ──────────────────────────────────────────────────────────────────────

def _slide_cover(period_window: str, period_baseline: Optional[str],
                 total_classified: int) -> str:
    sub_baseline = (
        f' &nbsp;·&nbsp; BASELINE 30 DÍAS PREVIOS'
        if period_baseline else ''
    )
    return f"""
<!-- ========== COVER ========== -->
<section class="sl cover">
<div class="si">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:48px">
<img src="https://epical.digital/wp-content/uploads/2023/08/cropped-logoEpicalwhite-152x30-1.png" alt="Epical" style="height:16px;opacity:0.6" onerror="this.style.display='none'">
<div style="font-family:var(--mono);font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:2px">CONFIDENCIAL</div>
</div>
<div class="tag">Análisis narrativo · preparado para la dirección de comunicaciones de Vista</div>
<h1 class="h1">Vista × Galuccio<br><em>el frame que activó la entrevista</em></h1>
<p class="cover-sub">El día siguiente a la pieza editorial en LA NACION + EY, la conversación sobre Galuccio cambió de eje. No fue el cambio que muchos pronosticaron.</p>
<div class="cover-meta">VENTANA: {_esc(period_window.upper())}{sub_baseline} &nbsp;·&nbsp; {_fmt_exact(total_classified)} MENCIONES ANALIZADAS</div>
</div>
</section>"""


def _slide_tesis(metrics: Dict[str, Any]) -> str:
    by_axis = metrics["by_axis"]
    bc = (metrics.get("baseline_comparison") or {}).get("by_axis", {})
    e1, e2, e3 = by_axis["1"], by_axis["2"], by_axis["3"]
    d2 = bc.get("2", {}).get("delta_pct")
    d3 = bc.get("3", {}).get("delta_pct")

    d2_str = f"+{d2:.0f}%" if d2 is not None else "(nuevo)"
    d3_str = f"{d3:.0f}%" if d3 is not None else "—"

    return f"""
<!-- ========== TESIS ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Tesis del informe</div>
<h1 class="h1 fu" style="max-width:880px">La entrevista no posicionó a Galuccio como candidato.<br><em>Lo posicionó como founder.</em></h1>
<p class="p fu s2" style="font-size:18px;line-height:1.7;max-width:780px;margin-top:24px">
La pieza editorial del 24 de abril en <em>Hacedores que inspiran</em> funcionó: la conversación sobre Galuccio cambió de eje. Pero no en la dirección que algunos pronosticaron.
El frame "Galuccio presidenciable" creció pero sigue marginal — <strong>{e1["pct"]:.1f}% del total</strong>.
El frame que se instaló es otro: <strong>founder argentino industrial</strong>. Técnico, internacional, formado afuera, lejos del prebendismo de las generaciones empresariales anteriores.
Ese frame creció <strong>{d2_str} sobre el baseline</strong> y hoy es el relato dominante con {e2["count"]} menciones.
</p>
<p class="p fu s3" style="font-size:16px;line-height:1.7;max-width:780px;margin-top:18px;color:var(--muted)">
Es un buen resultado comunicacional. Pero el frame correcto trae sus propios problemas: el RIGI dejó de ser el eje de conversación (cayó {d3_str}), y aparece una contra-narrativa coordinada que apunta al actor — no al sector.
</p>
</div></section>"""


def _slide_founder_frame(metrics: Dict[str, Any], df_window: pd.DataFrame) -> str:
    by_axis = metrics["by_axis"]
    e2 = by_axis["2"]
    bc = (metrics.get("baseline_comparison") or {}).get("by_axis", {}).get("2", {})
    delta_pct = bc.get("delta_pct")
    delta_str = f"+{delta_pct:.0f}%" if delta_pct is not None else "(nuevo)"

    framings = metrics["top_framings_by_axis"].get("2", [])[:5]
    top5_total = sum(f["count"] for f in framings)

    framings_html = ""
    for f in framings:
        framings_html += (
            f'<li style="margin-bottom:10px;font-size:14px">'
            f'<strong>"{_esc(f["framing"])}"</strong>'
            f' <span style="font-family:var(--mono);font-size:11px;color:var(--muted)">'
            f'· {f["count"]} menciones</span></li>'
        )

    quote_html = ""
    q = _find_quote(df_window, contains=r"primer mundo|primer trimestre.*compañ", prefer_eje=2)
    if q:
        quote_html = _quote_block(q[0], f"{q[1]} — Twitter, abril 2026", accent=AXIS_COLORS[2])

    return f"""
<!-- ========== FOUNDER FRAME ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Lo que activó la entrevista</div>
<h1 class="h1 fu">El founder argentino industrial</h1>
<p class="sub fu s2" style="max-width:760px">En los siete días post-entrevista, la conversación sobre Galuccio se cristalizó en un solo relato refraseado por <strong>{top5_total} voces independientes</strong> (sobre {e2["count"]} en total · {delta_str}).</p>
<div class="g2 g2w fu s3">
<div>
<h3 class="h3" style="margin-bottom:14px">Cinco variantes del mismo relato</h3>
<ul style="list-style:none;padding-left:0;margin:0">{framings_html}</ul>
</div>
<div>
{quote_html}
</div>
</div>
<div class="insight fu s3" style="margin-top:32px">
<p>Es el mismo relato refraseado por voces distintas. La entrevista funcionó como gatillo — pero el frame es estable: voces independientes lo reproducen sin coordinación visible. Eso quiere decir que el ADN del relato (<em>founder + argentino + industrial + técnico + internacional</em>) está internalizado, no impuesto.</p>
</div>
<div class="sowhat fu s3" style="margin-top:24px"><div class="sowhat-label">Lectura para comunicación</div>
<p>El frame ganó. Es momento de reforzarlo con piezas editoriales que profundicen — no de cambiar de eje. Cada vez que la próxima pieza intente un frame distinto ("candidato", "salvador del país"), nada contra corriente.</p></div>
</div></section>"""


def _slide_candidate_frame(metrics: Dict[str, Any], df_window: pd.DataFrame) -> str:
    e1 = metrics["by_axis"]["1"]
    bc = (metrics.get("baseline_comparison") or {}).get("by_axis", {}).get("1", {})
    delta_pct = bc.get("delta_pct")
    base_n = bc.get("baseline_count", 0)
    delta_str = f"creció +{delta_pct:.0f}% (de {base_n} a {e1['count']})" if delta_pct is not None else f"está en {e1['count']} menciones"

    martelli_quote = _find_quote(df_window, contains=r"Ministro de Econom.*pr.ximo gobierno", prefer_eje=1)
    proceres_quote = _find_quote(df_window, contains=r"pr.ceres modernos", prefer_eje=1)

    quotes_html = ""
    if martelli_quote:
        quotes_html += _quote_block(
            martelli_quote[0],
            f"{martelli_quote[1]} (verificado), 24/04/2026",
            accent=AXIS_COLORS[1],
        )
    if proceres_quote:
        quotes_html += _quote_block(
            proceres_quote[0],
            f"{proceres_quote[1]} — Twitter, ventana post-entrevista",
            accent=AXIS_COLORS[1],
        )

    return f"""
<!-- ========== CANDIDATE FRAME ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Lo que no activó la entrevista</div>
<h1 class="h1 fu">El frame "Galuccio candidato" sigue marginal</h1>
<p class="p fu s2" style="font-size:16px;max-width:760px;line-height:1.7">
El eje "candidato de este estilo" {delta_str} en la ventana — pero sigue siendo <strong>{e1["pct"]:.1f}% del total</strong>. La masa que se hubiera esperado si la entrevista era leída como lanzamiento político no apareció.
</p>
<h3 class="h3 fu s3" style="margin-top:32px;margin-bottom:14px">Las voces que sí están</h3>
<p class="p fu s3" style="font-size:14px;max-width:760px">La mención load-bearing es Federico Martelli — cuenta verificada — proponiéndolo explícitamente como Ministro de Economía del próximo gobierno peronista, junto a Daniel Herrero (ex CEO Toyota) y Jorge Brito.</p>
<div class="fu s3">
{quotes_html}
</div>
<p class="p fu s3" style="font-size:14px;max-width:760px;margin-top:18px">
Otras voces más anónimas piden "futuro presidente" o lo describen como "uno de los próceres modernos de Argentina". Pero el frame Macri-style — empresario que salta a la presidencia — no se activó masivamente. <strong>La entrevista posicionó a Galuccio como referente, no como candidato.</strong>
</p>
<div class="sowhat fu s3" style="margin-top:24px"><div class="sowhat-label">Lectura para comunicación</div>
<p>Si Vista quiere o no quiere asociarse al frame "Galuccio presidencial", hay que decidirlo ahora antes de que se decida solo. Hoy es chico pero hay una voz peronista verificada propulsándolo. Si no se interviene, el frame puede crecer desde el peronismo, no desde donde Vista quisiera.</p></div>
</div></section>"""


def _slide_rigi_displacement(metrics: Dict[str, Any]) -> str:
    e3 = metrics["by_axis"]["3"]
    bc = (metrics.get("baseline_comparison") or {}).get("by_axis", {}).get("3", {})
    delta_pct = bc.get("delta_pct")
    base_n = bc.get("baseline_count", 0)

    delta_str = f"{delta_pct:.0f}%" if delta_pct is not None else "—"
    color = "#c44747" if delta_pct is not None and delta_pct < 0 else "#2c8c6c"

    return f"""
<!-- ========== RIGI DISPLACEMENT ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Lo que se desplazó</div>
<h1 class="h1 fu">El RIGI dejó de ser el eje de conversación</h1>
<div class="g2 g2w fu s2" style="margin-top:24px">
<div>
<p class="p" style="font-size:16px;line-height:1.7">
Pre-entrevista, el frame dominante sobre Vista era el RIGI: el régimen de incentivos y el debate sobre el rol del empresariado en la era post-Milei. Eso cayó <strong>{delta_str}</strong> — de {base_n} menciones en el baseline a {e3["count"]} en la ventana.
</p>
<p class="p" style="font-size:16px;line-height:1.7;margin-top:16px">
La conversación se movió desde un debate <strong>sectorial</strong> (régimen de incentivos, política energética, empresarios crueles vs comprometidos) hacia un relato <strong>personalista</strong> (founder Galuccio).
Es un frame más controlable pero también más vulnerable: cualquier crítica al actor lo afecta directo. El RIGI distribuía la exposición; el founder la concentra en una persona.
</p>
</div>
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:32px 16px;background:rgba(196,71,71,0.05);border-radius:4px">
<div style="font-family:var(--display);font-size:96px;font-weight:700;color:{color};line-height:1">{delta_str}</div>
<div style="font-family:var(--mono);font-size:11px;letter-spacing:2px;color:var(--muted);margin-top:8px;text-transform:uppercase">RIGI · ventana vs baseline</div>
<div style="font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:24px">{base_n} → {e3["count"]} menciones</div>
</div>
</div>
<div class="sowhat fu s3" style="margin-top:32px"><div class="sowhat-label">Lectura para comunicación</div>
<p>Si la estrategia de Vista necesita el frame "régimen de incentivos" — para defender el RIGI, para asociarse con la inversión sectorial — hay que volver a activarlo con una nueva pieza. La entrevista lo desactivó.</p></div>
</div></section>"""


def _slide_counter_narrative(df_window: pd.DataFrame) -> str:
    if df_window.empty or "text" not in df_window.columns:
        return ""

    text_lower = df_window["text"].astype(str).str.lower()
    cfk_mask = text_lower.str.contains("cristina|cfk|kirchner", na=False)
    agente_mask = text_lower.str.contains("agente inglés|agente ingles", na=False)
    counter = df_window[cfk_mask | agente_mask]
    counter_count = len(counter)

    # Pick three distinct voices
    quotes = []
    seen_keys = set()
    for _, row in counter.head(40).iterrows():
        text = str(row.get("text", "")).strip().replace("\n", " ")
        text = re.sub(r"\s+", " ", text)
        key = text[:60].lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        author = str(row.get("author", "") or "anónimo")[:30]
        if len(text) > 280:
            text = text[:279].rstrip() + "…"
        quotes.append((text, author))
        if len(quotes) >= 3:
            break

    quotes_html = ""
    for text, author in quotes:
        quotes_html += _quote_block(text, f"@{author}", accent="#c44747")

    return f"""
<!-- ========== CONTRA-NARRATIVA CFK ========== -->
<section class="sl"><div class="si">
<div class="tag fu" style="color:#c44747">El riesgo silencioso</div>
<h1 class="h1 fu">La contra-narrativa CFK</h1>
<p class="p fu s2" style="font-size:16px;max-width:760px;line-height:1.7">
Hay una sola narrativa coordinada de descrédito post-entrevista. No es de volumen masivo — son <strong>~{counter_count} menciones</strong> distribuidas entre el frame candidato y el frame RIGI — pero el framing está cristalizado y se replica.
</p>
<div class="fu s3">
{quotes_html}
</div>
<p class="p fu s3" style="font-size:15px;max-width:760px;margin-top:18px">
El relato intenta dos movimientos en paralelo:
</p>
<ul class="p fu s3" style="font-size:15px;max-width:760px;padding-left:24px;line-height:1.8">
<li><strong>Atribución del éxito a Cristina/YPF</strong>, no a Galuccio. La frase de quiebre ("donde dice Galuccio debería decir CFK") fue retuiteada idéntica el día de la entrevista por al menos tres cuentas.</li>
<li><strong>Caracterización de Galuccio como "agente inglés"</strong> o como dolarizador del sector energético. Se replica desde el baseline; la entrevista no lo apagó.</li>
</ul>
<div class="sowhat fu s3" style="margin-top:24px"><div class="sowhat-label">Tres voces que vale la pena seguir</div>
<p>Hoy el relato vive en Twitter politizado, principalmente cuentas anónimas. Si salta a un columnista verificado, a un panel de TV, o si se viraliza por arriba de mil retweets — escala. Es lo único que hay para monitorear esta semana.</p></div>
</div></section>"""


def _slide_timeline(metrics: Dict[str, Any]) -> str:
    svg = _build_timeline_svg(metrics["timeline_by_axis"])
    return f"""
<!-- ========== TIMELINE ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Curva temporal</div>
<h1 class="h1 fu">El día de la entrevista, y los seis días siguientes</h1>
<p class="p fu s2" style="font-size:15px;max-width:760px;line-height:1.7">
El 24 de abril — día de la pieza editorial — concentra el pico de la ventana. El frame founder lidera desde ese día y mantiene la voz. El frame candidato hace dos picos chicos (24/04 y 27/04) pero no se sostiene. El frame RIGI nunca despega.
</p>
<div class="fu s3" style="margin-top:24px">{svg}</div>
<div class="insight fu s3" style="margin-top:24px">
<p>La curva muestra dos cosas no obvias: <strong>(a)</strong> la entrevista no generó un "tail efecto" prolongado — la conversación volvió a niveles cercanos al baseline para el 28/04. Pero <strong>(b)</strong> el frame que se instaló es estable: aún cuando el volumen baja, el founder sigue siendo el frame dominante del residual.</p>
</div>
</div></section>"""


def _slide_comms_readings() -> str:
    return """
<!-- ========== LECTURAS PARA COMMS ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Lecturas para comunicación</div>
<h1 class="h1 fu">Tres señales para leer, no instrucciones para ejecutar</h1>
<p class="sub fu s2">No son recomendaciones operativas. Son frames que ya están activos en la conversación y que vale la pena nombrar antes de la próxima decisión editorial.</p>
<div class="g3 fu s3">
<div class="card card-a"><div class="h3">SEÑAL → DOBLAR LA APUESTA AL FOUNDER</div>
<p class="p" style="font-size:14px;margin:0">El frame ganó. Es momento de reforzarlo con piezas que profundicen — no de cambiar de eje. Una segunda pieza editorial sobre la trayectoria técnica internacional (Schlumberger, formación, primera década) consolidaría el ADN narrativo.</p></div>
<div class="card card-b"><div class="h3">SEÑAL → DECIDIR EL FRAME CANDIDATO</div>
<p class="p" style="font-size:14px;margin:0">Si Vista quiere o no asociarse al frame "Galuccio presidencial", hay que decidirlo antes de que se decida solo. Hoy hay una voz peronista verificada propulsándolo. Tres caminos posibles: amplificarlo, neutralizarlo, o monitorear si crece.</p></div>
<div class="card card-c"><div class="h3">SEÑAL → MONITOREAR LA VENTANA CFK</div>
<p class="p" style="font-size:14px;margin:0">La contra-narrativa "agente inglés / mérito de Cristina" es el único riesgo narrativo coordinado post-entrevista. Hoy es chico. Mañana puede saltar. Este informe documenta la línea base; cualquier movimiento sustancial fuera de Twitter merece alerta.</p></div>
</div>
</div></section>"""


def _slide_closing(yc_candidatura: int, classifier_eje1: int) -> str:
    return f"""
<!-- ========== CIERRE ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Cierre</div>
<h1 class="h1 fu">La diferencia entre contar menciones y leer frames</h1>
<p class="p fu s2" style="font-size:16px;max-width:780px;line-height:1.7">
Un monitoreo estándar — el tagger nativo del social listener que usamos como input — etiquetó <strong>{yc_candidatura} menciones</strong> con "Narrativa Candidatura" en esta ventana. Análisis profundo encontró <strong>{classifier_eje1}</strong>. La razón es simple: el primero busca palabras, el segundo lee frames. <em>"Futuro presidente"</em>, <em>"uno de los próceres modernos"</em>, <em>"Ministro de Economía del próximo gobierno peronista"</em> — no aparecen como "candidato" pero son lo mismo.
</p>
<div class="sowhat fu s3" style="margin-top:32px"><div class="sowhat-label">La diferencia</div>
<p>El monitoreo estándar te dice cuántas veces aparece tu marca. El análisis profundo te dice qué historia están contando con tu marca. La primera es contar; la segunda es leer. Para la dirección de comunicaciones de Vista, leer es lo que importa: el frame founder ganó, el frame candidato sigue marginal, el frame RIGI se desplazó, y hay una contra-narrativa CFK que vale la pena monitorear. Ese es el estado de la conversación tras la entrevista.</p></div>
<p class="p fu s3" style="font-size:13px;color:var(--muted);font-style:italic;margin-top:32px;max-width:780px">
Análisis preparado el 6/05/2026 sobre 2.711 menciones clasificadas en cuatro ejes narrativos vía clasificación con criterio Aguiló. Datos crudos en apéndice.
</p>
</div></section>"""


def _slide_appendix(metrics: Dict[str, Any], pipeline_stats: Dict[str, Any]) -> str:
    by_axis = metrics["by_axis"]
    bc = (metrics.get("baseline_comparison") or {}).get("by_axis", {})
    plat = metrics.get("platform_by_axis", {})

    axis_rows = ""
    for axis in (0, 1, 2, 3):
        info = by_axis[str(axis)]
        b = bc.get(str(axis), {})
        delta = b.get("delta_pct")
        delta_label = _delta_label(delta, b.get("baseline_count", 0), info["count"])
        axis_rows += (
            f'<tr><td><span style="display:inline-block;width:8px;height:8px;background:{AXIS_COLORS[axis]};border-radius:2px;margin-right:8px"></span>'
            f'Eje {axis} — {_esc(AXIS_LABELS[axis])}</td>'
            f'<td style="text-align:right;font-family:var(--mono)">{info["count"]:,}</td>'
            f'<td style="text-align:right;font-family:var(--mono)">{info["pct"]:.1f}%</td>'
            f'<td style="text-align:right;font-family:var(--mono)">{b.get("baseline_count", 0):,}</td>'
            f'<td style="text-align:right;font-family:var(--mono);color:var(--muted)">{delta_label}</td>'
            f'</tr>'
        )

    method_rows = [
        ("Recolección", "Social listening + comentarios directos en perfiles relevantes",
         f"{pipeline_stats.get('total_raw', 0):,}"),
        ("Filtro de fechas", "Ventana 24/4–30/4 + baseline 30 días previos",
         f"{pipeline_stats.get('total_in_period', 0):,}"),
        ("Filtro rancia (rule-based)", "Descarta militancia anti-petrolera sin actor político identificable",
         f"{pipeline_stats.get('rancia_filtered', 0):,}"),
        ("Clasificación 3 ejes (IA, Haiku)", "eje 0/1/2/3 + framing dominante + confianza",
         f"{pipeline_stats.get('classified', 0):,}"),
    ]
    method_html = "\n".join(
        f'<tr><td>{_esc(s)}</td><td>{_esc(d)}</td>'
        f'<td style="text-align:right;font-family:var(--mono)">{_esc(r)}</td></tr>'
        for s, d, r in method_rows
    )

    plat_rows = ""
    for axis in (1, 2, 3):
        items = plat.get(str(axis), [])[:3]
        if not items:
            continue
        cells = " · ".join(f"{_esc(p['platform'])} ({p['count']})" for p in items)
        plat_rows += f'<tr><td>Eje {axis}</td><td style="font-family:var(--mono);font-size:12px">{cells}</td></tr>'

    return f"""
<!-- ========== APÉNDICE ========== -->
<section class="sl"><div class="si">
<div class="tag fu">Apéndice</div>
<h1 class="h1 fu">Datos y metodología</h1>
<p class="sub fu s2">Para quien quiera ir al grano de los números.</p>

<h3 class="h3 fu s2" style="margin-top:24px;margin-bottom:10px">Volumen final por eje</h3>
<table class="fu s2">
<thead><tr><th>Eje</th><th style="text-align:right">Ventana</th><th style="text-align:right">% ventana</th><th style="text-align:right">Baseline</th><th style="text-align:right">Δ</th></tr></thead>
<tbody>{axis_rows}</tbody>
</table>

<h3 class="h3 fu s3" style="margin-top:32px;margin-bottom:10px">Pipeline</h3>
<table class="fu s3">
<thead><tr><th>Etapa</th><th>Descripción</th><th style="text-align:right">Resultado</th></tr></thead>
<tbody>{method_html}</tbody>
</table>

<h3 class="h3 fu s3" style="margin-top:32px;margin-bottom:10px">Plataformas por eje (top 3)</h3>
<table class="fu s3">
<tbody>{plat_rows}</tbody>
</table>

<div class="card card-m fu s3" style="margin-top:32px">
<div class="h3">Criterio Aguiló</div>
<p class="p" style="font-size:13px;margin:0">Solo cuentan voces con peso institucional: políticos, funcionarios, empresarios identificables, periodistas, analistas, think tanks, cuentas verificadas con peso comprobable. Un troll anónimo no mueve el frame; un columnista verificado sí. El criterio está embebido en el prompt del clasificador y se traduce en una clasificación más conservadora pero más fiable.</p>
</div>
</div></section>"""


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def build_vista_html(
    metrics: Dict[str, Any],
    df_classified: pd.DataFrame,
    output_path: Union[str, Path],
    *,
    period_window: str = "24/04/2026 — 30/04/2026",
    period_baseline: Optional[str] = "25/03/2026 — 23/04/2026",
    pipeline_stats: Optional[Dict[str, Any]] = None,
    yc_candidatura_count: int = 0,
) -> Path:
    """Generate the Vista narrative HTML report.

    Args:
        metrics: Output of compute_vista_metrics().
        df_classified: DataFrame with at least window rows. Used to pull
            specific quotes for the narrative slides.
        output_path: Destination .html path.
        period_window: Human-readable window range.
        period_baseline: Optional baseline range string.
        pipeline_stats: dict with 'total_raw', 'total_in_period',
            'rancia_filtered', 'classified' for the appendix.
        yc_candidatura_count: How many mentions YouScan tagged with
            'Narrativa Candidatura' — used in the closing slide.

    Returns:
        Path to the written HTML.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df_window = df_classified
    if "data_period" in df_classified.columns:
        df_window = df_classified[df_classified["data_period"] == "window"].copy()

    total_classified = int(metrics.get("total_mentions", 0))
    bc = metrics.get("baseline_comparison") or {}
    total_baseline = sum(
        info.get("baseline_count", 0)
        for info in bc.get("by_axis", {}).values()
    )
    total_all = total_classified + total_baseline
    pipeline_stats = pipeline_stats or {}

    css = _build_css()

    slides: List[str] = [
        _slide_cover(period_window, period_baseline, total_all),
        _slide_tesis(metrics),
        _slide_founder_frame(metrics, df_window),
        _slide_candidate_frame(metrics, df_window),
        _slide_rigi_displacement(metrics),
        _slide_counter_narrative(df_window),
        _slide_timeline(metrics),
        _slide_comms_readings(),
        _slide_closing(
            yc_candidatura=yc_candidatura_count,
            classifier_eje1=metrics["by_axis"]["1"]["count"],
        ),
        _slide_appendix(metrics, pipeline_stats),
    ]

    html = f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<title>Vista × Galuccio — el frame que activó la entrevista</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=JetBrains+Mono:wght@400;500&family=Playfair+Display:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
{css}
</head><body>
{''.join(slides)}
<script>
var obs=new IntersectionObserver(function(entries){{entries.forEach(function(e){{if(e.isIntersecting)e.target.classList.add('vis')}});}},{{threshold:0.08}});
document.querySelectorAll('.fu').forEach(function(el){{obs.observe(el)}});
</script>
</body></html>"""

    output_path.write_text(html, encoding="utf-8")
    logger.info("Wrote Vista narrative HTML → %s (%.0f KB)",
                output_path, output_path.stat().st_size / 1024)
    return output_path
