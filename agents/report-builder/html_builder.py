"""Self-contained HTML visual report generator.

Generates a dark editorial intelligence report as a single HTML file
with scroll-snap sections, Chart.js / D3.js visualizations, and CSS animations.
"""

import base64
import json
import html as html_mod
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from agents.shared.logger import get_logger

logger = get_logger("report-builder")


# ---------------------------------------------------------------------------
# Platform normalisation
# ---------------------------------------------------------------------------

_PLATFORM_CANONICAL: Dict[str, str] = {
    "facebook": "Facebook",
    "facebook.com": "Facebook",
    "Facebook": "Facebook",
    "tiktok": "TikTok",
    "tiktok.com": "TikTok",
    "TikTok": "TikTok",
    "instagram": "Instagram",
    "instagram.com": "Instagram",
    "Instagram": "Instagram",
    "twitter.com": "Twitter",
    "twitter": "Twitter",
    "Twitter": "Twitter",
    "youtube.com": "YouTube",
    "youtube": "YouTube",
    "YouTube": "YouTube",
}


def _normalize_platforms(
    top_sources: List[List[Any]],
) -> List[List[Any]]:
    """Merge duplicate platform names and return sorted by total count."""
    merged: Dict[str, int] = {}
    for entry in top_sources:
        name = str(entry[0])
        count = int(entry[1]) if len(entry) > 1 else 0
        canonical = _PLATFORM_CANONICAL.get(name, name)
        merged[canonical] = merged.get(canonical, 0) + count
    result = [[name, count] for name, count in merged.items()]
    result.sort(key=lambda x: x[1], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Sentiment label fix
# ---------------------------------------------------------------------------

def _fix_sentiment_labels(
    sentiment: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace '<na>' key with 'Sin clasificar'."""
    fixed: Dict[str, Any] = {}
    for key, val in sentiment.items():
        new_key = "Sin clasificar" if key == "<na>" else key
        fixed[new_key] = val
    return fixed


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def _parse_report_sections(text: str) -> Dict[str, Any]:
    """Parse Claude-generated report into structured sections.

    Supports two formats:
    1. NEW: === delimited structured format (from updated report_generator)
    2. LEGACY: ## markdown headers (backward compatible)

    Returns a dict with editorial content ready for rendering.
    """
    result: Dict[str, Any] = {
        "framework_name": "",
        "framework_thesis": "",
        "exec_cards": [],
        "signals": [],
        "perception_brand": {"title": "", "subtitle": "", "body": ""},
        "perception_actor": {"title": "", "subtitle": "", "body": ""},
        "collision_zone": {"title": "", "subtitle": "", "body": ""},
        "narratives": [],
        "platform_deepdive": {"title": "", "subtitle": "", "insights": {}},
        "scenarios": [],
        "recommendations": [],
        "methodology": "",
        "hook": "Lo que revelan los datos.",
        # Legacy compat
        "resumen_ejecutivo": "",
        "metricas": "",
        "senales": "",
        "plataformas_texto": "",
        "escenarios_texto": "",
        "anomalias_texto": "",
        "picos_texto": "",
        "hallazgos": "",
    }

    if not text or not text.strip():
        return result

    # Detect format: === delimiters or ## markdown
    if "===" in text and ("EXECUTIVE_CARD" in text or "PERCEPTION_BRAND" in text or "NARRATIVE_1" in text):
        return _parse_structured_format(text, result)
    else:
        return _parse_markdown_format(text, result)


def _parse_structured_format(text: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the new === delimited structured format."""

    def _get_field(block: str, field: str) -> str:
        """Extract a field value from a block like 'FIELD: value'."""
        pattern = re.compile(r'^' + re.escape(field) + r':\s*(.+?)(?=\n[A-Z_]+:|$)', re.MULTILINE | re.DOTALL)
        m = pattern.search(block)
        return m.group(1).strip() if m else ""

    # Extract top-level fields
    fw_name = re.search(r'FRAMEWORK_NAME:\s*(.+)', text)
    if fw_name:
        result["framework_name"] = fw_name.group(1).strip()
    fw_thesis = re.search(r'FRAMEWORK_THESIS:\s*(.+)', text)
    if fw_thesis:
        result["framework_thesis"] = fw_thesis.group(1).strip()
        result["hook"] = fw_thesis.group(1).strip()

    # Split on === delimiters
    blocks = re.split(r'===([A-Z_0-9]+)===', text)
    # blocks alternates: [preamble, NAME1, content1, NAME2, content2, ...]
    block_map = {}  # type: Dict[str, str]
    for i in range(1, len(blocks) - 1, 2):
        name = blocks[i].strip()
        content = blocks[i + 1].strip()
        block_map[name] = content

    # Executive cards
    for n in range(1, 4):
        key = f"EXECUTIVE_CARD_{n}"
        if key in block_map:
            title = _get_field(block_map[key], "TITLE")
            body = _get_field(block_map[key], "BODY")
            result["exec_cards"].append({"title": title, "body": body})
            if n == 1 and body:
                hook = _extract_first_sentence(body)
                if hook:
                    result["hook"] = hook

    # Build legacy resumen from exec cards
    if result["exec_cards"]:
        result["resumen_ejecutivo"] = "\n\n".join(c["body"] for c in result["exec_cards"] if c["body"])

    # Signals
    if "SIGNALS" in block_map:
        for n in range(1, 6):
            val = _get_field(block_map["SIGNALS"], f"SIGNAL_{n}")
            if val:
                result["signals"].append(val)
        result["senales"] = "\n\n".join(result["signals"])

    # Perception sections
    for section_key, result_key in [
        ("PERCEPTION_BRAND", "perception_brand"),
        ("PERCEPTION_ACTOR", "perception_actor"),
        ("COLLISION_ZONE", "collision_zone"),
    ]:
        if section_key in block_map:
            blk = block_map[section_key]
            result[result_key] = {
                "title": _get_field(blk, "EDITORIAL_TITLE"),
                "subtitle": _get_field(blk, "EDITORIAL_SUBTITLE"),
                "body": _get_field(blk, "BODY"),
            }

    # Narratives
    for n in range(1, 8):
        key = f"NARRATIVE_{n}"
        if key in block_map:
            blk = block_map[key]
            evidence = []
            for e in range(1, 6):
                ev = _get_field(blk, f"EVIDENCE_{e}")
                if ev:
                    evidence.append(ev)
            result["narratives"].append({
                "thesis": _get_field(blk, "THESIS"),
                "evolution": _get_field(blk, "EVOLUTION"),
                "evidence": evidence,
                "implication": _get_field(blk, "IMPLICATION"),
                "risk_level": _get_field(blk, "RISK_LEVEL"),
                "dominant_platform": _get_field(blk, "DOMINANT_PLATFORM"),
            })

    # Legacy compat: also populate narrativas for existing rendering
    legacy_narrs = []
    for narr in result["narratives"]:
        content_parts = []
        if narr["evolution"]:
            content_parts.append(narr["evolution"])
        for ev in narr["evidence"]:
            content_parts.append(ev)
        if narr["implication"]:
            content_parts.append(narr["implication"])
        legacy_narrs.append({
            "title": narr["thesis"],
            "content": "\n\n".join(content_parts),
        })
    if legacy_narrs:
        result["narrativas"] = legacy_narrs

    # Platform deepdive
    if "PLATFORM_DEEPDIVE" in block_map:
        blk = block_map["PLATFORM_DEEPDIVE"]
        insights = {}
        for plat in ["TIKTOK", "FACEBOOK", "INSTAGRAM", "TWITTER", "YOUTUBE"]:
            val = _get_field(blk, f"{plat}_INSIGHT")
            if val:
                insights[plat.lower()] = val
        result["platform_deepdive"] = {
            "title": _get_field(blk, "EDITORIAL_TITLE"),
            "subtitle": _get_field(blk, "EDITORIAL_SUBTITLE"),
            "insights": insights,
        }
        result["plataformas_texto"] = "\n\n".join(
            f"{k.capitalize()}: {v}" for k, v in insights.items()
        )

    # Scenarios
    for letter in ["A", "B", "C"]:
        key = f"SCENARIO_{letter}"
        if key in block_map:
            blk = block_map[key]
            result["scenarios"].append({
                "name": _get_field(blk, "NAME"),
                "trigger": _get_field(blk, "TRIGGER") or _get_field(blk, "PROBABILITY_TRIGGER"),
                "description": _get_field(blk, "DESCRIPTION"),
                "consequence": _get_field(blk, "CONSEQUENCE"),
            })
    if result["scenarios"]:
        result["escenarios_texto"] = "\n\n".join(
            f"{s['name']}: {s['description']}" for s in result["scenarios"]
        )

    # Recommendations
    for n in range(1, 6):
        key = f"RECOMMENDATION_{n}"
        if key in block_map:
            blk = block_map[key]
            result["recommendations"].append({
                "title": _get_field(blk, "TITLE"),
                "data_support": _get_field(blk, "DATA_SUPPORT"),
                "action": _get_field(blk, "ACTION"),
                "metric": _get_field(blk, "METRIC"),
                "deadline": _get_field(blk, "DEADLINE"),
            })
    # Legacy compat
    if result["recommendations"]:
        result["recomendaciones"] = [
            {"title": r["title"], "content": f"{r['action']}\n{r['data_support']}\n{r['metric']}", "category": ""}
            for r in result["recommendations"]
        ]

    # Methodology
    if "METHODOLOGY" in block_map:
        result["methodology"] = _get_field(block_map["METHODOLOGY"], "BODY") or block_map["METHODOLOGY"]
        result["metodologia"] = result["methodology"]

    return result


def _parse_markdown_format(text: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Parse legacy ## markdown format (backward compatible)."""

    section_pattern = re.compile(r'^(#{1,2})\s+(.+)', re.MULTILINE)
    matches = list(section_pattern.finditer(text))

    sections = {}  # type: Dict[str, str]
    for i, m in enumerate(matches):
        header = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        key = _normalise_header(header)
        sections[key] = body

    for key, body in sections.items():
        if "resumen" in key and "ejecutivo" in key:
            result["resumen_ejecutivo"] = body
            hook = _extract_first_sentence(body)
            if hook:
                result["hook"] = hook
        elif "senales" in key or "datos revelan" in key:
            result["senales"] = body
        elif "metrica" in key:
            result["metricas"] = body
        elif "como recibio" in key or "recepcion" in key or "percepcion" in key and any(w in key for w in ("avianca", "marca", "brand")):
            result["perception_brand"] = {"title": "", "subtitle": "", "body": body}
        elif "percepcion" in key:
            result["perception_actor"] = {"title": "", "subtitle": "", "body": body}
        elif "colision" in key or "interseccion" in key or "zona" in key:
            result["collision_zone"] = {"title": "", "subtitle": "", "body": body}
        elif "narrativa" in key:
            result["narrativas"] = _parse_sub_sections(body)
        elif "lectura" in key or "plataforma" in key:
            result["plataformas_texto"] = body
        elif "escenario" in key:
            result["escenarios_texto"] = body
        elif "pico" in key or ("analisis" in key and "anomalia" in key):
            result["picos_texto"] = body
        elif "anomalia" in key or "alerta" in key:
            result["anomalias_texto"] = body
        elif "recomendacion" in key or "estrategic" in key:
            result["recomendaciones"] = _parse_recommendations(body)
        elif "metodolog" in key or "nota" in key:
            result["metodologia"] = body
        elif "hallazgo" in key:
            result["hallazgos"] = body

    return result


def _normalise_header(header: str) -> str:
    """Lower-case, strip accents for matching."""
    h = header.lower().strip()
    replacements = {
        "\u00e1": "a", "\u00e9": "e", "\u00ed": "i",
        "\u00f3": "o", "\u00fa": "u", "\u00f1": "n",
    }
    for orig, repl in replacements.items():
        h = h.replace(orig, repl)
    return h


def _extract_first_sentence(text: str) -> str:
    """Return the first sentence (up to first period followed by space or EOL)."""
    clean = re.sub(r'^[\s\n*_]+', '', text)
    m = re.match(r'(.+?[.!?])(?:\s|$)', clean, re.DOTALL)
    if m:
        sentence = m.group(1).strip()
        sentence = re.sub(r'\*\*(.+?)\*\*', r'\1', sentence)
        sentence = re.sub(r'\*(.+?)\*', r'\1', sentence)
        return sentence
    first_line = clean.split('\n')[0].strip()
    if first_line:
        return first_line
    return ""


def _parse_sub_sections(body: str) -> List[Dict[str, str]]:
    """Parse ### sub-sections into list of {title, content}."""
    pattern = re.compile(r'^###\s+(.+)', re.MULTILINE)
    matches = list(pattern.finditer(body))
    if not matches:
        if body.strip():
            return [{"title": "Narrativa Principal", "content": body.strip()}]
        return []

    results: List[Dict[str, str]] = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        title = re.sub(r'^\d+[\.\)\-\s]+', '', title).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        results.append({"title": title, "content": content})
    return results


def _parse_recommendations(body: str) -> List[Dict[str, str]]:
    """Parse recommendations from body text. Finds ### RECOMENDACION N headers."""
    # Remove draft badge
    body = re.sub(r'\*\*Borrador.*?\*\*', '', body).strip()

    # Try ### headers first (RECOMENDACION 1, RECOMENDACION 2, etc.)
    pattern = re.compile(r'^###\s+RECOMENDACI[O\u00d3]N\s+\d+[:\s]*(.*)', re.MULTILINE | re.IGNORECASE)
    matches = list(pattern.finditer(body))

    if matches:
        results: List[Dict[str, str]] = []
        for i, m in enumerate(matches):
            title = m.group(1).strip().strip('*').strip(':').strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            content = body[start:end].strip()
            results.append({"title": title, "content": content, "category": ""})
        return results

    # Fallback: split on **Recomendacion**: pattern
    parts = re.split(r'\*\*Recomendaci[o\u00f3]n\*\*\s*[:\uFF1A]\s*', body)
    parts = [p.strip() for p in parts if p.strip()]
    results = []
    for part in parts:
        lines = part.split('\n')
        title_lines: List[str] = []
        rest_lines: List[str] = []
        found_sub = False
        for line in lines:
            if re.match(r'^\*\*(Acci[o\u00f3]n|Fundamento|Implementaci|M[e\u00e9]trica)', line):
                found_sub = True
            if found_sub:
                rest_lines.append(line)
            else:
                title_lines.append(line)
        title = ' '.join(title_lines).strip()
        content = '\n'.join(rest_lines).strip()
        if title:
            results.append({"title": title, "content": content, "category": ""})

    if results:
        return results

    # Last resort: numbered items
    items = _parse_numbered_items(body)
    return items if items else ([{"title": "Recomendaci\u00f3n", "content": body, "category": ""}] if body.strip() else [])


def _parse_numbered_items(text: str) -> List[Dict[str, str]]:
    """Parse numbered items like '1. **Title**: content'."""
    pattern = re.compile(
        r'^\d+[\.\)]\s*\*?\*?(.+?)\*?\*?\s*[:\-\u2014]?\s*(.*)',
        re.MULTILINE,
    )
    items: List[Dict[str, str]] = []
    for m in pattern.finditer(text):
        title = m.group(1).strip().strip('*').strip(':').strip()
        content = m.group(2).strip()
        if title:
            items.append({"title": title, "content": content, "category": ""})
    return items


_SUBLABEL_KEYWORDS = frozenset([
    "contexto", "din\u00e1mica", "dinamica", "implicaci\u00f3n", "implicacion",
    "se\u00f1ales", "senales", "se\u00f1ales a monitorear",
    "recomendaci\u00f3n", "recomendacion", "fundamento", "implementaci\u00f3n",
    "implementacion", "m\u00e9trica de \u00e9xito", "metrica de exito",
    "m\u00e9trica", "metrica",
])


def _is_sublabel_line(stripped: str) -> bool:
    """Check if a line starts with a bold label like **Contexto**:"""
    m = re.match(r'^\*\*(.+?)\*\*\s*[:\uFF1A\-\u2014]?\s*', stripped)
    if not m:
        return False
    label = m.group(1).strip().lower().rstrip(":")
    if label in _SUBLABEL_KEYWORDS:
        return True
    if stripped.startswith("**") and (":" in stripped[:60] or "\u2014" in stripped[:60]):
        return True
    return False


def _md_to_html_block(text: str) -> str:
    """Convert a block of markdown text to HTML with styled sub-labels."""
    if not text:
        return ""
    lines = text.split("\n")
    parts: List[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue

        if stripped.startswith("### ") or stripped.startswith("## ") or stripped.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            content = _inline_format(stripped[2:])
            parts.append(f"<li>{content}</li>")
        elif _is_sublabel_line(stripped):
            if in_list:
                parts.append("</ul>")
                in_list = False
            m = re.match(r'^\*\*(.+?)\*\*\s*[:\uFF1A\-\u2014]?\s*(.*)', stripped)
            if m:
                label = html_mod.escape(m.group(1).strip())
                rest = m.group(2).strip()
                parts.append(
                    f'<div style="margin-top:20px;margin-bottom:6px;">'
                    f'<span style="font-family:\'IBM Plex Sans\',sans-serif;font-size:12px;'
                    f'font-weight:600;text-transform:uppercase;letter-spacing:1.5px;'
                    f'color:#FF1B6B;">{label}</span></div>'
                )
                if rest:
                    parts.append(f"<p>{_inline_format(rest)}</p>")
            else:
                content = _inline_format(stripped)
                parts.append(f"<p>{content}</p>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            content = _inline_format(stripped)
            parts.append(f"<p>{content}</p>")

    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def _inline_format(text: str) -> str:
    """Handle bold and italic inline markdown formatting."""
    result = html_mod.escape(text)
    result = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', result)
    result = re.sub(r'\*(.+?)\*', r'<em>\1</em>', result)
    return result


# ---------------------------------------------------------------------------
# Dynamic executive summary cards (replaces hardcoded EXEC_CARDS)
# ---------------------------------------------------------------------------

def _build_exec_cards_from_report(
    resumen_text: str,
    client_name: str,
) -> List[Dict[str, str]]:
    """Build 3 executive summary cards from resumen_ejecutivo text.

    Splits the text into 3 roughly equal parts by sentences and assigns
    them to the standard card structure.
    """
    titles = [
        "LO QUE PAS\u00d3",
        "LO QUE EST\u00c1 EN JUEGO",
        "LO QUE SE DEBE DECIDIR AHORA",
    ]
    colors = ["#FF1B6B", "#00D4FF", "#FFB800"]

    if not resumen_text or not resumen_text.strip():
        return [
            {"title": titles[0], "color": colors[0], "text": "Sin datos de resumen ejecutivo disponibles."},
            {"title": titles[1], "color": colors[1], "text": ""},
            {"title": titles[2], "color": colors[2], "text": ""},
        ]

    # Clean markdown formatting
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', resumen_text)
    clean = re.sub(r'\*(.+?)\*', r'\1', clean)
    clean = re.sub(r'^[\s\n*_#]+', '', clean)

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', clean.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        return [
            {"title": titles[0], "color": colors[0], "text": clean.strip()},
            {"title": titles[1], "color": colors[1], "text": ""},
            {"title": titles[2], "color": colors[2], "text": ""},
        ]

    # Distribute sentences into 3 roughly equal groups
    n = len(sentences)
    third = max(1, n // 3)
    parts = [
        " ".join(sentences[:third]),
        " ".join(sentences[third:third * 2]),
        " ".join(sentences[third * 2:]),
    ]

    # Truncate each part to ~600 chars at last sentence boundary
    for j in range(len(parts)):
        if len(parts[j]) > 600:
            cut = parts[j][:600].rfind('.')
            if cut > 200:
                parts[j] = parts[j][:cut + 1]

    return [
        {"title": titles[i], "color": colors[i], "text": parts[i]}
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# Dynamic insight generation (replaces hardcoded INSIGHT_* constants)
# ---------------------------------------------------------------------------

def _generate_insights_from_data(
    metrics: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    actor_breakdown: Dict[str, Any],
) -> Dict[str, str]:
    """Generate insight strings dynamically from actual data."""

    total_mentions = metrics.get("total_mentions", 0)
    sentiment = _fix_sentiment_labels(metrics.get("sentiment_breakdown", {}))
    volume_by_date = metrics.get("volume_by_date", {})
    top_sources_raw = metrics.get("top_sources", [])
    top_sources = _normalize_platforms(top_sources_raw)
    topic_clusters = metrics.get("topic_clusters", [])
    intersection_data = metrics.get("intersection", {})

    # --- insight_kpi: share of voice from actor_breakdown ---
    insight_kpi = ""
    if actor_breakdown:
        total_actor = sum(actor_breakdown.values()) or 1
        sorted_actors = sorted(actor_breakdown.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_actors) >= 2:
            primary_name = str(sorted_actors[0][0]).capitalize()
            primary_pct = (sorted_actors[0][1] / total_actor) * 100
            second_name = str(sorted_actors[1][0]).capitalize()
            second_pct = (sorted_actors[1][1] / total_actor) * 100
            insight_kpi = (
                f"{primary_name} gener\u00f3 el {primary_pct:.1f}% de la conversaci\u00f3n, "
                f"{second_name} solo el {second_pct:.1f}%. "
                f"El share of voice revela qui\u00e9n realmente controla la narrativa."
            )
        elif len(sorted_actors) == 1:
            name = str(sorted_actors[0][0]).capitalize()
            insight_kpi = f"{name} concentra la totalidad de la conversaci\u00f3n monitoreada."
    if not insight_kpi:
        insight_kpi = "Sin datos suficientes de actores para calcular share of voice."

    # --- insight_volume: biggest spike ---
    insight_volume = ""
    if volume_by_date:
        dates = list(volume_by_date.keys())
        values = list(volume_by_date.values())
        max_change = 0.0
        spike_date = ""
        for i in range(1, len(values)):
            prev = values[i - 1] if values[i - 1] > 0 else 1
            change = values[i] / prev
            if change > max_change:
                max_change = change
                spike_date = dates[i]
        if max_change > 1 and spike_date:
            insight_volume = (
                f"El pico del {spike_date} multiplic\u00f3 el volumen {max_change:.0f}x en 24 horas."
            )
        else:
            insight_volume = "No se detectaron picos significativos de volumen en el per\u00edodo analizado."
    else:
        insight_volume = "Sin datos de volumen por fecha disponibles."

    # --- insight_timeline: gap before first spike ---
    insight_timeline = ""
    if volume_by_date:
        dates = list(volume_by_date.keys())
        values = list(volume_by_date.values())
        avg_val = sum(values) / len(values) if values else 0
        threshold = avg_val * 2
        first_spike_idx = None
        for i, v in enumerate(values):
            if v > threshold:
                first_spike_idx = i
                break
        if first_spike_idx is not None and first_spike_idx > 0:
            insight_timeline = (
                f"Hubo {first_spike_idx} d\u00edas de bajo volumen antes de la explosi\u00f3n."
            )
        else:
            insight_timeline = "La conversaci\u00f3n no mostr\u00f3 un per\u00edodo de latencia significativo antes del pico."
    else:
        insight_timeline = "Sin datos de cronolog\u00eda disponibles."

    # --- insight_sentiment: neg/pos ratio ---
    insight_sentiment = ""
    pos_count = 0
    neg_count = 0
    unclassified_count = 0
    total_sent = 0
    for key, val in sentiment.items():
        count = val["count"] if isinstance(val, dict) else int(val)
        total_sent += count
        k = key.lower()
        if k in ("positive", "positivo"):
            pos_count = count
        elif k in ("negative", "negativo"):
            neg_count = count
        elif k in ("sin clasificar",):
            unclassified_count = count

    if pos_count > 0 and neg_count > 0:
        ratio = neg_count / pos_count
        unclass_pct = (unclassified_count / total_sent * 100) if total_sent > 0 else 0
        insight_sentiment = (
            f"El ratio negativo-positivo es {ratio:.1f}:1. "
        )
        if unclass_pct > 10:
            insight_sentiment += (
                f"El {unclass_pct:.0f}% sin clasificar representa "
                f"la audiencia m\u00e1s influenciable."
            )
    elif total_sent > 0:
        insight_sentiment = "Los datos de sentimiento no permiten calcular un ratio negativo-positivo claro."
    else:
        insight_sentiment = "Sin datos de sentimiento disponibles."

    # --- insight_heatmap: top topic cluster ---
    insight_heatmap = ""
    if topic_clusters:
        top_cluster = max(topic_clusters, key=lambda c: c.get("mention_count", 0))
        total_cluster_mentions = sum(c.get("mention_count", 0) for c in topic_clusters) or 1
        pct = (top_cluster.get("mention_count", 0) / total_cluster_mentions) * 100
        insight_heatmap = (
            f"Los clusters tem\u00e1ticos muestran concentraci\u00f3n en "
            f"{top_cluster.get('label', 'tema principal')} "
            f"({pct:.0f}% de las menciones)."
        )
    else:
        insight_heatmap = "Sin datos de clusters tem\u00e1ticos disponibles para el mapa de calor."

    # --- insight_actor_graph: intersection ---
    insight_actor_graph = ""
    if intersection_data and intersection_data.get("intersection_pct") is not None:
        inter_pct = intersection_data.get("intersection_pct", 0)
        insight_actor_graph = (
            f"Solo el {inter_pct}% de las menciones referencia "
            f"ambos actores simult\u00e1neamente."
        )
    elif actor_breakdown and len(actor_breakdown) >= 2:
        insight_actor_graph = (
            "Los actores principales operan en ecosistemas narrativos "
            "mayormente separados."
        )
    else:
        insight_actor_graph = "Sin datos suficientes para analizar la red de actores."

    # --- insight_wordcloud: top keywords ---
    insight_wordcloud = ""
    if topic_clusters:
        all_keywords: List[str] = []
        for cluster in topic_clusters:
            kws = cluster.get("keywords", [])
            all_keywords.extend(kws[:3])
        top_3 = all_keywords[:3] if all_keywords else []
        if top_3:
            insight_wordcloud = (
                f"Las palabras dominantes giran en torno a: "
                f"{', '.join(top_3)}."
            )
        else:
            insight_wordcloud = "Sin palabras clave destacadas en los clusters tem\u00e1ticos."
    else:
        insight_wordcloud = "Sin datos de clusters tem\u00e1ticos para el an\u00e1lisis de lenguaje."

    # --- insight_platforms: top platform ---
    insight_platforms = ""
    if top_sources and len(top_sources) >= 2:
        total_src = sum(s[1] for s in top_sources) or 1
        top_name = top_sources[0][0]
        top_pct = (top_sources[0][1] / total_src) * 100
        second_name = top_sources[1][0]
        second_pct = (top_sources[1][1] / total_src) * 100
        insight_platforms = (
            f"{top_name} concentra el {top_pct:.0f}% de las menciones. "
            f"{second_name} tiene {second_pct:.0f}%."
        )
    elif top_sources:
        total_src = sum(s[1] for s in top_sources) or 1
        top_name = top_sources[0][0]
        top_pct = (top_sources[0][1] / total_src) * 100
        insight_platforms = f"{top_name} concentra el {top_pct:.0f}% de las menciones."
    else:
        insight_platforms = "Sin datos de plataformas disponibles."

    # --- insight_recommendations: always generic ---
    insight_recommendations = (
        "Las recomendaciones son secuenciales \u2014 el orden de "
        "ejecuci\u00f3n importa tanto como la ejecuci\u00f3n misma."
    )

    return {
        "insight_kpi": insight_kpi,
        "insight_volume": insight_volume,
        "insight_timeline": insight_timeline,
        "insight_sentiment": insight_sentiment,
        "insight_heatmap": insight_heatmap,
        "insight_actor_graph": insight_actor_graph,
        "insight_wordcloud": insight_wordcloud,
        "insight_platforms": insight_platforms,
        "insight_recommendations": insight_recommendations,
    }


# ---------------------------------------------------------------------------
# Dynamic spike explorer (replaces hardcoded spike data)
# ---------------------------------------------------------------------------

def _build_spike_buttons_html(anomalies: List[Dict[str, Any]]) -> str:
    """Build spike explorer buttons HTML from volume_spike anomalies."""
    spike_anomalies = [
        a for a in anomalies
        if a.get("type", "").lower().replace(" ", "_") in (
            "volume_spike", "spike", "pico_de_volumen", "pico",
        )
    ]
    if not spike_anomalies:
        return ""

    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    buttons: List[str] = []
    for i, a in enumerate(spike_anomalies[:8]):
        letter = letters[i] if i < len(letters) else str(i)
        data = a.get("data", {})
        date_str = ""
        pct_str = ""
        if isinstance(data, dict):
            date_str = data.get("date", data.get("fecha", ""))
            pct_val = data.get("pct_change", data.get("change", ""))
            if pct_val:
                pct_str = f"+{pct_val}%" if not str(pct_val).startswith("+") else str(pct_val)
        active_class = " active" if i == 0 else ""
        buttons.append(
            f'<button class="spike-btn{active_class}" data-spike="{i}">'
            f'<span class="spike-letter">{html_mod.escape(letter)}</span>'
            f'<span class="spike-dates">{html_mod.escape(str(date_str))}</span>'
            f'<span class="spike-pct">{html_mod.escape(str(pct_str))}</span>'
            f'</button>'
        )
    return "\n".join(buttons)


def _build_spike_js_data(anomalies: List[Dict[str, Any]]) -> str:
    """Build JavaScript array literal for spike explorer data."""
    spike_anomalies = [
        a for a in anomalies
        if a.get("type", "").lower().replace(" ", "_") in (
            "volume_spike", "spike", "pico_de_volumen", "pico",
        )
    ]
    if not spike_anomalies:
        return "[]"

    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    entries: List[str] = []
    for i, a in enumerate(spike_anomalies[:8]):
        letter = letters[i] if i < len(letters) else str(i)
        data = a.get("data", {})
        date_str = ""
        pct_str = ""
        volume_str = ""
        platform_str = ""
        tone_str = ""
        if isinstance(data, dict):
            date_str = data.get("date", data.get("fecha", ""))
            pct_val = data.get("pct_change", data.get("change", ""))
            if pct_val:
                pct_str = f"+{pct_val}%" if not str(pct_val).startswith("+") else str(pct_val)
            volume_str = str(data.get("volume", data.get("volumen", "")))
            platform_str = str(data.get("platform", data.get("plataforma", "")))
            tone_str = str(data.get("tone", data.get("tono", "")))

        desc = a.get("description", "Anomal\u00eda de volumen detectada.")
        # Escape for JS string
        desc_js = desc.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
        date_js = str(date_str).replace("'", "\\'")
        pct_js = str(pct_str).replace("'", "\\'")
        vol_js = str(volume_str).replace("'", "\\'")
        plat_js = str(platform_str).replace("'", "\\'")
        tone_js = str(tone_str).replace("'", "\\'")

        entry = (
            "    {\n"
            f"        id: '{letter}', dates: '{date_js}', pctChange: '{pct_js}',\n"
            f"        description: '{desc_js}',\n"
            f"        volume: '{vol_js}',\n"
            f"        platform: '{plat_js}',\n"
            f"        tone: '{tone_js}'\n"
            "    }"
        )
        entries.append(entry)
    return "[\n" + ",\n".join(entries) + "\n]"


# ---------------------------------------------------------------------------
# Dynamic findings (replaces hardcoded Hallazgos section)
# ---------------------------------------------------------------------------

def _build_findings_html(
    sections: Dict[str, Any],
    actor_breakdown: Dict[str, Any],
    sentiment: Dict[str, Any],
    top_authors: List[List[Any]],
    client_name: str,
) -> str:
    """Build findings section HTML from parsed report or generated from data."""
    hallazgos_text = sections.get("hallazgos", "")

    # If hallazgos content exists in the report, render it
    if hallazgos_text and hallazgos_text.strip():
        return (
            f'<div class="fade-up stagger-2">'
            f'{_md_to_html_block(hallazgos_text)}'
            f'</div>'
        )

    # Otherwise generate findings from data
    cards: List[str] = []
    card_idx = 0

    # Finding 1: Top author analysis
    if top_authors and len(top_authors) >= 3:
        total_author_mentions = sum(a[1] for a in top_authors if len(a) > 1) or 1
        top_3_mentions = sum(a[1] for a in top_authors[:3] if len(a) > 1)
        top_3_pct = (top_3_mentions / total_author_mentions) * 100
        card_idx += 1
        cards.append(
            f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);'
            f'border-top:3px solid #FFB800;border-radius:0 0 16px 16px;padding:28px;">'
            f'<div style="font-family:\'Bebas Neue\',sans-serif;font-size:48px;color:rgba(255,184,0,0.3);'
            f'line-height:1;margin-bottom:12px;">0{card_idx}</div>'
            f'<h3 style="font-size:18px;font-weight:700;color:#fff;margin-bottom:16px;line-height:1.3;">'
            f'Concentraci&oacute;n de autores</h3>'
            f'<p style="color:#A0AEC0;font-size:14px;line-height:1.8;margin-bottom:12px;">'
            f'{len(top_authors[:3])} autores concentran el {top_3_pct:.0f}% de las menciones. '
            f'La conversaci&oacute;n est&aacute; dominada por un grupo reducido de voces.</p>'
            f'<div style="background:rgba(255,184,0,0.1);border:1px solid rgba(255,184,0,0.2);'
            f'border-radius:6px;padding:8px 12px;font-size:11px;color:#FFB800;letter-spacing:0.5px;">'
            f'SE&Ntilde;AL: Monitorear la actividad de los autores principales como indicador temprano.</div>'
            f'</div>'
        )

    # Finding 2: Actor disparity
    if actor_breakdown and len(actor_breakdown) >= 2:
        sorted_actors = sorted(actor_breakdown.items(), key=lambda x: x[1], reverse=True)
        primary_name = str(sorted_actors[0][0]).capitalize()
        primary_count = sorted_actors[0][1]
        second_name = str(sorted_actors[1][0]).capitalize()
        second_count = sorted_actors[1][1]
        if second_count > 0 and primary_count > second_count:
            ratio = primary_count / second_count
            card_idx += 1
            cards.append(
                f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);'
                f'border-top:3px solid #FFB800;border-radius:0 0 16px 16px;padding:28px;">'
                f'<div style="font-family:\'Bebas Neue\',sans-serif;font-size:48px;color:rgba(255,184,0,0.3);'
                f'line-height:1;margin-bottom:12px;">0{card_idx}</div>'
                f'<h3 style="font-size:18px;font-weight:700;color:#fff;margin-bottom:16px;line-height:1.3;">'
                f'Disparidad entre actores</h3>'
                f'<p style="color:#A0AEC0;font-size:14px;line-height:1.8;margin-bottom:12px;">'
                f'{primary_name} gener&oacute; {ratio:.1f}x m&aacute;s conversaci&oacute;n que '
                f'{second_name}. Esta asimetr&iacute;a define qui&eacute;n controla la narrativa.</p>'
                f'<div style="background:rgba(255,184,0,0.1);border:1px solid rgba(255,184,0,0.2);'
                f'border-radius:6px;padding:8px 12px;font-size:11px;color:#FFB800;letter-spacing:0.5px;">'
                f'SE&Ntilde;AL: Evaluar estrategias para equilibrar el share of voice.</div>'
                f'</div>'
            )

    # Finding 3: Unclassified sentiment
    total_sent = 0
    unclassified = 0
    for key, val in sentiment.items():
        count = val["count"] if isinstance(val, dict) else int(val)
        total_sent += count
        if key.lower() in ("sin clasificar",):
            unclassified = count
    if total_sent > 0 and unclassified > 0:
        uncl_pct = (unclassified / total_sent) * 100
        if uncl_pct > 5:
            card_idx += 1
            cards.append(
                f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);'
                f'border-top:3px solid #FFB800;border-radius:0 0 16px 16px;padding:28px;">'
                f'<div style="font-family:\'Bebas Neue\',sans-serif;font-size:48px;color:rgba(255,184,0,0.3);'
                f'line-height:1;margin-bottom:12px;">0{card_idx}</div>'
                f'<h3 style="font-size:18px;font-weight:700;color:#fff;margin-bottom:16px;line-height:1.3;">'
                f'Audiencia sin posici&oacute;n formada</h3>'
                f'<p style="color:#A0AEC0;font-size:14px;line-height:1.8;margin-bottom:12px;">'
                f'El {uncl_pct:.0f}% de menciones ({unclassified:,}) no tiene sentimiento clasificado. '
                f'Representan una audiencia potencialmente influenciable que a&uacute;n no ha tomado partido.</p>'
                f'<div style="background:rgba(255,184,0,0.1);border:1px solid rgba(255,184,0,0.2);'
                f'border-radius:6px;padding:8px 12px;font-size:11px;color:#FFB800;letter-spacing:0.5px;">'
                f'SE&Ntilde;AL: Dise&ntilde;ar contenido dirigido a la audiencia no posicionada.</div>'
                f'</div>'
            )

    if not cards:
        return ""

    # Pad to 3 columns if fewer cards
    grid_cols = min(len(cards), 3)
    return (
        f'<p class="fade-up stagger-1" style="color:#A0AEC0;font-size:15px;margin-bottom:40px;">'
        f'Se&ntilde;ales que el volumen de conversaci&oacute;n no revela a simple vista</p>'
        f'<div style="display:grid;grid-template-columns:repeat({grid_cols},1fr);gap:24px;" '
        f'class="fade-up stagger-2">'
        + "\n".join(cards[:3]) +
        f'</div>'
        f'<div class="insight-box fade-up stagger-3" style="margin-top:32px;">'
        f'<p>Estos hallazgos requieren an&aacute;lisis de patrones sobre tiempo, actores y '
        f'clusters narrativos &mdash; una capa de lectura que va m&aacute;s all&aacute; del '
        f'monitoreo de volumen est&aacute;ndar.</p></div>'
    )


# ---------------------------------------------------------------------------
# Dynamic scenario projections (replaces hardcoded Avianca scenarios)
# ---------------------------------------------------------------------------

def _build_scenarios_html(
    metrics: Dict[str, Any],
    sentiment: Dict[str, Any],
    report_type: str = "crisis",
) -> str:
    """Build scenario projection cards from actual data."""
    total_mentions = metrics.get("total_mentions", 0)

    # Calculate neg/pos ratio for dynamic text
    pos_count = 0
    neg_count = 0
    for key, val in sentiment.items():
        count = val["count"] if isinstance(val, dict) else int(val)
        k = key.lower()
        if k in ("positive", "positivo"):
            pos_count = count
        elif k in ("negative", "negativo"):
            neg_count = count

    ratio_str = ""
    if pos_count > 0:
        ratio = neg_count / pos_count
        ratio_str = f"{ratio:.1f}:1"
    else:
        ratio_str = "desfavorable"

    mentions_str = f"{total_mentions:,}" if total_mentions > 0 else "las"

    return f"""<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px;" class="fade-up stagger-2">
    <div style="background:rgba(255,27,107,0.03);border:1px solid rgba(255,27,107,0.15);border-top:3px solid #FF1B6B;border-radius:0 0 16px 16px;padding:28px;">
        <div style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:#FF1B6B;letter-spacing:2px;margin-bottom:4px;">ESCENARIO A</div>
        <div style="font-size:18px;font-weight:700;color:#fff;margin-bottom:4px;">Inacci&oacute;n</div>
        <div style="font-size:11px;color:#FF1B6B;margin-bottom:16px;">Probabilidad: Alta si no hay decisi&oacute;n esta semana</div>
        <p style="color:#A0AEC0;font-size:14px;line-height:1.8;margin-bottom:16px;">Sin intervenci&oacute;n, el ratio negativo/positivo ({ratio_str}) continuar&aacute; deterior&aacute;ndose. De las {mentions_str} menciones, la proporci&oacute;n negativa seguir&aacute; creciendo sin contrapeso.</p>
        <div style="border-top:1px solid rgba(255,27,107,0.15);padding-top:12px;font-size:13px;color:#FF1B6B;font-weight:600;">El capital reputacional se diluye sin convertirse en ventaja.</div>
    </div>
    <div style="background:rgba(255,184,0,0.03);border:1px solid rgba(255,184,0,0.15);border-top:3px solid #FFB800;border-radius:0 0 16px 16px;padding:28px;">
        <div style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:#FFB800;letter-spacing:2px;margin-bottom:4px;">ESCENARIO B</div>
        <div style="font-size:18px;font-weight:700;color:#fff;margin-bottom:4px;">Respuesta t&aacute;ctica</div>
        <div style="font-size:11px;color:#FFB800;margin-bottom:16px;">Probabilidad: Media &mdash; requiere decisi&oacute;n en 72 horas</div>
        <p style="color:#A0AEC0;font-size:14px;line-height:1.8;margin-bottom:16px;">Con contenido proactivo, el sentimiento se estabiliza en 30 d&iacute;as. La audiencia sin posici&oacute;n se divide entre narrativas y el ratio negativo/positivo deja de crecer.</p>
        <div style="border-top:1px solid rgba(255,184,0,0.15);padding-top:12px;font-size:13px;color:#FFB800;font-weight:600;">Crisis contenida. Reputaci&oacute;n estabilizada pero sin capitalizaci&oacute;n.</div>
    </div>
    <div style="background:rgba(0,212,255,0.03);border:1px solid rgba(0,212,255,0.15);border-top:3px solid #00D4FF;border-radius:0 0 16px 16px;padding:28px;">
        <div style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:#00D4FF;letter-spacing:2px;margin-bottom:4px;">ESCENARIO C</div>
        <div style="font-size:18px;font-weight:700;color:#fff;margin-bottom:4px;">Liderazgo proactivo</div>
        <div style="font-size:11px;color:#00D4FF;margin-bottom:16px;">Probabilidad: Alta si se act&uacute;a esta semana</div>
        <p style="color:#A0AEC0;font-size:14px;line-height:1.8;margin-bottom:16px;">Con estrategia integral, la crisis se convierte en oportunidad de posicionamiento. La audiencia sin posici&oacute;n migra hacia narrativa favorable en 15-20 d&iacute;as.</p>
        <div style="border-top:1px solid rgba(0,212,255,0.15);padding-top:12px;font-size:13px;color:#00D4FF;font-weight:600;">Crisis convertida en activo reputacional.</div>
    </div>
</div>
<div class="insight-box fade-up stagger-3" style="margin-top:32px;">
    <p>La diferencia entre el Escenario A y el C no es presupuesto &mdash; es velocidad de decisi&oacute;n. El capital reputacional tiene fecha de vencimiento.</p>
</div>"""


# ---------------------------------------------------------------------------
# Dynamic competitive benchmark (replaces hardcoded airline table)
# ---------------------------------------------------------------------------

def _build_competitive_benchmark_html(
    top_authors: List[List[Any]],
    client_name: str,
) -> str:
    """Build competitive benchmark table from top_authors data.

    Looks for author names that appear to be brands/companies (not the client).
    If no competitor data is found, returns empty string to hide the section.
    """
    if not top_authors:
        return ""

    client_lower = client_name.lower().strip()
    # Filter out the client, obvious non-brand entries, and entries with special chars
    competitors: List[Dict[str, Any]] = []
    for entry in top_authors:
        if len(entry) < 2:
            continue
        name = str(entry[0]).strip()
        count = int(entry[1])
        name_lower = name.lower()
        # Skip the client itself (case insensitive)
        if name_lower == client_lower or client_lower in name_lower:
            continue
        # Skip generic terms
        if name_lower in ("audiencia general", "medios", "otros", "general", "unknown", "desconocido"):
            continue
        # Skip entries with emoji or weird unicode characters
        if re.search(r'[^\w\s\-.,\u00c0-\u024f]', name):
            continue
        competitors.append({"name": name, "count": count})

    if len(competitors) < 2:
        return ""

    # Build table rows (top 6 competitors)
    rows: List[str] = []
    for comp in competitors[:6]:
        name_esc = html_mod.escape(comp["name"])
        count = comp["count"]
        border_style = 'border-bottom:1px solid rgba(255,255,255,0.04);'
        rows.append(
            f'<tr style="{border_style}">'
            f'<td style="padding:10px 12px;color:#fff;">{name_esc}</td>'
            f'<td style="padding:10px 12px;color:#A0AEC0;text-align:right;'
            f'font-family:\'JetBrains Mono\',monospace;">~{count:,}</td>'
            f'<td style="padding:10px 12px;color:#A0AEC0;">Menci&oacute;n en contexto de conversaci&oacute;n</td>'
            f'</tr>'
        )

    return (
        f'<div class="fade-up stagger-3" style="background:rgba(255,255,255,0.03);'
        f'border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:28px;margin-bottom:24px;">'
        f'<h3 style="font-family:\'Bebas Neue\',sans-serif;font-size:22px;letter-spacing:2px;'
        f'color:#fff;margin-bottom:4px;">VOCES M&Aacute;S ACTIVAS EN LA CONVERSACI&Oacute;N</h3>'
        f'<p style="font-size:13px;color:#5A6378;margin-bottom:20px;">'
        f'Otros actores presentes en la conversaci&oacute;n</p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f'<thead><tr style="border-bottom:1px solid rgba(255,27,107,0.3);">'
        f'<th style="text-align:left;padding:8px 12px;color:#FF1B6B;font-weight:600;'
        f'font-size:11px;text-transform:uppercase;letter-spacing:1px;">Nombre</th>'
        f'<th style="text-align:right;padding:8px 12px;color:#FF1B6B;font-weight:600;'
        f'font-size:11px;text-transform:uppercase;letter-spacing:1px;">Menciones</th>'
        f'<th style="text-align:left;padding:8px 12px;color:#FF1B6B;font-weight:600;'
        f'font-size:11px;text-transform:uppercase;letter-spacing:1px;">Rol en la conversaci&oacute;n</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Logo URLs
# ---------------------------------------------------------------------------
EPICAL_LOGO_URL = "https://epical.digital/wp-content/uploads/2023/08/cropped-logoEpicalwhite-152x30-1.png"


def _normalize_period(period: str) -> str:
    """Translate English month names to Spanish in period strings."""
    months = {
        "january": "enero", "february": "febrero", "march": "marzo",
        "april": "abril", "may": "mayo", "june": "junio",
        "july": "julio", "august": "agosto", "september": "septiembre",
        "october": "octubre", "november": "noviembre", "december": "diciembre",
    }
    result = period
    for en, es in months.items():
        result = re.sub(en, es, result, flags=re.IGNORECASE)
    # "to" -> "al" between dates
    result = re.sub(r'\bto\b', 'al', result)
    # Add "de" between day and month if pattern like "1 marzo"
    result = re.sub(r'(\d+)\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)', r'\1 de \2', result)
    # Add "de 2026" at the end if year is present but not prefixed with "de"
    result = re.sub(r'(\w)\s+(20\d{2})', r'\1 de \2', result)
    return result


# ---------------------------------------------------------------------------
# New helper functions for v4 layout
# ---------------------------------------------------------------------------

def _split_narrative_subsections(content: str) -> Dict[str, str]:
    """Split narrative on **Contexto**, **Dinamica**, **Implicacion**, **Senales** markers."""
    result = {"contexto": "", "dinamica": "", "implicacion": "", "senales": ""}
    if not content:
        return result

    # Split on bold markers
    parts = re.split(r'\*\*(Contexto|Din[a\u00e1]mica|Implicaci[o\u00f3]n[^*]*|Se[n\u00f1]ales[^*]*)\*\*\s*[:\uFF1A]?\s*', content)
    current_key: Optional[str] = None
    for part in parts:
        lower = part.lower().strip()
        if 'contexto' in lower:
            current_key = 'contexto'
        elif 'din' in lower and len(lower) < 40:
            current_key = 'dinamica'
        elif 'implic' in lower:
            current_key = 'implicacion'
        elif 'se\u00f1al' in lower or 'senal' in lower:
            current_key = 'senales'
        elif current_key:
            result[current_key] = _md_to_html_block(part.strip()) if part.strip() else ""

    # Fallback: if no subsections parsed, put everything in contexto
    if not any(result.values()):
        result["contexto"] = _md_to_html_block(content)

    return result


def _build_narrative_mini_chart(index: int) -> str:
    """Return inline SVG mini chart for narrative slide."""
    if index == 0:
        return (
            '<svg width="220" height="60">'
            '<text x="0" y="12" fill="#5A6378" font-size="10" font-family="IBM Plex Sans">NARRATIVA PRINCIPAL</text>'
            '<rect x="0" y="20" width="150" height="14" rx="7" fill="#00D4FF" opacity="0.8"/>'
            '<rect x="150" y="20" width="70" height="14" rx="0" ry="0" fill="#FF1B6B" opacity="0.8"/>'
            '<text x="0" y="52" fill="#A0AEC0" font-size="10">Dominante</text>'
            '<text x="160" y="52" fill="#A0AEC0" font-size="10">Secundaria</text>'
            '</svg>'
        )
    elif index == 1:
        return (
            '<svg width="220" height="60">'
            '<text x="0" y="12" fill="#5A6378" font-size="10">EVOLUCI\u00d3N</text>'
            '<rect x="0" y="20" width="73" height="14" rx="7" ry="7" fill="#FFB800" opacity="0.7"/>'
            '<rect x="73" y="20" width="73" height="14" fill="#00D4FF" opacity="0.7"/>'
            '<rect x="146" y="20" width="74" height="14" rx="7" ry="7" fill="#FF1B6B" opacity="0.7"/>'
            '<text x="10" y="52" fill="#A0AEC0" font-size="9">Fase 1</text>'
            '<text x="85" y="52" fill="#A0AEC0" font-size="9">Fase 2</text>'
            '<text x="155" y="52" fill="#A0AEC0" font-size="9">Fase 3</text>'
            '</svg>'
        )
    else:
        return (
            '<svg width="220" height="70">'
            '<text x="0" y="12" fill="#5A6378" font-size="10">ENGAGEMENT</text>'
            '<rect x="0" y="22" width="180" height="12" rx="6" fill="#FF1B6B" opacity="0.8"/>'
            '<text x="185" y="32" fill="#FF1B6B" font-size="11" font-weight="bold">Alto</text>'
            '<rect x="0" y="40" width="119" height="12" rx="6" fill="#5A6378" opacity="0.5"/>'
            '<text x="124" y="50" fill="#5A6378" font-size="11">Medio</text>'
            '</svg>'
        )


def _build_platform_matrix(normalized_sources: List[List[Any]]) -> str:
    """Build 2x2 platform cards grid HTML."""
    platform_config = {
        "tiktok": {"label": "RIESGO ALTO", "border": "#FF1B6B"},
        "instagram": {"label": "OPORTUNIDAD", "border": "#00D4FF"},
        "facebook": {"label": "BASE S\u00d3LIDA", "border": "#FFB800"},
    }
    default_config = {"label": "MONITOREAR", "border": "#5A6378"}

    cards: List[str] = []
    for source in normalized_sources[:4]:
        name = str(source[0])
        count = int(source[1])
        name_lower = name.lower()

        config = default_config
        for key, cfg in platform_config.items():
            if key in name_lower:
                config = cfg
                break

        # Generic strategy lines based on platform type
        strategy_lines: List[str] = []
        if "tiktok" in name_lower:
            strategy_lines = ["Audiencia joven dominante", "Mayor viralidad potencial"]
        elif "instagram" in name_lower:
            strategy_lines = ["Espacio visual clave", "Potencial de crecimiento"]
        elif "facebook" in name_lower:
            strategy_lines = ["Base institucional consolidada", "Comunidad org\u00e1nica activa"]
        elif "twitter" in name_lower:
            strategy_lines = ["Formadores de opini\u00f3n", "Ciclo de noticias r\u00e1pido"]
        elif "youtube" in name_lower:
            strategy_lines = ["Contenido de larga duraci\u00f3n", "B\u00fasqueda org\u00e1nica"]
        else:
            strategy_lines = ["Canal complementario", "Monitoreo recomendado"]

        bullet_html = f'<li>{count:,} menciones</li>'
        for sl in strategy_lines:
            bullet_html += f'<li>{html_mod.escape(sl)}</li>'

        cards.append(
            f'<div class="platform-card" style="border-top:4px solid {config["border"]};">'
            f'<div class="platform-name">{html_mod.escape(name)}</div>'
            f'<div class="platform-quadrant" style="color:{config["border"]};">{config["label"]}</div>'
            f'<ul class="platform-bullets">{bullet_html}</ul>'
            f'</div>'
        )

    return "\n".join(cards)


def _build_compressed_recommendations(recomendaciones: List[Dict[str, str]]) -> str:
    """Build compressed recommendation cards extracting key info only."""
    if not recomendaciones:
        return ""

    seen_titles: set = set()
    cards: List[str] = []
    idx = 0
    for rec in recomendaciones:
        title = rec.get("title", "Recomendaci\u00f3n")
        # Strip markdown bold markers from title
        title = re.sub(r'\*\*(.+?)\*\*', r'\1', title)
        title = title.strip('*').strip()
        title_key = _normalise_header(title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        idx += 1
        num = f"{idx:02d}"
        title_esc = html_mod.escape(title)
        content = rec.get("content", "")

        # Extract fundamento: first 2 sentences after **Fundamento**
        fundamento = ""
        fund_match = re.search(
            r'\*\*Fundamento\*\*\s*[:\uFF1A\-\u2014]?\s*(.*?)(?=\*\*(?:Implementaci|M[e\u00e9]trica)|$)',
            content, re.DOTALL | re.IGNORECASE
        )
        if fund_match:
            fund_text = fund_match.group(1).strip()
            fund_sentences = re.split(r'(?<=[.!?])\s+', fund_text)
            fund_sentences = [s.strip() for s in fund_sentences if s.strip()]
            fundamento = " ".join(fund_sentences[:2])
        else:
            # Fallback: first 2 sentences of content
            sentences = re.split(r'(?<=[.!?])\s+', content)
            sentences = [s.strip() for s in sentences if s.strip()]
            fundamento = " ".join(sentences[:2])

        # Extract metrica: first sentence after **Metrica**
        metrica = ""
        met_match = re.search(
            r'\*\*M[e\u00e9]trica[^*]*\*\*\s*[:\uFF1A\-\u2014]?\s*(.*?)(?=\*\*|$)',
            content, re.DOTALL | re.IGNORECASE
        )
        if met_match:
            met_text = met_match.group(1).strip()
            met_sentences = re.split(r'(?<=[.!?])\s+', met_text)
            metrica = met_sentences[0].strip() if met_sentences else ""

        fundamento_html = _inline_format(fundamento) if fundamento else ""
        metrica_html = _inline_format(metrica) if metrica else ""

        metrica_block = ""
        if metrica_html:
            metrica_block = (
                f'<div class="rec-metrica">'
                f'<span class="rec-metrica-label">M\u00c9TRICA</span> '
                f'{metrica_html}'
                f'</div>'
            )

        cards.append(
            f'<div class="rec-card">'
            f'<div class="rec-number font-mono">{num}</div>'
            f'<div class="rec-body">'
            f'<h4>{title_esc}</h4>'
            f'<p class="rec-fundamento">{fundamento_html}</p>'
            f'{metrica_block}'
            f'</div></div>'
        )

        if idx >= 3:
            break

    return "\n".join(cards)


# ---------------------------------------------------------------------------
# HTML builders for sections
# ---------------------------------------------------------------------------

def _build_kpi_cards(
    total_mentions: int,
    pos_pct: float,
    neg_pct: float,
    avg_reach: Optional[float],
    avg_engagement: Optional[float],
    total_likes: int,
    total_comments: int,
    total_shares: int,
    actor_breakdown: Dict[str, Any],
) -> str:
    """Build KPI card grid HTML."""
    cards: List[str] = []

    cards.append(
        '<div class="kpi-card">'
        '<div class="kpi-label">Total Menciones</div>'
        f'<div class="kpi-value white countup font-mono" '
        f'data-target="{total_mentions}" data-commas="true">'
        f'{total_mentions:,}</div>'
        '</div>'
    )

    cards.append(
        '<div class="kpi-card">'
        '<div class="kpi-label">Sentimiento Positivo</div>'
        f'<div class="kpi-value cyan countup font-mono" '
        f'data-target="{pos_pct}" data-suffix="%" data-decimals="1">'
        f'{pos_pct}%</div>'
        '</div>'
    )

    cards.append(
        '<div class="kpi-card">'
        '<div class="kpi-label">Sentimiento Negativo</div>'
        f'<div class="kpi-value magenta countup font-mono" '
        f'data-target="{neg_pct}" data-suffix="%" data-decimals="1">'
        f'{neg_pct}%</div>'
        '</div>'
    )

    if avg_reach is not None:
        cards.append(
            '<div class="kpi-card">'
            '<div class="kpi-label">Alcance Promedio</div>'
            f'<div class="kpi-value white countup font-mono" '
            f'data-target="{avg_reach}" data-commas="true">'
            f'{avg_reach:,.0f}</div>'
            '</div>'
        )

    if avg_engagement is not None:
        cards.append(
            '<div class="kpi-card">'
            '<div class="kpi-label">Engagement Promedio</div>'
            f'<div class="kpi-value white countup font-mono" '
            f'data-target="{avg_engagement}" data-suffix="" data-decimals="1">'
            f'{avg_engagement:,.1f}</div>'
            '</div>'
        )

    cards.append(
        '<div class="kpi-card">'
        '<div class="kpi-label">Total Likes</div>'
        f'<div class="kpi-value gold countup font-mono" '
        f'data-target="{total_likes}" data-commas="true">'
        f'{total_likes:,}</div>'
        '</div>'
    )

    if actor_breakdown:
        total = sum(actor_breakdown.values()) or 1
        actor_colors = ["#FF1B6B", "#00D4FF", "#FFB800", "#8B5CF6", "#5A6378"]
        bar_segments = ""
        legend_items = ""
        for i, (actor, count) in enumerate(actor_breakdown.items()):
            pct = (count / total) * 100
            color = actor_colors[i % len(actor_colors)]
            bar_segments += (
                f'<div class="actor-bar-segment" '
                f'style="width:{pct:.1f}%;background:{color};"></div>'
            )
            legend_items += (
                f'<span><span class="actor-legend-dot" '
                f'style="background:{color};"></span>'
                f'{html_mod.escape(str(actor).capitalize())} '
                f'<span class="font-mono" style="color:#5A6378;">{pct:.0f}%</span></span>'
            )
        cards.append(
            '<div class="kpi-card" style="grid-column: span 1;">'
            '<div class="kpi-label">Distribuci\u00f3n de Actores</div>'
            '<div class="actor-bar-container">'
            f'<div class="actor-bar">{bar_segments}</div>'
            f'<div class="actor-legend">{legend_items}</div>'
            '</div></div>'
        )

    return "\n".join(cards)


def _build_narrative_slide(narr: Dict[str, str], index: int) -> str:
    """Build a full-viewport narrative slide with mini chart."""
    title = html_mod.escape(narr.get("title", ""))
    content = narr.get("content", "")
    subs = _split_narrative_subsections(content)
    mini_chart_svg = _build_narrative_mini_chart(index)
    num = f"0{index + 1}"

    left_col = ""
    if subs["contexto"]:
        left_col += (
            '<div class="subsection-label">CONTEXTO</div>'
            f'<div class="subsection-text">{subs["contexto"]}</div>'
        )
    if subs["dinamica"]:
        left_col += (
            '<div class="subsection-label">DIN\u00c1MICA</div>'
            f'<div class="subsection-text">{subs["dinamica"]}</div>'
        )

    right_col = ""
    if subs["implicacion"]:
        right_col += (
            '<div class="subsection-label">IMPLICACI\u00d3N PARA EL NEGOCIO</div>'
            f'<div class="subsection-text">{subs["implicacion"]}</div>'
        )
    if subs["senales"]:
        right_col += (
            '<div class="subsection-label">SE\u00d1ALES A MONITOREAR</div>'
            f'<div class="subsection-text">{subs["senales"]}</div>'
        )

    # Fallback: if no subsections parsed, put all content in left col
    if not left_col and not right_col:
        fallback_html = _md_to_html_block(content)
        left_col = f'<div class="subsection-text">{fallback_html}</div>'

    return (
        f'<div class="section-inner" style="position:relative;">'
        f'<div class="narrative-mini-chart">{mini_chart_svg}</div>'
        f'<div class="narrative-bg-number">{num}</div>'
        f'<h2 class="narrative-slide-title fade-up">{title}</h2>'
        f'<div class="narrative-two-col fade-up stagger-2">'
        f'<div class="narrative-col-left">{left_col}</div>'
        f'<div class="narrative-col-right">{right_col}</div>'
        f'</div>'
        f'</div>'
    )


def _build_anomaly_cards(anomalies: List[Dict[str, Any]]) -> str:
    """Build anomaly alert cards HTML."""
    if not anomalies:
        return ""

    cards: List[str] = []
    for a in anomalies:
        severity = a.get("severity", "info")
        sev_class = severity if severity in ("critical", "warning", "info") else "info"
        desc = html_mod.escape(a.get("description", ""))
        atype = html_mod.escape(a.get("type", ""))
        type_html = ""
        if atype:
            type_html = (
                '<div style="color:#5A6378;font-size:11px;letter-spacing:1px;'
                f'text-transform:uppercase;margin-bottom:8px;">{atype}</div>'
            )
        cards.append(
            f'<div class="anomaly-card {sev_class}">'
            f'<span class="severity-badge {sev_class}">{severity.upper()}</span>'
            f'{type_html}'
            f'<div class="anomaly-desc">{desc}</div>'
            f'</div>'
        )
    return "\n".join(cards)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def _build_theme_css(is_light: bool, brand_color: str = "#FF1B6B") -> str:
    """Return CSS custom properties and overrides for the selected theme."""
    if not is_light:
        # Dark theme (default) -- all existing styles apply, just set variables
        return """
:root {
    --bg-primary: #050D1A;
    --bg-secondary: #0A1628;
    --bg-card: rgba(255,255,255,0.03);
    --border-color: rgba(255,255,255,0.06);
    --text-primary: #FFFFFF;
    --text-secondary: #A0AEC0;
    --text-muted: #5A6378;
    --accent-primary: #FF1B6B;
    --accent-secondary: #00D4FF;
    --accent-gold: #FFB800;
    --shadow: none;
    --chart-text: #A0AEC0;
    --chart-grid: rgba(255,255,255,0.04);
}
"""
    # Light theme
    return f"""
:root {{
    --bg-primary: #FFFFFF;
    --bg-secondary: #F5F5F5;
    --bg-card: #FFFFFF;
    --border-color: #E0E0E0;
    --text-primary: #1A1A1A;
    --text-secondary: #666666;
    --text-muted: #999999;
    --accent-primary: {brand_color};
    --accent-secondary: #333333;
    --accent-gold: #C8A84B;
    --shadow: 0 2px 12px rgba(0,0,0,0.08);
    --chart-text: #666666;
    --chart-grid: rgba(0,0,0,0.06);
}}
body {{
    background: var(--bg-primary) !important;
    color: var(--text-secondary) !important;
}}
html {{
    scroll-snap-type: none !important;
    scroll-behavior: smooth;
}}
.section {{
    min-height: auto !important;
    scroll-snap-align: none !important;
    padding: 60px 48px !important;
    border-bottom: 1px solid var(--border-color);
}}
/* Cover */
.cover {{
    background: var(--bg-secondary) !important;
    min-height: 80vh !important;
}}
.cover-orb {{ display: none !important; }}
.cover-client,
.cover h1 {{
    color: var(--text-primary) !important;
    -webkit-text-fill-color: var(--text-primary) !important;
    background: none !important;
}}
.cover-subtitle, .cover p {{
    color: var(--text-secondary) !important;
}}
.cover-period {{
    color: var(--text-muted) !important;
}}
.cover-line {{
    background: var(--accent-primary) !important;
    width: 80px !important;
}}
.cover-wordmark span {{
    color: var(--text-muted) !important;
}}
/* Section titles */
.section-title {{
    color: var(--text-primary) !important;
}}
.section-title::after {{
    background: var(--accent-primary) !important;
}}
/* Cards */
.kpi-card, .chart-wrapper, .d3-card, .narrative-card,
.anomaly-card, .rec-card, .executive-card, .platform-card {{
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    box-shadow: var(--shadow) !important;
}}
.kpi-card:hover {{
    border-color: var(--accent-primary) !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1) !important;
}}
/* KPI values */
.kpi-value.white {{ color: var(--text-primary) !important; }}
.kpi-value.cyan {{ color: var(--accent-primary) !important; }}
.kpi-value.magenta {{ color: var(--accent-primary) !important; }}
.kpi-label {{ color: var(--text-muted) !important; }}
/* Narrative cards */
.narrative-card {{
    border-left-color: var(--accent-primary) !important;
    border-radius: 0 8px 8px 0 !important;
}}
.narrative-card:hover {{
    box-shadow: 0 4px 20px rgba(0,0,0,0.1) !important;
}}
.narrative-body h3 {{ color: var(--text-primary) !important; }}
.narrative-body p, .narrative-body li {{ color: var(--text-secondary) !important; }}
.narrative-bg-number {{ color: rgba(0,0,0,0.05) !important; }}
.narrative-slide-title {{ color: var(--text-primary) !important; }}
.subsection-label {{ color: var(--accent-primary) !important; }}
.subsection-text, .subsection-text p {{ color: var(--text-secondary) !important; }}
/* Insight boxes */
.insight-box {{
    background: rgba(0,0,0,0.02) !important;
    border-left-color: var(--accent-primary) !important;
}}
.insight-box p {{ color: var(--text-primary) !important; }}
/* Editorial questions */
.editorial-question {{ color: var(--accent-primary) !important; }}
/* Transitions */
.transition-section {{
    background: var(--accent-primary) !important;
    min-height: 40vh !important;
}}
.transition-quote {{ color: #FFFFFF !important; font-size: clamp(20px, 3vw, 36px) !important; }}
.transition-bg .blob {{ display: none !important; }}
/* Anomaly cards */
.anomaly-card.critical {{ background: rgba(255,0,0,0.03) !important; }}
.anomaly-card.warning {{ background: rgba(255,180,0,0.03) !important; }}
.anomaly-desc {{ color: var(--text-secondary) !important; }}
/* Rec cards */
.rec-body h4 {{ color: var(--text-primary) !important; }}
.rec-body p {{ color: var(--text-secondary) !important; }}
.draft-badge {{
    background: rgba(200,0,0,0.08) !important;
    border-color: rgba(200,0,0,0.2) !important;
    color: #CC0000 !important;
}}
/* Methodology */
.methodology {{
    background: var(--bg-secondary) !important;
    border-top-color: var(--border-color) !important;
}}
.methodology .brand {{ color: var(--accent-primary) !important; }}
.methodology .tagline {{ color: var(--text-secondary) !important; }}
.methodology .stats {{ color: var(--text-muted) !important; }}
.methodology p {{ color: var(--text-muted) !important; }}
.methodology .confidential {{ color: var(--text-muted) !important; border-top-color: var(--border-color) !important; }}
/* Nav dots */
.nav-dot {{
    border-color: rgba(0,0,0,0.2) !important;
}}
.nav-dot.active {{
    background: var(--accent-primary) !important;
    border-color: var(--accent-primary) !important;
}}
.nav-dot::before {{
    background: rgba(0,0,0,0.8) !important;
    color: #fff !important;
}}
/* Tables */
th {{ color: var(--accent-primary) !important; }}
td {{ color: var(--text-secondary) !important; }}
/* Chart defaults override in JS */
/* Force graph */
.force-legend {{ color: var(--text-secondary) !important; }}
/* Spike explorer */
.spike-btn {{
    border-color: var(--border-color) !important;
    color: var(--text-secondary) !important;
    background: var(--bg-card) !important;
}}
.spike-btn.active {{
    border-color: var(--accent-primary) !important;
    background: var(--accent-primary) !important;
    color: #fff !important;
}}
.spike-panel {{
    background: var(--bg-card) !important;
    border-color: var(--border-color) !important;
}}
/* Platform cards */
.platform-card {{ box-shadow: var(--shadow) !important; }}
/* Word cloud text */
/* D3 tooltip */
.d3-tooltip {{
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-color) !important;
}}
"""


def _encode_logo(logo_path: Union[str, Path]) -> Optional[str]:
    """Read an image file and return a base64 data URI string."""
    logo_path = Path(logo_path)
    if not logo_path.exists():
        logger.warning("Logo file not found: %s", logo_path)
        return None
    mime, _ = mimetypes.guess_type(str(logo_path))
    if mime is None:
        ext = logo_path.suffix.lower()
        mime_map = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/png")
    try:
        raw = logo_path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.error("Failed to encode logo %s: %s", logo_path, e)
        return None


def build_report_html(
    client_name: str,
    period: str,
    report_text: str,
    metrics: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    output_path: Union[str, Path],
    logo_path: Optional[Union[str, Path]] = None,
    theme: str = "dark",
    brand_color: str = "#FF1B6B",
    report_type: str = "crisis",
) -> Path:
    """Create a self-contained HTML visual report.

    Args:
        client_name: Client name for the header.
        period: Reporting period description.
        report_text: The Claude-generated narrative text (markdown).
        metrics: Calculated metrics dictionary.
        anomalies: List of anomaly dictionaries.
        output_path: Destination file path.
        logo_path: Optional path to a client logo image (PNG/SVG/JPG).
        theme: "dark" or "light".
        brand_color: Client brand color for light theme accent.
        report_type: Report type — "crisis" hides some sections.

    Returns:
        Path to the generated .html file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Section visibility flags based on report_type
    show_wordcloud = report_type != "crisis"
    show_heatmap = report_type != "crisis"
    show_bubbles = report_type != "crisis"
    show_transitions = report_type != "crisis"
    show_hallazgos = report_type != "crisis"

    generated_date = datetime.now().strftime("%d/%m/%Y %H:%M")
    year = datetime.now().year

    # Encode client logo if provided
    cover_logo_data_uri = _encode_logo(logo_path) if logo_path else None

    # Theme configuration
    is_light = theme.lower() == "light"
    theme_css = _build_theme_css(is_light, brand_color)

    # ------------------------------------------------------------------
    # Parse report text
    # ------------------------------------------------------------------
    sections = _parse_report_sections(report_text or "")

    # ------------------------------------------------------------------
    # Extract & fix metrics
    # ------------------------------------------------------------------
    total_mentions = metrics.get("total_mentions", 0)
    sentiment = _fix_sentiment_labels(metrics.get("sentiment_breakdown", {}))
    volume_by_date = metrics.get("volume_by_date", {})
    top_sources_raw = metrics.get("top_sources", [])
    top_sources = _normalize_platforms(top_sources_raw)
    top_authors = metrics.get("top_authors", [])
    actor_breakdown = metrics.get("actor_breakdown", {})
    avg_reach = metrics.get("avg_reach")
    avg_engagement = metrics.get("avg_engagement")
    total_likes = metrics.get("total_likes", 0)
    total_comments = metrics.get("total_comments", 0)
    total_shares = metrics.get("total_shares", 0)
    topic_clusters = metrics.get("topic_clusters", [])

    # Sentiment percentages
    pos_pct = 0.0
    neg_pct = 0.0
    for key, val in sentiment.items():
        pct = val["percentage"] if isinstance(val, dict) else 0
        if key in ("positive", "positivo"):
            pos_pct = pct
        elif key in ("negative", "negativo"):
            neg_pct = pct

    # Chart data as JSON
    volume_labels_json = json.dumps(list(volume_by_date.keys()))
    volume_data_json = json.dumps(list(volume_by_date.values()))

    # Sentiment -- use fixed labels
    sentiment_labels_json = json.dumps(list(sentiment.keys()))
    sentiment_counts_json = json.dumps(
        [v["count"] if isinstance(v, dict) else v for v in sentiment.values()]
    )

    sentiment_color_map = {
        "positive": "#00D4FF", "positivo": "#00D4FF",
        "negative": "#FF1B6B", "negativo": "#FF1B6B",
        "neutral": "#5A6378", "neutro": "#5A6378",
        "mixed": "#FFB800", "mixto": "#FFB800",
        "sin clasificar": "#3D4663",
    }
    sentiment_colors_json = json.dumps(
        [sentiment_color_map.get(k.lower(), "#5A6378") for k in sentiment.keys()]
    )

    source_labels_json = json.dumps([s[0] for s in top_sources[:8]])
    source_data_json = json.dumps([s[1] for s in top_sources[:8]])

    # Anomaly dates for chart annotations
    anomaly_dates: List[str] = []
    anomaly_severity_map: Dict[str, str] = {}
    for a in anomalies:
        data = a.get("data", {})
        if isinstance(data, dict):
            d = data.get("date") or data.get("fecha")
            if d:
                anomaly_dates.append(str(d))
                anomaly_severity_map[str(d)] = a.get("severity", "info")
    anomaly_dates_json = json.dumps(anomaly_dates)
    anomaly_severity_json = json.dumps(anomaly_severity_map)

    # Actor breakdown for stacked bar
    actor_breakdown_json = json.dumps(actor_breakdown)

    # Topic clusters as JSON for D3 visualizations
    topic_clusters_json = json.dumps(topic_clusters)

    # Intersection metrics for Venn diagram
    intersection_data = metrics.get("intersection", {})
    intersection_json = json.dumps(intersection_data)

    # Top authors JSON for actor graph
    top_authors_json = json.dumps(top_authors[:20])

    # Full normalized sources JSON for bubble chart
    normalized_sources_json = json.dumps(top_sources[:12])

    # ------------------------------------------------------------------
    # Build section HTML
    # ------------------------------------------------------------------

    kpi_cards_html = _build_kpi_cards(
        total_mentions, pos_pct, neg_pct,
        avg_reach, avg_engagement,
        total_likes, total_comments, total_shares,
        actor_breakdown,
    )

    # Narrative slides (up to 3)
    narrativas = sections.get("narrativas", [])
    narrative_slides_html: List[str] = []
    for i, narr in enumerate(narrativas[:3]):
        narrative_slides_html.append(_build_narrative_slide(narr, i))

    # Anomaly cards
    anomaly_cards_html = _build_anomaly_cards(anomalies)

    # Compressed recommendations
    recommendation_cards_html = _build_compressed_recommendations(
        sections.get("recomendaciones", [])
    )

    # Platform matrix
    platform_matrix_html = _build_platform_matrix(top_sources)

    # Methodology
    methodology_html = _md_to_html_block(sections.get("metodologia", ""))
    hook_text = html_mod.escape(sections.get("hook", "Lo que revelan los datos."))

    client_escaped = html_mod.escape(client_name)
    period_escaped = html_mod.escape(_normalize_period(period))

    # Build narrative section HTML fragments
    narr_section_0 = narrative_slides_html[0] if len(narrative_slides_html) > 0 else ""
    narr_section_1 = narrative_slides_html[1] if len(narrative_slides_html) > 1 else ""
    narr_section_2 = narrative_slides_html[2] if len(narrative_slides_html) > 2 else ""

    # Executive summary cards (dynamic from report text)
    exec_cards_data = _build_exec_cards_from_report(
        sections.get("resumen_ejecutivo", ""),
        client_name,
    )
    exec_cards_html = ""
    css_classes = ["exec-card-paso", "exec-card-juego", "exec-card-viene"]
    for i, card in enumerate(exec_cards_data):
        css_class = css_classes[i] if i < len(css_classes) else ""
        exec_cards_html += (
            f'<div class="exec-card {css_class}">'
            f'<h3>{html_mod.escape(card["title"])}</h3>'
            f'<p>{html_mod.escape(card["text"])}</p>'
            f'</div>'
        )

    # Dynamic insight texts
    insights = _generate_insights_from_data(metrics, anomalies, actor_breakdown)
    insight_kpi = html_mod.escape(insights["insight_kpi"])
    insight_volume = html_mod.escape(insights["insight_volume"])
    insight_timeline = html_mod.escape(insights["insight_timeline"])
    insight_sentiment = html_mod.escape(insights["insight_sentiment"])
    insight_heatmap = html_mod.escape(insights["insight_heatmap"])
    insight_actor_graph = html_mod.escape(insights["insight_actor_graph"])
    insight_wordcloud = html_mod.escape(insights["insight_wordcloud"])
    insight_platforms = html_mod.escape(insights["insight_platforms"])
    insight_recommendations = html_mod.escape(insights["insight_recommendations"])

    # Dynamic spike explorer
    spike_buttons_html = _build_spike_buttons_html(anomalies)
    spike_js_data = _build_spike_js_data(anomalies)
    has_spikes = bool(spike_buttons_html)

    # Dynamic findings
    findings_html = _build_findings_html(
        sections, actor_breakdown, sentiment, top_authors, client_name,
    )
    has_findings = bool(findings_html)

    # Dynamic scenario projections
    scenarios_html = _build_scenarios_html(metrics, sentiment)

    # Dynamic competitive benchmark
    competitive_benchmark_html = _build_competitive_benchmark_html(top_authors, client_name)

    # Build actor legend dynamically from actor_breakdown
    actor_legend_items = ""
    actor_colors_list = ["#FF1B6B", "#00D4FF", "#5A6378", "#FFB800", "#8B5CF6"]
    sorted_actors_for_legend = sorted(actor_breakdown.items(), key=lambda x: x[1], reverse=True)
    for i, (actor_name, _) in enumerate(sorted_actors_for_legend[:3]):
        color = actor_colors_list[i] if i < len(actor_colors_list) else "#5A6378"
        actor_esc = html_mod.escape(str(actor_name).capitalize())
        actor_legend_items += (
            f'<div class="force-legend-item">'
            f'<div class="force-legend-dot" style="background:{color};"></div>'
            f'{actor_esc}</div>'
        )
    if not actor_legend_items:
        actor_legend_items = '<div class="force-legend-item"><div class="force-legend-dot" style="background:#5A6378;"></div>Sin datos de actores</div>'

    # Build actors monitored badges dynamically
    actor_badges_html = ""
    badge_colors = [
        ("rgba(0,212,255,0.1)", "rgba(0,212,255,0.2)", "#00D4FF"),
        ("rgba(255,27,107,0.1)", "rgba(255,27,107,0.2)", "#FF1B6B"),
        ("rgba(255,255,255,0.05)", "rgba(255,255,255,0.1)", "#A0AEC0"),
        ("rgba(255,184,0,0.1)", "rgba(255,184,0,0.2)", "#FFB800"),
    ]
    for i, (actor_name, _) in enumerate(sorted_actors_for_legend[:6]):
        bg, border, fg = badge_colors[i % len(badge_colors)]
        actor_esc = html_mod.escape(str(actor_name).capitalize())
        actor_badges_html += (
            f'<span style="background:{bg};border:1px solid {border};'
            f'color:{fg};padding:4px 12px;border-radius:6px;font-size:12px;">'
            f'{actor_esc}</span>'
        )
    if not actor_badges_html:
        actor_badges_html = f'<span style="background:rgba(0,212,255,0.1);border:1px solid rgba(0,212,255,0.2);color:#00D4FF;padding:4px 12px;border-radius:6px;font-size:12px;">{client_escaped}</span>'

    # Build platform badges dynamically
    platform_badge_colors = [
        ("rgba(0,212,255,0.1)", "rgba(0,212,255,0.2)", "#00D4FF"),
        ("rgba(255,27,107,0.1)", "rgba(255,27,107,0.2)", "#FF1B6B"),
        ("rgba(255,184,0,0.1)", "rgba(255,184,0,0.2)", "#FFB800"),
        ("rgba(255,255,255,0.05)", "rgba(255,255,255,0.1)", "#A0AEC0"),
    ]
    platform_badges_html = ""
    for i, src in enumerate(top_sources[:5]):
        bg, border, fg = platform_badge_colors[i % len(platform_badge_colors)]
        platform_badges_html += (
            f'<span style="background:{bg};border:1px solid {border};'
            f'color:{fg};padding:4px 12px;border-radius:6px;font-size:12px;">'
            f'{html_mod.escape(str(src[0]))}</span>'
        )
    if not platform_badges_html:
        platform_badges_html = '<span style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:#A0AEC0;padding:4px 12px;border-radius:6px;font-size:12px;">Sin datos de plataformas</span>'

    # Calculate days covered
    days_covered = len(volume_by_date) if volume_by_date else 0

    # Build Venn diagram labels dynamically (exclude "otros" from venn labels)
    venn_actors = [(a, c) for a, c in sorted_actors_for_legend if str(a).lower() != "otros"]
    venn_label_left = "Solo marca"
    venn_label_right = "Solo actor"
    if venn_actors:
        if len(venn_actors) >= 2:
            # Find which is the client vs other
            venn_label_left = str(venn_actors[1][0]).capitalize()
            venn_label_right = str(venn_actors[0][0]).capitalize()
        else:
            venn_label_left = client_escaped
            venn_label_right = str(venn_actors[0][0]).capitalize()

    # Transition quote (dynamic)
    if venn_actors and len(venn_actors) >= 2:
        actor1 = str(venn_actors[0][0]).capitalize()
        actor2 = str(venn_actors[1][0]).capitalize()
        transition_battle_quote = f"Los actores principales operan en ecosistemas digitales distintos. Son conversaciones paralelas que casi no se intersectan."
    else:
        transition_battle_quote = "La conversaci&oacute;n digital revela patrones que no son evidentes a simple vista."

    # ------------------------------------------------------------------
    # Build dynamic nav dots based on visible sections
    # ------------------------------------------------------------------
    show_actor_graph = bool(actor_breakdown)
    nav_sections: List[Tuple[str, bool]] = [
        ("Cover", True),
        ("Marco", True),
        ("Lo que necesit\u00e1s saber", True),
        ("Impacto", True),
        ("Cronolog\u00eda", True),
        ("Sentimiento", True),
        ("Red de actores", report_type != "crisis" or show_actor_graph),
        ("Narrativa 01", len(narrativas) > 0),
        ("Narrativa 02", len(narrativas) > 1),
        ("Narrativa 03", len(narrativas) > 2),
        ("Escenarios", report_type == "crisis"),
        ("Audiencias", True),
        ("Decisiones", True),
        ("Metodolog\u00eda", True),
    ]
    nav_dots_html = ""
    dot_idx = 0
    for nav_title, visible in nav_sections:
        if not visible:
            continue
        active = " active" if dot_idx == 0 else ""
        title_esc = html_mod.escape(nav_title)
        nav_dots_html += f'    <button class="nav-dot{active}" data-index="{dot_idx}" title="{title_esc}"></button>\n'
        dot_idx += 1

    # ------------------------------------------------------------------
    # Pre-build conditional section HTML (avoids backslash in f-string expr on 3.9)
    # ------------------------------------------------------------------
    _sec7_transition = (
        '<!-- SEC-7: TRANSITION -->\n'
        '<section class="section transition-section" id="sec-7">\n'
        '    <div class="transition-bg">\n'
        '        <div class="blob blob-magenta"></div>\n'
        '        <div class="blob blob-cyan"></div>\n'
        '    </div>\n'
        f'    <p class="transition-quote fade-up">{transition_battle_quote}</p>\n'
        '</section>'
    ) if show_transitions else ''

    _sec8_heatmap = (
        '<!-- SEC-8: HEATMAP -->\n'
        '<section class="section" id="sec-8">\n'
        '    <div class="section-inner">\n'
        '        <div class="editorial-question fade-up">&iquest;QUI\u00c9N CONTROLA QU\u00c9 PARTE DE LA CONVERSACI\u00d3N?</div>\n'
        '        <h2 class="section-title fade-up stagger-1">EL MAPA DE CALOR</h2>\n'
        '        <div class="d3-card fade-up stagger-2" style="margin-bottom:24px;">\n'
        '            <div id="narrativeHeatmap"></div>\n'
        '            <div class="heatmap-legend" style="justify-content:center;">\n'
        '                <span>Menor</span>\n'
        '                <div class="heatmap-legend-bar"></div>\n'
        '                <span>Mayor</span>\n'
        '            </div>\n'
        '        </div>\n'
        '        <div class="insight-box fade-up stagger-3">\n'
        f'            <p>{insight_heatmap}</p>\n'
        '        </div>\n'
        '    </div>\n'
        '</section>'
    ) if show_heatmap else ''

    _sec10_wordcloud = (
        '<!-- SEC-10: WORD CLOUD -->\n'
        '<section class="section" id="sec-10">\n'
        '    <div class="section-inner">\n'
        '        <div class="editorial-question fade-up">&iquest;QU\u00c9 PALABRAS DEFINIERON LA CONVERSACI\u00d3N?</div>\n'
        '        <h2 class="section-title fade-up stagger-1">EL LENGUAJE</h2>\n'
        '        <div class="d3-card fade-up stagger-2">\n'
        '            <div class="wordcloud-container" id="wordCloud"></div>\n'
        '        </div>\n'
        '        <div class="insight-box fade-up stagger-3">\n'
        f'            <p>{insight_wordcloud}</p>\n'
        '        </div>\n'
        '    </div>\n'
        '</section>'
    ) if show_wordcloud else ''

    _sec10b_findings = ''
    if has_findings and show_hallazgos:
        _sec10b_findings = (
            '<section class="section" id="sec-10b" style="justify-content: flex-start; padding-top: 80px;">\n'
            '    <div class="section-inner">\n'
            '        <div class="editorial-question fade-up">&iquest;QU&Eacute; SE&Ntilde;ALES QUEDARON SIN DETECTAR?</div>\n'
            '        <h2 class="section-title fade-up stagger-1">HALLAZGOS QUE MERECEN ATENCI&Oacute;N</h2>\n'
            f'        {findings_html}\n'
            '    </div>\n'
            '</section>'
        )

    _sec11_transition = (
        '<!-- SEC-11: TRANSITION - NARRATIVAS -->\n'
        '<section class="section transition-section" id="sec-11">\n'
        '    <div class="transition-bg">\n'
        '        <div class="blob blob-magenta"></div>\n'
        '        <div class="blob blob-cyan"></div>\n'
        '    </div>\n'
        '    <p class="transition-quote fade-up">Las narrativas que definieron esta conversaci&oacute;n &mdash; y lo que significan para el futuro.</p>\n'
        '</section>'
    ) if show_transitions else ''

    _sec15_transition = (
        '<!-- SEC-15: TRANSITION - PLATAFORMAS -->\n'
        '<section class="section transition-section" id="sec-15">\n'
        '    <div class="transition-bg">\n'
        '        <div class="blob blob-magenta"></div>\n'
        '        <div class="blob blob-cyan"></div>\n'
        '    </div>\n'
        '    <p class="transition-quote fade-up">Las plataformas son campos de batalla con reglas diferentes.</p>\n'
        '</section>'
    ) if show_transitions else ''

    _bubbles_html = (
        '<!-- Bubble Chart -->\n'
        '        <div class="d3-card fade-up stagger-4">\n'
        '            <h3 style="font-family:\'Bebas Neue\',sans-serif;font-size:22px;letter-spacing:2px;'
        'color:#fff;margin-bottom:20px;text-align:center;">AUDIENCIAS POR PLATAFORMA</h3>\n'
        '            <div id="platformBubbles"></div>\n'
        '        </div>'
    ) if show_bubbles else ''

    _sec17_transition = (
        '<!-- SEC-17: TRANSITION - DECISIONES -->\n'
        '<section class="section transition-section" id="sec-17">\n'
        '    <div class="transition-bg">\n'
        '        <div class="blob blob-magenta"></div>\n'
        '        <div class="blob blob-cyan"></div>\n'
        '    </div>\n'
        '    <p class="transition-quote fade-up">Tres decisiones que no pueden esperar.</p>\n'
        '</section>'
    ) if show_transitions else ''

    # ------------------------------------------------------------------
    # Assemble full HTML
    # ------------------------------------------------------------------
    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{client_escaped} &mdash; Informe de Inteligencia Social</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
<style>
/* ===== THEME VARIABLES ===== */
{theme_css}
/* ===== RESET & BASE ===== */
*, *::before, *::after {{
    margin: 0; padding: 0; box-sizing: border-box;
}}
html {{
    scroll-snap-type: y mandatory;
    scroll-behavior: smooth;
    overflow-y: scroll;
}}
body {{
    font-family: 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
    background: #050D1A;
    color: #A0AEC0;
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
}}

/* ===== SECTION SNAP ===== */
.section {{
    min-height: 100vh;
    scroll-snap-align: start;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 80px 48px;
    overflow: hidden;
}}
.section.auto-height {{
    min-height: auto;
    scroll-snap-align: start;
}}
.section-inner {{
    max-width: 1200px;
    width: 100%;
    margin: 0 auto;
}}

/* ===== TYPOGRAPHY ===== */
.font-header {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #FFFFFF;
}}
.font-mono {{
    font-family: 'JetBrains Mono', 'Courier New', monospace;
}}
.section-title {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 48px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #FFFFFF;
    margin-bottom: 48px;
}}
.section-title::after {{
    content: '';
    display: block;
    width: 60px;
    height: 3px;
    background: linear-gradient(90deg, #FF1B6B, #00D4FF);
    margin-top: 16px;
}}
.section-subtitle {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 15px;
    color: #A0AEC0;
    margin-top: -36px;
    margin-bottom: 40px;
    font-style: italic;
}}
.text-secondary {{ color: #A0AEC0; }}
.text-white {{ color: #FFFFFF; }}

/* ===== EDITORIAL QUESTION & INSIGHT ===== */
.editorial-question {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: #00D4FF;
    margin-bottom: 32px;
}}
.insight-box {{
    border-left: 4px solid #FF1B6B;
    padding: 16px 24px;
    margin-top: 32px;
    background: rgba(255,27,107,0.03);
}}
.insight-box p {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 18px;
    font-weight: 600;
    color: #FFFFFF;
    line-height: 1.6;
    margin: 0;
}}

/* ===== ANIMATIONS ===== */
.fade-up {{
    opacity: 0;
    transform: translateY(30px);
    transition: opacity 0.8s ease, transform 0.8s ease;
}}
.fade-up.visible {{
    opacity: 1;
    transform: translateY(0);
}}
.stagger-1 {{ transition-delay: 0.1s; }}
.stagger-2 {{ transition-delay: 0.2s; }}
.stagger-3 {{ transition-delay: 0.3s; }}
.stagger-4 {{ transition-delay: 0.4s; }}
.stagger-5 {{ transition-delay: 0.5s; }}
.stagger-6 {{ transition-delay: 0.6s; }}

/* ===== COVER ===== */
.cover {{
    text-align: center;
    justify-content: center;
    align-items: center;
}}
.cover-orb {{
    position: absolute;
    width: 600px;
    height: 600px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,27,107,0.15), rgba(0,212,255,0.1), transparent 70%);
    filter: blur(80px);
    animation: orb-rotate 15s linear infinite;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    pointer-events: none;
    z-index: 0;
}}
@keyframes orb-rotate {{
    0%   {{ transform: translate(-50%, -50%) rotate(0deg) scale(1); }}
    25%  {{ transform: translate(-50%, -50%) rotate(90deg) scale(1.1); }}
    50%  {{ transform: translate(-50%, -50%) rotate(180deg) scale(1); }}
    75%  {{ transform: translate(-50%, -50%) rotate(270deg) scale(0.95); }}
    100% {{ transform: translate(-50%, -50%) rotate(360deg) scale(1); }}
}}
.cover-content {{
    position: relative;
    z-index: 1;
}}
.cover-client {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: clamp(60px, 10vw, 120px);
    letter-spacing: 6px;
    background: linear-gradient(135deg, #FF1B6B, #00D4FF);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
}}
.cover-subtitle {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 14px;
    letter-spacing: 6px;
    text-transform: uppercase;
    color: #A0AEC0;
    margin-top: 16px;
}}
.cover-period {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: #5A6378;
    margin-top: 24px;
}}
.cover-line {{
    width: 120px;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,27,107,0.5), transparent);
    margin: 32px auto 0;
}}
.cover-wordmark {{
    z-index: 1;
}}

/* ===== EXECUTIVE SUMMARY CARDS ===== */
.exec-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
}}
@media (max-width: 900px) {{
    .exec-grid {{ grid-template-columns: 1fr; }}
}}
.exec-card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 28px 24px;
}}
.exec-card h3 {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 24px;
    letter-spacing: 2px;
    color: #FFFFFF;
    margin-bottom: 16px;
}}
.exec-card p {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 15px;
    color: #FFFFFF;
    line-height: 1.8;
    margin-bottom: 8px;
}}
.exec-card-paso {{ border-left: 4px solid #FF1B6B; }}
.exec-card-juego {{ border-left: 4px solid #00D4FF; }}
.exec-card-viene {{ border-left: 4px solid #FFB800; }}

/* ===== KPI CARDS ===== */
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
}}
@media (max-width: 900px) {{
    .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
@media (max-width: 600px) {{
    .kpi-grid {{ grid-template-columns: 1fr; }}
}}
.kpi-card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    padding: 32px 28px;
    text-align: center;
    transition: box-shadow 0.3s ease, border-color 0.3s ease;
}}
.kpi-card:hover {{
    border-color: rgba(255,27,107,0.2);
    box-shadow: 0 0 40px rgba(255,27,107,0.05);
}}
.kpi-label {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #A0AEC0;
    margin-bottom: 12px;
}}
.kpi-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 56px;
    font-weight: 700;
    line-height: 1.1;
}}
.kpi-value.white {{ color: #FFFFFF; }}
.kpi-value.cyan {{ color: #00D4FF; }}
.kpi-value.magenta {{ color: #FF1B6B; }}
.kpi-value.gold {{ color: #FFB800; }}

/* Actor stacked bar */
.actor-bar-container {{
    margin-top: 16px;
}}
.actor-bar {{
    display: flex;
    height: 16px;
    border-radius: 8px;
    overflow: hidden;
    background: rgba(255,255,255,0.04);
}}
.actor-bar-segment {{
    height: 100%;
    transition: width 1.5s ease;
}}
.actor-legend {{
    display: flex;
    justify-content: center;
    gap: 20px;
    margin-top: 10px;
    font-size: 11px;
    color: #A0AEC0;
}}
.actor-legend-dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}}

/* ===== CHART SECTION ===== */
.chart-wrapper {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    padding: 32px;
}}
.chart-wrapper canvas {{
    max-height: 400px;
    width: 100% !important;
}}

/* ===== TWO COLUMN LAYOUT ===== */
.two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
}}
@media (max-width: 768px) {{
    .two-col {{ grid-template-columns: 1fr; }}
}}

/* ===== NARRATIVE TRANSITION ===== */
.transition-section {{
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    position: relative;
}}
.transition-bg {{
    position: absolute;
    inset: 0;
    overflow: hidden;
    pointer-events: none;
}}
.transition-bg .blob {{
    position: absolute;
    width: 400px;
    height: 400px;
    border-radius: 50%;
    filter: blur(120px);
    opacity: 0.05;
}}
.transition-bg .blob-magenta {{
    background: #FF1B6B;
    top: 20%;
    left: 20%;
}}
.transition-bg .blob-cyan {{
    background: #00D4FF;
    bottom: 20%;
    right: 20%;
}}
.transition-quote {{
    font-family: Georgia, 'Times New Roman', serif;
    font-size: clamp(28px, 4vw, 36px);
    font-style: italic;
    color: #FFFFFF;
    max-width: 800px;
    line-height: 1.4;
    position: relative;
    z-index: 1;
}}

/* ===== NARRATIVE FULL-VIEWPORT SLIDES (NEW) ===== */
.narrative-bg-number {{
    position: absolute; top: -20px; left: -10px;
    font-family: 'Bebas Neue', Impact, sans-serif; font-size: 160px;
    color: rgba(255,27,107,0.08); line-height: 1; z-index: 0;
}}
.narrative-slide-title {{
    font-family: 'Bebas Neue', Impact, sans-serif; font-size: 42px; color: #fff;
    letter-spacing: 2px; margin-bottom: 40px; position: relative; z-index: 1;
}}
.narrative-two-col {{
    display: grid; grid-template-columns: 45fr 55fr; gap: 40px;
}}
@media (max-width: 768px) {{
    .narrative-two-col {{ grid-template-columns: 1fr; }}
    .narrative-slide-title {{ font-size: 32px; }}
    .narrative-bg-number {{ font-size: 100px; }}
}}
.subsection-label {{
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 2px; color: #FF1B6B; margin-bottom: 12px; margin-top: 32px;
}}
.subsection-text {{ color: #A0AEC0; font-size: 15px; line-height: 1.8; }}
.subsection-text p {{ margin-bottom: 12px; }}
.subsection-text ul {{ padding-left: 20px; margin-bottom: 12px; }}
.subsection-text li {{ margin-bottom: 4px; }}
.subsection-text strong {{ color: #FFFFFF; }}
.narrative-mini-chart {{
    position: absolute; top: 0; right: 0; width: 220px;
}}

/* ===== PLATFORM CARDS ===== */
.platform-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 32px;
}}
@media (max-width: 768px) {{
    .platform-grid {{ grid-template-columns: 1fr; }}
}}
.platform-card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 24px;
}}
.platform-name {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 28px;
    letter-spacing: 2px;
    color: #FFFFFF;
    margin-bottom: 4px;
}}
.platform-quadrant {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 12px;
}}
.platform-bullets {{
    list-style: none;
    padding: 0;
}}
.platform-bullets li {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 14px;
    color: #A0AEC0;
    padding: 4px 0;
    padding-left: 16px;
    position: relative;
}}
.platform-bullets li::before {{
    content: '\\2022';
    position: absolute;
    left: 0;
    color: #5A6378;
}}

/* ===== ANOMALY CARDS ===== */
.anomaly-card {{
    border-radius: 0 16px 16px 0;
    padding: 24px 28px;
    margin-bottom: 16px;
    border-left: 4px solid;
}}
.anomaly-card.critical {{
    border-left-color: #FF1B6B;
    background: rgba(255,27,107,0.03);
}}
.anomaly-card.warning {{
    border-left-color: #FFB800;
    background: rgba(255,184,0,0.03);
}}
.anomaly-card.info {{
    border-left-color: #00D4FF;
    background: rgba(0,212,255,0.03);
}}
.severity-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 10px;
}}
.severity-badge.critical {{
    background: rgba(255,27,107,0.15);
    color: #FF1B6B;
}}
.severity-badge.warning {{
    background: rgba(255,184,0,0.15);
    color: #FFB800;
}}
.severity-badge.info {{
    background: rgba(0,212,255,0.15);
    color: #00D4FF;
}}
.anomaly-desc {{
    color: #A0AEC0;
    font-size: 14px;
    line-height: 1.7;
}}

/* ===== RECOMMENDATION CARDS ===== */
.rec-card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 16px;
    display: flex;
    gap: 20px;
    align-items: flex-start;
}}
.rec-number {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 36px;
    color: #FF1B6B;
    line-height: 1;
    min-width: 36px;
    flex-shrink: 0;
}}
.rec-body h4 {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 18px;
    font-weight: 600;
    color: #FFFFFF;
    margin-bottom: 8px;
}}
.rec-body p {{
    color: #A0AEC0;
    font-size: 14px;
    line-height: 1.7;
    margin-bottom: 8px;
}}
.rec-fundamento {{
    color: #A0AEC0;
    font-size: 14px;
    line-height: 1.7;
}}
.rec-metrica {{
    margin-top: 8px;
    font-size: 13px;
    color: #5A6378;
}}
.rec-metrica-label {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #FFB800;
    margin-right: 6px;
}}
.draft-badge {{
    display: inline-block;
    background: rgba(255,27,107,0.15);
    border: 1px solid rgba(255,27,107,0.3);
    color: #FF1B6B;
    padding: 6px 16px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
    margin-bottom: 32px;
}}

/* ===== SPIKE EXPLORER ===== */
.spike-buttons {{
    display: flex;
    gap: 8px;
    margin-top: 20px;
    flex-wrap: wrap;
}}
.spike-btn {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,27,107,0.3);
    border-radius: 8px;
    color: #A0AEC0;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 12px;
    padding: 8px 14px;
    cursor: pointer;
    transition: all 0.3s ease;
    text-align: center;
    line-height: 1.4;
}}
.spike-btn:hover {{
    border-color: #FF1B6B;
    color: #FFFFFF;
}}
.spike-btn.active {{
    background: #FF1B6B;
    border-color: #FF1B6B;
    color: #FFFFFF;
}}
.spike-btn .spike-letter {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 18px;
    display: block;
    color: inherit;
}}
.spike-btn .spike-dates {{
    font-size: 11px;
    display: block;
    opacity: 0.8;
}}
.spike-btn .spike-pct {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    display: block;
    color: #FF1B6B;
}}
.spike-btn.active .spike-pct {{
    color: #FFFFFF;
}}
.spike-panel {{
    margin-top: 16px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-left: 4px solid #FF1B6B;
    border-radius: 0 12px 12px 0;
    padding: 24px;
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.4s ease, padding 0.4s ease, opacity 0.3s ease;
    opacity: 0;
}}
.spike-panel.open {{
    max-height: 300px;
    opacity: 1;
}}
.spike-panel-title {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 20px;
    color: #FFFFFF;
    letter-spacing: 1px;
    margin-bottom: 8px;
}}
.spike-panel-desc {{
    font-size: 14px;
    color: #A0AEC0;
    line-height: 1.7;
    margin-bottom: 12px;
}}
.spike-panel-meta {{
    display: flex;
    gap: 24px;
    flex-wrap: wrap;
}}
.spike-meta-item {{
    font-size: 12px;
}}
.spike-meta-label {{
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #5A6378;
    font-size: 10px;
    display: block;
    margin-bottom: 2px;
}}
.spike-meta-value {{
    color: #FFFFFF;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
}}

/* ===== METHODOLOGY FOOTER ===== */
.methodology {{
    background: rgba(255,255,255,0.02);
    border-top: 1px solid rgba(255,255,255,0.06);
    padding: 60px 48px;
    scroll-snap-align: start;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.methodology-inner {{
    max-width: 1200px;
    margin: 0 auto;
}}
.methodology .brand {{
    font-family: 'Bebas Neue', Impact, sans-serif;
    font-size: 32px;
    letter-spacing: 4px;
    color: #FF1B6B;
    margin-bottom: 8px;
}}
.methodology .tagline {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 14px;
    color: #A0AEC0;
    margin-bottom: 24px;
}}
.methodology .stats {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #5A6378;
    margin-bottom: 8px;
}}
.methodology .confidential {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 12px;
    color: #5A6378;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.04);
}}
.methodology p {{
    color: #5A6378;
    font-size: 13px;
    line-height: 1.6;
    margin-bottom: 8px;
}}

/* ===== NAV DOTS ===== */
.nav-dots {{
    position: fixed;
    right: 24px;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    flex-direction: column;
    gap: 10px;
    z-index: 1000;
}}
.nav-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    border: 1.5px solid rgba(255,255,255,0.3);
    background: transparent;
    cursor: pointer;
    transition: all 0.3s ease;
    padding: 0;
    position: relative;
}}
.nav-dot.small {{
    width: 4px;
    height: 4px;
}}
.nav-dot.active {{
    width: 10px;
    height: 10px;
    background: #FF1B6B;
    border-color: #FF1B6B;
    box-shadow: 0 0 12px rgba(255,27,107,0.4);
}}
.nav-dot::before {{
    content: attr(title);
    position: absolute;
    right: 24px;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(5,13,26,0.95);
    border: 1px solid rgba(255,255,255,0.1);
    color: #A0AEC0;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 6px;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
}}
.nav-dot:hover::before {{
    opacity: 1;
}}
@media (max-width: 768px) {{
    .nav-dots {{ right: 12px; gap: 8px; }}
    .section {{ padding: 60px 24px; }}
    .methodology {{ padding: 40px 24px; }}
    .cover-wordmark {{ left: 24px; bottom: 24px; }}
    .nav-dot::before {{ display: none; }}
}}

/* ===== D3 VIZ SHARED ===== */
.d3-card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    padding: 32px;
    overflow: hidden;
}}
.d3-card svg {{
    width: 100%;
    display: block;
}}
.d3-tooltip {{
    position: absolute;
    background: rgba(5,13,26,0.95);
    border: 1px solid rgba(255,27,107,0.3);
    color: #A0AEC0;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 12px;
    padding: 8px 12px;
    border-radius: 8px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s ease;
    z-index: 999;
}}
.d3-tooltip.visible {{
    opacity: 1;
}}

/* Pulse animation for crisis markers */
@keyframes pulse-ring {{
    0% {{ transform: scale(1); opacity: 0.6; }}
    100% {{ transform: scale(2.5); opacity: 0; }}
}}
.pulse-marker {{
    animation: pulse-ring 2s ease-out infinite;
}}

/* ===== WORD CLOUD ===== */
.wordcloud-container {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    gap: 8px 16px;
    padding: 32px 16px;
    min-height: 200px;
}}
.wordcloud-word {{
    display: inline-block;
    opacity: 0;
    transition: opacity 0.6s ease, transform 0.6s ease;
    transform: translateY(12px);
    cursor: default;
}}
.wordcloud-word.visible {{
    opacity: 1;
    transform: translateY(0);
}}

/* ===== HEATMAP ===== */
.heatmap-legend {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
    font-size: 11px;
    color: #5A6378;
}}
.heatmap-legend-bar {{
    width: 200px;
    height: 12px;
    border-radius: 6px;
    background: linear-gradient(90deg, #0A1628, #FF1B6B);
}}

/* ===== FORCE GRAPH ===== */
.force-graph-container {{
    position: relative;
    overflow: hidden;
}}
.force-graph-container svg {{
    cursor: grab;
}}
.force-graph-container svg:active {{
    cursor: grabbing;
}}

/* ===== FORCE GRAPH LEGEND ===== */
.force-legend {{
    display: flex;
    gap: 24px;
    margin-top: 16px;
    justify-content: center;
    flex-wrap: wrap;
}}
.force-legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: #A0AEC0;
}}
.force-legend-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
}}
</style>
</head>
<body>

<!-- Shared D3 tooltip -->
<div class="d3-tooltip" id="d3Tooltip"></div>

<!-- Navigation dots (dynamic) -->
<nav class="nav-dots" id="navDots" aria-label="Navegaci\u00f3n de secciones">
{nav_dots_html}</nav>

<!-- SEC-0: COVER -->
<section class="section cover" id="sec-0">
    <div class="cover-orb"></div>
    <div class="cover-content">
        <div class="fade-up" style="margin-bottom:32px;">
            <span style="display:inline-block;background:#CC0000;color:#fff;font-family:'IBM Plex Sans',sans-serif;font-size:12px;font-weight:700;letter-spacing:1px;padding:4px 12px;border-radius:4px;">DEMO</span>
        </div>
        <h1 class="fade-up stagger-1" style="font-family:'Bebas Neue',Impact,sans-serif;font-size:52px;letter-spacing:4px;color:#FFFFFF;line-height:1.1;margin-bottom:24px;">INFORME DE INTELIGENCIA SOCIAL</h1>
        <p class="fade-up stagger-2" style="font-family:'IBM Plex Sans',sans-serif;font-size:13px;text-transform:uppercase;letter-spacing:3px;color:#5A6378;margin-bottom:20px;">preparado para</p>
        {f'<div class="fade-up stagger-3" style="margin-bottom:32px;"><img src="{cover_logo_data_uri}" alt="{client_escaped}" style="max-height:48px;width:auto;object-fit:contain;"></div>' if cover_logo_data_uri else f'<div class="fade-up stagger-3" style="font-family:Bebas Neue,sans-serif;font-size:40px;letter-spacing:3px;color:#FFFFFF;margin-bottom:32px;">{client_escaped}</div>'}
        <p class="fade-up stagger-4" style="font-family:'JetBrains Mono',monospace;font-size:13px;color:#5A6378;margin-bottom:0;">{period_escaped} &mdash; Generado el {generated_date}</p>
        <div class="cover-line fade-up stagger-5"></div>
    </div>
    <div class="cover-wordmark" style="position:absolute;bottom:40px;left:48px;display:flex;align-items:center;gap:10px;z-index:1;">
        <img src="{EPICAL_LOGO_URL}" alt="Epical" style="height:14px;object-fit:contain;opacity:0.7;" onerror="this.style.display='none'">
        <span style="font-family:'IBM Plex Sans',sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,0.3);">Social &amp; Consumer Intelligence</span>
    </div>
</section>

<!-- SEC-1: INTRO / DATASET & FRAMEWORK -->
<section class="section" id="sec-1" style="justify-content:center;">
    <div class="section-inner" style="max-width:1000px;">
        <div class="fade-up" style="text-align:center;margin-bottom:48px;">
            <h2 style="font-family:'Bebas Neue',sans-serif;font-size:42px;letter-spacing:3px;color:#fff;margin-bottom:8px;">MARCO DE AN\u00c1LISIS</h2>
            <div style="width:60px;height:3px;background:linear-gradient(90deg,#FF1B6B,#00D4FF);margin:0 auto;"></div>
        </div>
        <div class="fade-up stagger-2" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px;margin-bottom:48px;">
            <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-top:3px solid #FF1B6B;border-radius:0 0 16px 16px;padding:28px;">
                <div style="font-family:'JetBrains Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#FF1B6B;margin-bottom:12px;">Per\u00edodo de an\u00e1lisis</div>
                <div style="font-family:'IBM Plex Sans',sans-serif;font-size:18px;color:#fff;font-weight:600;margin-bottom:8px;">{period_escaped}</div>
                <div style="font-size:13px;color:#A0AEC0;line-height:1.6;">Monitoreo continuo de conversaciones digitales en torno a {client_escaped} y actores relacionados.</div>
            </div>
            <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-top:3px solid #00D4FF;border-radius:0 0 16px 16px;padding:28px;">
                <div style="font-family:'JetBrains Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#00D4FF;margin-bottom:12px;">Dataset</div>
                <div style="font-family:'IBM Plex Sans',sans-serif;font-size:18px;color:#fff;font-weight:600;margin-bottom:8px;">{total_mentions:,} menciones</div>
                <div style="font-size:13px;color:#A0AEC0;line-height:1.6;">Fuentes: Social listening + scrapping multicanal de plataformas digitales.</div>
            </div>
            <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-top:3px solid #FFB800;border-radius:0 0 16px 16px;padding:28px;">
                <div style="font-family:'JetBrains Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#FFB800;margin-bottom:12px;">Framework</div>
                <div style="font-family:'IBM Plex Sans',sans-serif;font-size:18px;color:#fff;font-weight:600;margin-bottom:8px;">Inteligencia Estrat\u00e9gica</div>
                <div style="font-size:13px;color:#A0AEC0;line-height:1.6;">An\u00e1lisis de volumen, sentimiento, narrativas, actores, plataformas y anomal\u00edas con IA.</div>
            </div>
        </div>
        <div class="fade-up stagger-3" style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
            <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:12px;padding:24px;">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#5A6378;margin-bottom:16px;">Plataformas cubiertas</div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">
                    {platform_badges_html}
                </div>
            </div>
            <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:12px;padding:24px;">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#5A6378;margin-bottom:16px;">Actores monitoreados</div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">
                    {actor_badges_html}
                </div>
            </div>
        </div>
        <div class="fade-up stagger-4" style="text-align:center;margin-top:48px;">
            <div style="display:inline-flex;align-items:center;gap:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px 24px;">
                <img src="{EPICAL_LOGO_URL}" alt="Epical" style="height:13px;object-fit:contain;opacity:0.6;" onerror="this.style.display='none'">
                <span style="color:#5A6378;font-size:12px;">Social &amp; Consumer Intelligence</span>
            </div>
        </div>
    </div>
</section>

<!-- SEC-2: EXECUTIVE SUMMARY -->
<section class="section" id="sec-2">
    <div class="section-inner">
        <h2 class="section-title fade-up">LO QUE NECESIT\u00c1S SABER</h2>
        <div class="exec-grid fade-up stagger-2">
            {exec_cards_html}
        </div>
    </div>
</section>

<!-- SEC-3: KPIs -->
<section class="section" id="sec-3">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;QU\u00c9 TAN GRANDE FUE EL IMPACTO?</div>
        <h2 class="section-title fade-up stagger-1">IMPACTO</h2>
        <div class="kpi-grid fade-up stagger-2">
            {kpi_cards_html}
        </div>
        <!-- Venn Diagram: Brand vs Actor intersection -->
        <div class="fade-up stagger-3" style="margin-top:32px;">
            <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:32px;text-align:center;">
                <h3 style="font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:2px;color:#fff;margin-bottom:8px;">MAPA DE CONVERSACI\u00d3N</h3>
                <p style="font-size:12px;color:#5A6378;margin-bottom:20px;">Menciones exclusivas vs. intersecci\u00f3n</p>
                <div id="vennDiagram" style="width:100%;max-width:500px;margin:0 auto;"></div>
            </div>
        </div>
        <div class="insight-box fade-up stagger-4">
            <p>{insight_kpi}</p>
        </div>
    </div>
</section>

<!-- SEC-4: VOLUME CHART + SPIKE EXPLORER -->
<section class="section" id="sec-4">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;C\u00d3MO EVOLUCION\u00d3 LA CONVERSACI\u00d3N D\u00cdA A D\u00cdA?</div>
        <h2 class="section-title fade-up stagger-1">CRONOLOG\u00cdA</h2>
        <div class="chart-wrapper fade-up stagger-2">
            <canvas id="volumeChart"></canvas>
        </div>
        {"" if not has_spikes else f'''<!-- Spike Explorer -->
        <div class="spike-buttons fade-up stagger-3" id="spikeButtons">
            {spike_buttons_html}
        </div>
        <div class="spike-panel open" id="spikePanel">
            <div class="spike-panel-title" id="spikePanelTitle"></div>
            <div class="spike-panel-desc" id="spikePanelDesc"></div>
            <div class="spike-panel-meta" id="spikePanelMeta"></div>
        </div>'''}
        <div class="insight-box fade-up stagger-4">
            <p>{insight_volume}</p>
        </div>
    </div>
</section>

<!-- SEC-5: CRISIS TIMELINE (D3) -->
<section class="section" id="sec-5">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;HUBO UNA VENTANA PARA ACTUAR ANTES?</div>
        <h2 class="section-title fade-up stagger-1">LA EXPLOSI\u00d3N</h2>
        <div class="d3-card fade-up stagger-2">
            <div id="crisisTimeline"></div>
        </div>
        <div class="insight-box fade-up stagger-3">
            <p>{insight_timeline}</p>
        </div>
    </div>
</section>

<!-- SEC-6: SENTIMENT & SOURCES -->
<section class="section" id="sec-6">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;QU\u00c9 EMOCI\u00d3N DOMINA LA CONVERSACI\u00d3N?</div>
        <h2 class="section-title fade-up stagger-1">SENTIMIENTO</h2>
        <div class="two-col fade-up stagger-2">
            <div class="chart-wrapper">
                <h3 style="font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:2px;color:#fff;margin-bottom:20px;">DISTRIBUCI\u00d3N DE SENTIMIENTO</h3>
                <canvas id="sentimentChart"></canvas>
            </div>
            <div class="chart-wrapper">
                <h3 style="font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:2px;color:#fff;margin-bottom:20px;">FUENTES PRINCIPALES</h3>
                <canvas id="sourcesChart"></canvas>
            </div>
        </div>
        <div class="insight-box fade-up stagger-3">
            <p>{insight_sentiment}</p>
        </div>
    </div>
</section>

{_sec7_transition}

{_sec8_heatmap}

<!-- SEC-9: ACTOR GRAPH -->
<section class="section" id="sec-9">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;C\u00d3MO SE CONECTAN LOS ACTORES?</div>
        <h2 class="section-title fade-up stagger-1">RED DE ACTORES</h2>
        <div class="d3-card fade-up stagger-2 force-graph-container" style="margin-bottom:24px;">
            <div id="actorGraph"></div>
        </div>
        <div class="force-legend fade-up stagger-3">
            {actor_legend_items}
        </div>
        <div class="insight-box fade-up stagger-4">
            <p>{insight_actor_graph}</p>
        </div>
    </div>
</section>

{_sec10_wordcloud}

<!-- SEC-10b: FINDINGS -->
{_sec10b_findings}

{_sec11_transition}

<!-- SEC-12: NARRATIVE 01 -->
<section class="section" id="sec-12">
    {narr_section_0}
</section>

<!-- SEC-13: NARRATIVE 02 -->
<section class="section" id="sec-13">
    {narr_section_1}
</section>

<!-- SEC-14: NARRATIVE 03 -->
<section class="section" id="sec-14">
    {narr_section_2}
</section>

{_sec15_transition}

<!-- SEC-16: PLATFORMS / AUDIENCIAS -->
<section class="section" id="sec-16" style="justify-content: flex-start; padding-top: 80px;">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;D\u00d3NDE EST\u00c1 EL RIESGO Y D\u00d3NDE LA OPORTUNIDAD?</div>
        <h2 class="section-title fade-up stagger-1">AUDIENCIAS</h2>

        <div class="platform-grid fade-up stagger-2">
            {platform_matrix_html}
        </div>

        {competitive_benchmark_html}

        {_bubbles_html}

        <div class="insight-box fade-up stagger-4">
            <p>{insight_platforms}</p>
        </div>
    </div>
</section>

<!-- SCENARIO PROJECTION -->
<section class="section" id="sec-scenarios" style="justify-content: flex-start; padding-top: 80px;">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;QU&Eacute; PASA EN LOS PR&Oacute;XIMOS 30 D&Iacute;AS?</div>
        <h2 class="section-title fade-up stagger-1">TRES ESCENARIOS POSIBLES</h2>
        {scenarios_html}
    </div>
</section>

{_sec17_transition}

<!-- SEC-18: RECOMMENDATIONS -->
<section class="section" id="sec-18" style="justify-content: flex-start; padding-top: 80px;">
    <div class="section-inner">
        <div class="editorial-question fade-up">&iquest;CU\u00c1LES SON LAS 3 DECISIONES M\u00c1S URGENTES?</div>
        <h2 class="section-title fade-up stagger-1">DECISIONES</h2>
        <div class="draft-badge fade-up stagger-1">Borrador &mdash; requiere revisi\u00f3n del analista</div>
        <div class="fade-up stagger-2">
            {recommendation_cards_html if recommendation_cards_html else '<p style="color:#5A6378;">No se generaron recomendaciones para este periodo.</p>'}
        </div>
        <div class="insight-box fade-up stagger-3">
            <p>{insight_recommendations}</p>
        </div>
    </div>
</section>

<!-- EPICAL CAPABILITIES -->
<section class="section" id="sec-epical" style="justify-content: flex-start; padding-top: 80px;">
    <div class="section-inner">
        <h2 class="section-title fade-up">C&Oacute;MO SE PRODUJO ESTE AN&Aacute;LISIS</h2>
        <p class="fade-up stagger-1" style="color:#A0AEC0;font-size:15px;margin-bottom:40px;">Lo que viste en este reporte, cada mes</p>
        <div style="display:grid;grid-template-columns:3fr 2fr;gap:48px;" class="fade-up stagger-2">
            <div>
                <div style="display:flex;gap:20px;margin-bottom:32px;">
                    <div style="display:flex;flex-direction:column;align-items:center;min-width:40px;">
                        <div style="width:40px;height:40px;border-radius:50%;background:rgba(0,212,255,0.15);border:1px solid rgba(0,212,255,0.3);display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:14px;color:#00D4FF;font-weight:700;">1</div>
                        <div style="width:1px;height:100%;background:rgba(0,212,255,0.15);margin-top:8px;"></div>
                    </div>
                    <div>
                        <div style="font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:2px;color:#00D4FF;margin-bottom:8px;">RECOLECCI&Oacute;N</div>
                        <p style="color:#A0AEC0;font-size:14px;line-height:1.7;">{total_mentions:,} menciones capturadas de {len(top_sources)} plataformas mediante social listening + scrapping directo. Procesamiento, limpieza y deduplicaci&oacute;n automatizada.</p>
                    </div>
                </div>
                <div style="display:flex;gap:20px;margin-bottom:32px;">
                    <div style="display:flex;flex-direction:column;align-items:center;min-width:40px;">
                        <div style="width:40px;height:40px;border-radius:50%;background:rgba(0,212,255,0.15);border:1px solid rgba(0,212,255,0.3);display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:14px;color:#00D4FF;font-weight:700;">2</div>
                        <div style="width:1px;height:100%;background:rgba(0,212,255,0.15);margin-top:8px;"></div>
                    </div>
                    <div>
                        <div style="font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:2px;color:#00D4FF;margin-bottom:8px;">AN&Aacute;LISIS</div>
                        <p style="color:#A0AEC0;font-size:14px;line-height:1.7;">Clustering tem&aacute;tico, detecci&oacute;n de anomal&iacute;as, an&aacute;lisis de actores y sentimiento sobre dataset completo. Muestreo estratificado para an&aacute;lisis narrativo profundo con IA.</p>
                    </div>
                </div>
                <div style="display:flex;gap:20px;">
                    <div style="display:flex;flex-direction:column;align-items:center;min-width:40px;">
                        <div style="width:40px;height:40px;border-radius:50%;background:rgba(0,212,255,0.15);border:1px solid rgba(0,212,255,0.3);display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:14px;color:#00D4FF;font-weight:700;">3</div>
                    </div>
                    <div>
                        <div style="font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:2px;color:#00D4FF;margin-bottom:8px;">INTELIGENCIA</div>
                        <p style="color:#A0AEC0;font-size:14px;line-height:1.7;">S&iacute;ntesis narrativa, identificaci&oacute;n de hallazgos no obvios, proyecci&oacute;n de escenarios y recomendaciones accionables producidas por analistas especializados con asistencia de IA.</p>
                    </div>
                </div>
            </div>
            <div style="display:flex;flex-direction:column;gap:24px;justify-content:center;">
                <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:24px;text-align:center;">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:48px;font-weight:700;color:#fff;">{total_mentions:,}</div>
                    <div style="font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#5A6378;margin-top:4px;">menciones procesadas</div>
                </div>
                <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:24px;text-align:center;">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:48px;font-weight:700;color:#fff;">{days_covered}</div>
                    <div style="font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#5A6378;margin-top:4px;">d&iacute;as cubiertos</div>
                </div>
                <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:24px;text-align:center;">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:48px;font-weight:700;color:#00D4FF;">&lt; 4h</div>
                    <div style="font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#5A6378;margin-top:4px;">tiempo de producci&oacute;n</div>
                </div>
            </div>
        </div>
        <div class="fade-up stagger-3" style="margin-top:40px;text-align:center;">
            <p style="color:#5A6378;font-size:13px;margin-bottom:16px;">Este reporte fue producido autom&aacute;ticamente con asistencia de IA, reduciendo significativamente el tiempo de an&aacute;lisis.</p>
            <div style="display:inline-flex;align-items:center;gap:12px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px 24px;">
                <img src="{EPICAL_LOGO_URL}" alt="Epical" style="height:14px;object-fit:contain;opacity:0.7;" onerror="this.style.display='none'">
                <span style="color:#A0AEC0;font-size:12px;">Social &amp; Consumer Intelligence para decisiones de negocio en LATAM</span>
            </div>
        </div>
    </div>
</section>

<!-- METHODOLOGY FOOTER -->
<footer class="methodology" id="sec-19">
    <div class="methodology-inner">
        <div class="brand fade-up">EPICAL</div>
        <div class="tagline fade-up stagger-1">Social &amp; Consumer Intelligence para decisiones de negocio</div>
        <div class="stats fade-up stagger-2">Total menciones analizadas: {total_mentions:,} &bull; Per\u00edodo: {period_escaped}</div>
        <div class="stats fade-up stagger-3">Generado: {generated_date}</div>
        {f'<div class="fade-up stagger-4" style="margin-top:20px;">{methodology_html}</div>' if methodology_html else ''}
        <div class="confidential fade-up stagger-5">
            Confidencial &mdash; uso interno<br>
            &copy; {year} Epical. Todos los derechos reservados.
        </div>
    </div>
</footer>

<script>
/* ===== THEME CONFIG ===== */
const THEME = {{
    isLight: {"true" if is_light else "false"},
    text: '{"#1A1A2E" if is_light else "#A0AEC0"}',
    textMuted: '{"#6B7280" if is_light else "#5A6378"}',
    bg: '{"#FFFFFF" if is_light else "#050D1A"}',
    bgCard: '{"#F8F9FA" if is_light else "rgba(255,255,255,0.03)"}',
    border: '{"#E5E7EB" if is_light else "rgba(255,255,255,0.06)"}',
    accent: '{"" + brand_color if is_light else "#FF1B6B"}',
    accentSecondary: '{"#6B7280" if is_light else "#00D4FF"}',
    accentGold: '{"#C8A84B" if is_light else "#FFB800"}',
    grid: '{"rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.04)"}',
    chartFill: '{"rgba(0,102,204,0.1)" if is_light else "rgba(0,212,255,0.25)"}',
    chartFillEnd: '{"rgba(0,102,204,0.0)" if is_light else "rgba(0,212,255,0.0)"}',
    tooltipBg: '{"rgba(255,255,255,0.95)" if is_light else "rgba(5,13,26,0.95)"}',
    tooltipText: '{"#1A1A2E" if is_light else "#FFFFFF"}',
    tooltipBorder: '{"#E5E7EB" if is_light else "rgba(255,255,255,0.1)"}',
}};

/* ===== DATA ===== */
const volumeLabels = {volume_labels_json};
const volumeData = {volume_data_json};
const sentimentLabels = {sentiment_labels_json};
const sentimentCounts = {sentiment_counts_json};
const sentimentColors = {sentiment_colors_json};
const sourceLabels = {source_labels_json};
const sourceData = {source_data_json};
const anomalyDates = {anomaly_dates_json};
const anomalySeverity = {anomaly_severity_json};
const actorBreakdown = {actor_breakdown_json};
const intersectionData = {intersection_json};
const topicClusters = {topic_clusters_json};
const topAuthors = {top_authors_json};
const normalizedSources = {normalized_sources_json};

/* ===== SPIKE EXPLORER DATA ===== */
const spikes = {spike_js_data};

/* ===== CHART DEFAULTS ===== */
Chart.defaults.color = THEME.text;
Chart.defaults.borderColor = THEME.border;
Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";

/* ===== VOLUME CHART ===== */
(function() {{
    var ctx = document.getElementById('volumeChart');
    if (!ctx || volumeLabels.length === 0) return;

    var gradient = ctx.getContext('2d').createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, THEME.chartFill);
    gradient.addColorStop(1, THEME.chartFillEnd);

    var anomalyPoints = volumeLabels.map(function(label) {{
        return anomalyDates.indexOf(label) >= 0 ? Math.max.apply(null, volumeData) * 1.05 : null;
    }});

    var datasets = [
        {{
            label: 'Menciones',
            data: volumeData,
            borderColor: THEME.accentSecondary,
            backgroundColor: gradient,
            fill: true,
            tension: 0.4,
            pointBackgroundColor: THEME.accentSecondary,
            pointRadius: 3,
            pointHoverRadius: 6,
            borderWidth: 2.5,
        }}
    ];

    if (anomalyDates.length > 0) {{
        datasets.push({{
            label: 'Anomal\u00eda',
            data: anomalyPoints,
            type: 'bar',
            backgroundColor: 'rgba(255,27,107,0.15)',
            borderColor: 'rgba(255,27,107,0.5)',
            borderWidth: 1,
            borderDash: [5, 3],
            barPercentage: 0.15,
        }});
    }}

    new Chart(ctx, {{
        type: 'line',
        data: {{ labels: volumeLabels, datasets: datasets }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: 'index', intersect: false }},
            plugins: {{
                legend: {{ display: anomalyDates.length > 0, labels: {{ usePointStyle: true, padding: 16 }} }}
            }},
            scales: {{
                x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 45, font: {{ size: 11 }} }} }},
                y: {{ beginAtZero: true, grid: {{ color: THEME.grid }}, ticks: {{ font: {{ size: 11 }} }} }}
            }}
        }}
    }});
}})();

/* ===== SPIKE EXPLORER ===== */
(function() {{
    if (spikes.length === 0) return;
    var panel = document.getElementById('spikePanel');
    var titleEl = document.getElementById('spikePanelTitle');
    var descEl = document.getElementById('spikePanelDesc');
    var metaEl = document.getElementById('spikePanelMeta');
    var buttons = document.querySelectorAll('.spike-btn');
    if (!panel || !titleEl || !descEl || !metaEl) return;
    var activeIndex = 0;

    function showSpike(index) {{
        var spike = spikes[index];
        if (!spike) return;
        titleEl.textContent = 'PICO ' + spike.id + ' \u2014 ' + spike.dates + ' (' + spike.pctChange + ')';
        descEl.textContent = spike.description;
        metaEl.innerHTML =
            '<div class="spike-meta-item"><span class="spike-meta-label">VOLUMEN</span><span class="spike-meta-value">' + spike.volume + '</span></div>' +
            '<div class="spike-meta-item"><span class="spike-meta-label">PLATAFORMA</span><span class="spike-meta-value">' + spike.platform + '</span></div>' +
            '<div class="spike-meta-item"><span class="spike-meta-label">TONO</span><span class="spike-meta-value">' + spike.tone + '</span></div>';
        panel.classList.add('open');
        buttons.forEach(function(btn, i) {{
            btn.classList.toggle('active', parseInt(btn.getAttribute('data-spike')) === index);
        }});
        activeIndex = index;
    }}

    buttons.forEach(function(btn) {{
        btn.addEventListener('click', function() {{
            var idx = parseInt(this.getAttribute('data-spike'));
            if (idx === activeIndex) {{
                /* Toggle off */
                panel.classList.remove('open');
                this.classList.remove('active');
                activeIndex = -1;
            }} else {{
                showSpike(idx);
            }}
        }});
    }});

    /* Show default spike 0 */
    showSpike(0);
}})();

/* ===== SENTIMENT CHART ===== */
(function() {{
    var ctx = document.getElementById('sentimentChart');
    if (!ctx || sentimentLabels.length === 0) return;

    new Chart(ctx, {{
        type: 'doughnut',
        data: {{
            labels: sentimentLabels,
            datasets: [{{
                data: sentimentCounts,
                backgroundColor: sentimentColors,
                borderWidth: 0,
                hoverOffset: 8,
            }}]
        }},
        options: {{
            responsive: true,
            cutout: '65%',
            plugins: {{
                legend: {{
                    position: 'bottom',
                    labels: {{ padding: 16, usePointStyle: true, pointStyleWidth: 8, font: {{ size: 12 }} }}
                }}
            }}
        }}
    }});
}})();

/* ===== SOURCES CHART ===== */
(function() {{
    var ctx = document.getElementById('sourcesChart');
    if (!ctx || sourceLabels.length === 0) return;

    new Chart(ctx, {{
        type: 'bar',
        data: {{
            labels: sourceLabels,
            datasets: [{{
                label: 'Menciones',
                data: sourceData,
                backgroundColor: function(context) {{
                    var chart = context.chart;
                    var c = chart.ctx;
                    var chartArea = chart.chartArea;
                    if (!chartArea) return THEME.accent;
                    var grad = c.createLinearGradient(chartArea.left, 0, chartArea.right, 0);
                    grad.addColorStop(0, THEME.accent);
                    grad.addColorStop(1, THEME.accentSecondary);
                    return grad;
                }},
                borderRadius: 6,
                borderSkipped: false,
            }}]
        }},
        options: {{
            indexAxis: 'y',
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ grid: {{ color: THEME.grid }}, ticks: {{ font: {{ size: 11 }} }} }},
                y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 12 }} }} }}
            }}
        }}
    }});
}})();

/* ===== D3 TOOLTIP HELPER ===== */
var d3Tooltip = d3.select('#d3Tooltip');
function showTooltip(event, html) {{
    d3Tooltip
        .html(html)
        .style('left', (event.pageX + 12) + 'px')
        .style('top', (event.pageY - 28) + 'px')
        .classed('visible', true);
}}
function hideTooltip() {{
    d3Tooltip.classed('visible', false);
}}

/* ===== D3 VIZ 1: CRISIS TIMELINE ===== */
(function() {{
    var container = document.getElementById('crisisTimeline');
    if (!container || volumeLabels.length === 0) return;

    var margin = {{ top: 30, right: 30, bottom: 60, left: 60 }};
    var width = container.clientWidth - margin.left - margin.right;
    var height = 360 - margin.top - margin.bottom;

    var svg = d3.select(container).append('svg')
        .attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' ' + (height + margin.top + margin.bottom))
        .append('g')
        .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

    var parseDate = d3.timeParse('%Y-%m-%d');
    var data = volumeLabels.map(function(d, i) {{
        return {{ date: parseDate(d) || new Date(d), value: volumeData[i], label: d }};
    }}).filter(function(d) {{ return d.date !== null; }});

    var x = d3.scaleTime()
        .domain(d3.extent(data, function(d) {{ return d.date; }}))
        .range([0, width]);

    var y = d3.scaleLinear()
        .domain([0, d3.max(data, function(d) {{ return d.value; }}) * 1.1])
        .range([height, 0]);

    /* Grid lines */
    svg.append('g')
        .attr('transform', 'translate(0,' + height + ')')
        .call(d3.axisBottom(x).ticks(8).tickFormat(d3.timeFormat('%d/%m')))
        .selectAll('text')
        .style('fill', THEME.textMuted)
        .style('font-size', '11px');

    svg.append('g')
        .call(d3.axisLeft(y).ticks(5))
        .selectAll('text')
        .style('fill', THEME.textMuted)
        .style('font-size', '11px');

    svg.selectAll('.domain').style('stroke', THEME.border);
    svg.selectAll('.tick line').style('stroke', THEME.grid);

    /* Area */
    var area = d3.area()
        .x(function(d) {{ return x(d.date); }})
        .y0(height)
        .y1(function(d) {{ return y(d.value); }})
        .curve(d3.curveMonotoneX);

    var defs = svg.append('defs');
    var gradient = defs.append('linearGradient')
        .attr('id', 'crisisGrad')
        .attr('x1', '0%').attr('y1', '0%')
        .attr('x2', '0%').attr('y2', '100%');
    gradient.append('stop').attr('offset', '0%').attr('stop-color', THEME.accentSecondary).attr('stop-opacity', 0.3);
    gradient.append('stop').attr('offset', '100%').attr('stop-color', THEME.accentSecondary).attr('stop-opacity', 0.0);

    svg.append('path')
        .datum(data)
        .attr('fill', 'url(#crisisGrad)')
        .attr('d', area);

    /* Line */
    var line = d3.line()
        .x(function(d) {{ return x(d.date); }})
        .y(function(d) {{ return y(d.value); }})
        .curve(d3.curveMonotoneX);

    svg.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', THEME.accentSecondary)
        .attr('stroke-width', 2.5)
        .attr('d', line);

    /* Anomaly markers */
    var anomalySet = new Set(anomalyDates);
    var anomalyData = data.filter(function(d) {{ return anomalySet.has(d.label); }});

    /* Pulse rings for critical */
    anomalyData.forEach(function(d) {{
        var sev = anomalySeverity[d.label] || 'info';
        if (sev === 'critical') {{
            svg.append('circle')
                .attr('cx', x(d.date))
                .attr('cy', y(d.value))
                .attr('r', 8)
                .attr('fill', 'none')
                .attr('stroke', THEME.accent)
                .attr('stroke-width', 2)
                .attr('class', 'pulse-marker');
        }}
    }});

    /* Solid markers */
    svg.selectAll('.anomaly-marker')
        .data(anomalyData)
        .enter()
        .append('circle')
        .attr('class', 'anomaly-marker')
        .attr('cx', function(d) {{ return x(d.date); }})
        .attr('cy', function(d) {{ return y(d.value); }})
        .attr('r', 6)
        .attr('fill', function(d) {{
            var sev = anomalySeverity[d.label] || 'info';
            return sev === 'critical' ? THEME.accent : THEME.accentGold;
        }})
        .attr('stroke', THEME.bg)
        .attr('stroke-width', 2)
        .style('cursor', 'pointer')
        .on('mouseover', function(event, d) {{
            showTooltip(event, '<strong>' + d.label + '</strong><br>Menciones: ' + d.value.toLocaleString('es-ES'));
        }})
        .on('mousemove', function(event) {{
            d3Tooltip.style('left', (event.pageX + 12) + 'px').style('top', (event.pageY - 28) + 'px');
        }})
        .on('mouseout', hideTooltip);

    /* Phase labels */
    if (data.length > 4) {{
        var maxVal = d3.max(data, function(d) {{ return d.value; }});
        var threshold = maxVal * 0.3;
        var phases = [];
        var spikeIndices = [];
        data.forEach(function(d, i) {{
            if (d.value > threshold) spikeIndices.push(i);
        }});
        if (spikeIndices.length > 0) {{
            var spikeStart = spikeIndices[0];
            var spikeEnd = spikeIndices[spikeIndices.length - 1];
            if (spikeStart > 1) {{
                phases.push({{ label: 'Pre-crisis', start: 0, end: spikeStart - 1 }});
            }}
            phases.push({{ label: 'Explosi\u00f3n', start: spikeStart, end: Math.min(spikeStart + Math.max(1, Math.floor((spikeEnd - spikeStart) / 2)), data.length - 1) }});
            if (spikeEnd < data.length - 2) {{
                phases.push({{ label: 'Estabilizaci\u00f3n', start: spikeEnd + 1, end: data.length - 1 }});
            }}
        }}
        phases.forEach(function(p) {{
            var x1 = x(data[p.start].date);
            var x2 = x(data[p.end].date);
            var midX = (x1 + x2) / 2;
            svg.append('text')
                .attr('x', midX)
                .attr('y', height + 42)
                .attr('text-anchor', 'middle')
                .style('fill', THEME.textMuted)
                .style('font-size', '10px')
                .style('letter-spacing', '1.5px')
                .style('text-transform', 'uppercase')
                .style('font-family', "'IBM Plex Sans', sans-serif")
                .text(p.label);
            /* Bracket line */
            svg.append('line')
                .attr('x1', x1).attr('x2', x2)
                .attr('y1', height + 30).attr('y2', height + 30)
                .attr('stroke', THEME.border)
                .attr('stroke-width', 1);
        }});
    }}
}})();

/* ===== D3 VIZ 2: NARRATIVE HEATMAP ===== */
(function() {{
    var container = document.getElementById('narrativeHeatmap');
    if (!container || topicClusters.length === 0 || volumeLabels.length === 0) return;

    /* Divide dates into 4 phases */
    var nDates = volumeLabels.length;
    var phaseSize = Math.ceil(nDates / 4);
    var phaseLabels = [];
    var phaseVolumes = [];  /* total volume in each phase */
    for (var p = 0; p < 4; p++) {{
        var start = p * phaseSize;
        var end = Math.min((p + 1) * phaseSize, nDates);
        if (start >= nDates) break;
        var label = volumeLabels[start].slice(5) + ' \u2014 ' + volumeLabels[Math.min(end - 1, nDates - 1)].slice(5);
        phaseLabels.push(label);
        var total = 0;
        for (var i = start; i < end; i++) total += volumeData[i];
        phaseVolumes.push(total);
    }}
    var totalVolume = phaseVolumes.reduce(function(a, b) {{ return a + b; }}, 0) || 1;

    /* Build grid data */
    var clusters = topicClusters.slice(0, 10);  /* limit to top 10 */
    var gridData = [];
    var maxCount = 0;
    clusters.forEach(function(cluster, ci) {{
        phaseLabels.forEach(function(phase, pi) {{
            var weight = phaseVolumes[pi] / totalVolume;
            var count = Math.round(cluster.mention_count * weight);
            if (count > maxCount) maxCount = count;
            gridData.push({{ cluster: cluster.label, phase: phase, count: count, ci: ci, pi: pi }});
        }});
    }});

    var margin = {{ top: 10, right: 20, bottom: 80, left: 180 }};
    var cellW = 90;
    var cellH = 32;
    var width = phaseLabels.length * cellW;
    var height = clusters.length * cellH;

    var svg = d3.select(container).append('svg')
        .attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' ' + (height + margin.top + margin.bottom))
        .append('g')
        .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

    var colorScale = d3.scaleLinear()
        .domain([0, maxCount])
        .range([THEME.isLight ? '#F0F0F0' : '#0A1628', THEME.accent]);

    /* Cells */
    svg.selectAll('.hm-cell')
        .data(gridData)
        .enter()
        .append('rect')
        .attr('x', function(d) {{ return d.pi * cellW; }})
        .attr('y', function(d) {{ return d.ci * cellH; }})
        .attr('width', cellW - 3)
        .attr('height', cellH - 3)
        .attr('rx', 4)
        .attr('fill', function(d) {{ return colorScale(d.count); }})
        .style('cursor', 'pointer')
        .on('mouseover', function(event, d) {{
            showTooltip(event, '<strong>' + d.cluster + '</strong><br>' + d.phase + '<br>Menciones: ~' + d.count.toLocaleString('es-ES'));
        }})
        .on('mousemove', function(event) {{
            d3Tooltip.style('left', (event.pageX + 12) + 'px').style('top', (event.pageY - 28) + 'px');
        }})
        .on('mouseout', hideTooltip);

    /* Y axis labels */
    clusters.forEach(function(c, i) {{
        svg.append('text')
            .attr('x', -10)
            .attr('y', i * cellH + cellH / 2 + 4)
            .attr('text-anchor', 'end')
            .style('fill', THEME.text)
            .style('font-size', '11px')
            .style('font-family', "'IBM Plex Sans', sans-serif")
            .text(c.label.length > 22 ? c.label.slice(0, 20) + '\u2026' : c.label);
    }});

    /* X axis labels */
    phaseLabels.forEach(function(label, i) {{
        svg.append('text')
            .attr('x', i * cellW + cellW / 2)
            .attr('y', height + 20)
            .attr('text-anchor', 'middle')
            .style('fill', THEME.textMuted)
            .style('font-size', '10px')
            .style('font-family', "'IBM Plex Sans', sans-serif")
            .attr('transform', 'rotate(-30,' + (i * cellW + cellW / 2) + ',' + (height + 20) + ')')
            .text(label);
    }});
}})();

/* ===== D3 VIZ 3: ACTOR RELATIONSHIP GRAPH ===== */
(function() {{
    var container = document.getElementById('actorGraph');
    if (!container) return;

    var w = container.clientWidth || 700;
    var h = 450;

    var svg = d3.select(container).append('svg')
        .attr('viewBox', '0 0 ' + w + ' ' + h);

    var defs = svg.append('defs');
    /* Glow filter */
    var filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'coloredBlur');
    var feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    /* Build nodes dynamically from actor breakdown */
    var nodes = [];
    var links = [];
    var actorKeys = Object.keys(actorBreakdown);
    var actorCounts = actorKeys.map(function(k) {{ return actorBreakdown[k]; }});
    var maxActor = Math.max.apply(null, actorCounts.concat([1]));
    var actorNodeColors = [THEME.accent, THEME.accentSecondary, THEME.accentGold, '#8B5CF6', THEME.textMuted];

    actorKeys.forEach(function(key, idx) {{
        var count = actorBreakdown[key];
        var color = actorNodeColors[idx % actorNodeColors.length];
        nodes.push({{
            id: key.charAt(0).toUpperCase() + key.slice(1),
            count: count,
            color: color,
            r: Math.max(25, 55 * (count / maxActor))
        }});
    }});

    /* Add links between actors */
    if (nodes.length >= 2) {{
        links.push({{ source: nodes[0].id, target: nodes[1].id, strength: 3 }});
    }}

    /* Add other top authors */
    var existingNames = new Set(actorKeys.map(function(k) {{ return k.toLowerCase(); }}));
    var otherCount = 0;
    topAuthors.forEach(function(a) {{
        if (otherCount >= 5) return;
        if (existingNames.has(a[0].toLowerCase())) return;
        var count = a[1] || 0;
        nodes.push({{ id: a[0], count: count, color: THEME.textMuted, r: Math.max(12, 30 * (count / maxActor)) }});
        /* Connect to the actor with highest count */
        var target = nodes.length > 1 ? nodes[0].id : nodes[0].id;
        links.push({{ source: a[0], target: target, strength: 1 }});
        otherCount++;
    }});

    if (nodes.length === 0) return;

    var simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(function(d) {{ return d.id; }}).distance(120))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(w / 2, h / 2))
        .force('collision', d3.forceCollide().radius(function(d) {{ return d.r + 10; }}))
        .alphaDecay(0.05);

    var link = svg.append('g')
        .selectAll('line')
        .data(links)
        .enter()
        .append('line')
        .attr('stroke', function(d) {{ return d.strength > 2 ? (THEME.accent + '66') : THEME.border; }})
        .attr('stroke-width', function(d) {{ return d.strength > 2 ? 3 : 1.5; }});

    var node = svg.append('g')
        .selectAll('g')
        .data(nodes)
        .enter()
        .append('g')
        .style('cursor', 'grab')
        .call(d3.drag()
            .on('start', function(event, d) {{
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x; d.fy = d.y;
            }})
            .on('drag', function(event, d) {{
                d.fx = event.x; d.fy = event.y;
            }})
            .on('end', function(event, d) {{
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null; d.fy = null;
            }})
        );

    node.append('circle')
        .attr('r', function(d) {{ return d.r; }})
        .attr('fill', function(d) {{ return d.color; }})
        .attr('fill-opacity', 0.8)
        .attr('stroke', function(d) {{ return d.color; }})
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.4)
        .style('filter', 'url(#glow)');

    node.append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', '0.35em')
        .style('fill', THEME.isLight ? '#1A1A2E' : '#FFFFFF')
        .style('font-size', function(d) {{ return d.r > 30 ? '13px' : '10px'; }})
        .style('font-family', "'IBM Plex Sans', sans-serif")
        .style('font-weight', '600')
        .style('pointer-events', 'none')
        .text(function(d) {{ return d.id; }});

    node.on('mouseover', function(event, d) {{
        showTooltip(event, '<strong>' + d.id + '</strong><br>Menciones: ' + d.count.toLocaleString('es-ES'));
    }})
    .on('mousemove', function(event) {{
        d3Tooltip.style('left', (event.pageX + 12) + 'px').style('top', (event.pageY - 28) + 'px');
    }})
    .on('mouseout', hideTooltip);

    simulation.on('tick', function() {{
        link
            .attr('x1', function(d) {{ return d.source.x; }})
            .attr('y1', function(d) {{ return d.source.y; }})
            .attr('x2', function(d) {{ return d.target.x; }})
            .attr('y2', function(d) {{ return d.target.y; }});
        node.attr('transform', function(d) {{ return 'translate(' + d.x + ',' + d.y + ')'; }});
    }});
}})();

/* ===== D3 VIZ 4: ENGAGEMENT BUBBLE CHART ===== */
(function() {{
    var container = document.getElementById('platformBubbles');
    if (!container || normalizedSources.length === 0) return;

    var w = container.clientWidth || 700;
    var h = 400;
    var margin = {{ top: 20, right: 20, bottom: 20, left: 20 }};
    var innerW = w - margin.left - margin.right;
    var innerH = h - margin.top - margin.bottom;

    var svg = d3.select(container).append('svg')
        .attr('viewBox', '0 0 ' + w + ' ' + h)
        .append('g')
        .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

    var maxCount = d3.max(normalizedSources, function(d) {{ return d[1]; }}) || 1;
    var rScale = d3.scaleSqrt().domain([0, maxCount]).range([20, 70]);

    var platformColors = {{
        'Facebook': '#1877F2',
        'TikTok': '#FF0050',
        'Instagram': '#E1306C',
        'Twitter': '#1DA1F2',
        'YouTube': '#FF0000',
    }};
    var fallbackColors = [THEME.accent, THEME.accentSecondary, THEME.accentGold, '#8B5CF6', '#10B981', '#F59E0B', '#6366F1', '#EC4899'];

    var bubbleData = normalizedSources.map(function(d, i) {{
        return {{
            name: d[0],
            count: d[1],
            r: rScale(d[1]),
            color: platformColors[d[0]] || fallbackColors[i % fallbackColors.length],
        }};
    }});

    /* Use force simulation to pack bubbles */
    var simulation = d3.forceSimulation(bubbleData)
        .force('x', d3.forceX(innerW / 2).strength(0.05))
        .force('y', d3.forceY(innerH / 2).strength(0.05))
        .force('collision', d3.forceCollide().radius(function(d) {{ return d.r + 4; }}).strength(0.8))
        .stop();

    for (var i = 0; i < 120; i++) simulation.tick();

    var bubbles = svg.selectAll('.bubble')
        .data(bubbleData)
        .enter()
        .append('g')
        .attr('transform', function(d) {{ return 'translate(' + d.x + ',' + d.y + ')'; }});

    bubbles.append('circle')
        .attr('r', function(d) {{ return d.r; }})
        .attr('fill', function(d) {{ return d.color; }})
        .attr('fill-opacity', 0.75)
        .attr('stroke', function(d) {{ return d.color; }})
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.3);

    bubbles.append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', '-0.2em')
        .style('fill', THEME.isLight ? '#1A1A2E' : '#FFFFFF')
        .style('font-size', function(d) {{ return d.r > 40 ? '13px' : '10px'; }})
        .style('font-family', "'IBM Plex Sans', sans-serif")
        .style('font-weight', '600')
        .style('pointer-events', 'none')
        .text(function(d) {{ return d.name; }});

    bubbles.append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', '1.2em')
        .style('fill', THEME.isLight ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.7)')
        .style('font-size', '10px')
        .style('font-family', "'JetBrains Mono', monospace")
        .style('pointer-events', 'none')
        .text(function(d) {{ return d.count.toLocaleString('es-ES'); }});

    bubbles.on('mouseover', function(event, d) {{
        showTooltip(event, '<strong>' + d.name + '</strong><br>Menciones: ' + d.count.toLocaleString('es-ES'));
    }})
    .on('mousemove', function(event) {{
        d3Tooltip.style('left', (event.pageX + 12) + 'px').style('top', (event.pageY - 28) + 'px');
    }})
    .on('mouseout', hideTooltip);
}})();

/* ===== D3 VIZ 5: WORD CLOUD ===== */
(function() {{
    var container = document.getElementById('wordCloud');
    if (!container || topicClusters.length === 0) return;

    var stopwords = new Set(['de', 'la', 'el', 'en', 'que', 'y', 'a', 'los', 'las', 'se', 'un', 'una', 'por', 'con', 'del', 'al']);
    var cloudColors = [THEME.accent, THEME.accentSecondary, THEME.isLight ? '#1A1A2E' : '#FFFFFF', THEME.text, THEME.accentGold];

    /* Collect words from cluster labels and keywords */
    var wordMap = {{}};
    topicClusters.forEach(function(cluster) {{
        var words = (cluster.keywords || []).concat([cluster.label]);
        words.forEach(function(w) {{
            var tokens = w.toLowerCase().split(/\\s+/);
            tokens.forEach(function(token) {{
                token = token.replace(/[^a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00fc0-9]/gi, '');
                if (token.length < 2 || stopwords.has(token)) return;
                if (!wordMap[token]) wordMap[token] = 0;
                wordMap[token] += cluster.mention_count || 1;
            }});
        }});
    }});

    var wordList = Object.keys(wordMap).map(function(w) {{
        return {{ text: w, count: wordMap[w] }};
    }});
    wordList.sort(function(a, b) {{ return b.count - a.count; }});
    wordList = wordList.slice(0, 50);

    if (wordList.length === 0) return;

    var maxCount = wordList[0].count;
    var minCount = wordList[wordList.length - 1].count;
    var range = maxCount - minCount || 1;

    wordList.forEach(function(w, i) {{
        var size = 14 + ((w.count - minCount) / range) * 42;  /* 14px to 56px */
        var color = cloudColors[i % cloudColors.length];
        var span = document.createElement('span');
        span.className = 'wordcloud-word fade-up';
        span.style.fontSize = size + 'px';
        span.style.color = color;
        span.style.fontFamily = "'IBM Plex Sans', sans-serif";
        span.style.fontWeight = size > 36 ? '700' : '400';
        span.style.transitionDelay = (i * 0.04) + 's';
        span.textContent = w.text;
        container.appendChild(span);
    }});
}})();

/* ===== INTERSECTION OBSERVER: FADE UP ===== */
(function() {{
    var observer = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                entry.target.classList.add('visible');
            }}
        }});
    }}, {{ threshold: 0.15 }});

    document.querySelectorAll('.fade-up').forEach(function(el) {{
        observer.observe(el);
    }});
}})();

/* ===== INTERSECTION OBSERVER: NAV DOTS ===== */
(function() {{
    var sections = document.querySelectorAll('.section, .methodology');
    var dots = document.querySelectorAll('.nav-dot');

    var observer = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting) {{
                var idx = entry.target.id.replace('sec-', '');
                dots.forEach(function(d) {{ d.classList.remove('active'); }});
                var activeDot = document.querySelector('.nav-dot[data-index="' + idx + '"]');
                if (activeDot) activeDot.classList.add('active');
            }}
        }});
    }}, {{ threshold: 0.3 }});

    sections.forEach(function(s) {{ observer.observe(s); }});

    dots.forEach(function(dot) {{
        dot.addEventListener('click', function() {{
            var idx = this.getAttribute('data-index');
            var target = document.getElementById('sec-' + idx);
            if (target) target.scrollIntoView({{ behavior: 'smooth' }});
        }});
    }});
}})();

/* ===== COUNT-UP ANIMATION ===== */
(function() {{
    function animateValue(el, start, end, duration) {{
        var startTime = performance.now();
        var suffix = el.getAttribute('data-suffix') || '';
        var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
        var useCommas = el.getAttribute('data-commas') === 'true';

        function update(currentTime) {{
            var elapsed = currentTime - startTime;
            var progress = Math.min(elapsed / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            var current = start + (end - start) * eased;
            var formatted;
            if (decimals > 0) {{
                formatted = current.toFixed(decimals);
            }} else {{
                formatted = Math.round(current).toString();
            }}
            if (useCommas) {{
                formatted = Number(formatted).toLocaleString('es-ES');
            }}
            el.textContent = formatted + suffix;
            if (progress < 1) requestAnimationFrame(update);
        }}
        requestAnimationFrame(update);
    }}

    var observer = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
            if (entry.isIntersecting && !entry.target.classList.contains('counted')) {{
                entry.target.classList.add('counted');
                var target = parseFloat(entry.target.getAttribute('data-target'));
                animateValue(entry.target, 0, target, 1500);
            }}
        }});
    }}, {{ threshold: 0.5 }});

    document.querySelectorAll('.countup').forEach(function(el) {{
        el.textContent = '0' + (el.getAttribute('data-suffix') || '');
        observer.observe(el);
    }});
}})();

/* ===== VENN DIAGRAM ===== */
(function() {{
    const container = document.getElementById('vennDiagram');
    if (!container || !intersectionData || !intersectionData.total) return;

    const w = 460, h = 260;
    const svg = d3.select(container).append('svg')
        .attr('viewBox', '0 0 ' + w + ' ' + h)
        .attr('width', '100%');

    const brandOnly = intersectionData.brand_only || 0;
    const actorOnly = intersectionData.actor_only || 0;
    const inter = intersectionData.intersection || 0;
    const brandPct = intersectionData.brand_only_pct || 0;
    const actorPct = intersectionData.actor_only_pct || 0;
    const interPct = intersectionData.intersection_pct || 0;
    const brandLabel = intersectionData.brand_label || '{html_mod.escape(venn_label_left)}';
    const actorLabel = intersectionData.actor_label || '{html_mod.escape(venn_label_right)}';

    // Two overlapping circles
    const cx1 = 165, cx2 = 295, cy = 120, r = 100;

    // Brand circle
    svg.append('circle').attr('cx', cx1).attr('cy', cy).attr('r', r)
        .attr('fill', THEME.accentSecondary).attr('opacity', 0.15)
        .attr('stroke', THEME.accentSecondary).attr('stroke-width', 1.5);

    // Actor circle
    svg.append('circle').attr('cx', cx2).attr('cy', cy).attr('r', r)
        .attr('fill', THEME.accent).attr('opacity', 0.15)
        .attr('stroke', THEME.accent).attr('stroke-width', 1.5);

    // Labels
    svg.append('text').attr('x', cx1 - 45).attr('y', cy - 10)
        .attr('text-anchor', 'middle').attr('fill', THEME.accentSecondary)
        .attr('font-family', 'JetBrains Mono').attr('font-size', '22px').attr('font-weight', '700')
        .text(brandOnly.toLocaleString());
    svg.append('text').attr('x', cx1 - 45).attr('y', cy + 12)
        .attr('text-anchor', 'middle').attr('fill', THEME.text)
        .attr('font-size', '10px').text(brandPct + '%');
    svg.append('text').attr('x', cx1 - 45).attr('y', cy + 28)
        .attr('text-anchor', 'middle').attr('fill', THEME.textMuted)
        .attr('font-size', '9px').attr('text-transform', 'uppercase').text('Solo ' + brandLabel);

    // Intersection
    svg.append('text').attr('x', (cx1 + cx2) / 2).attr('y', cy - 10)
        .attr('text-anchor', 'middle').attr('fill', THEME.accentGold)
        .attr('font-family', 'JetBrains Mono').attr('font-size', '22px').attr('font-weight', '700')
        .text(inter.toLocaleString());
    svg.append('text').attr('x', (cx1 + cx2) / 2).attr('y', cy + 12)
        .attr('text-anchor', 'middle').attr('fill', THEME.text)
        .attr('font-size', '10px').text(interPct + '%');
    svg.append('text').attr('x', (cx1 + cx2) / 2).attr('y', cy + 28)
        .attr('text-anchor', 'middle').attr('fill', THEME.textMuted)
        .attr('font-size', '9px').text('Ambos');

    // Actor only
    svg.append('text').attr('x', cx2 + 45).attr('y', cy - 10)
        .attr('text-anchor', 'middle').attr('fill', THEME.accent)
        .attr('font-family', 'JetBrains Mono').attr('font-size', '22px').attr('font-weight', '700')
        .text(actorOnly.toLocaleString());
    svg.append('text').attr('x', cx2 + 45).attr('y', cy + 12)
        .attr('text-anchor', 'middle').attr('fill', THEME.text)
        .attr('font-size', '10px').text(actorPct + '%');
    svg.append('text').attr('x', cx2 + 45).attr('y', cy + 28)
        .attr('text-anchor', 'middle').attr('fill', THEME.textMuted)
        .attr('font-size', '9px').text('Solo ' + actorLabel);

    // Top labels
    svg.append('text').attr('x', cx1 - 30).attr('y', 18)
        .attr('fill', THEME.accentSecondary).attr('font-family', 'Bebas Neue')
        .attr('font-size', '14px').attr('letter-spacing', '2px').text(brandLabel.toUpperCase());
    svg.append('text').attr('x', cx2 + 10).attr('y', 18)
        .attr('fill', THEME.accent).attr('font-family', 'Bebas Neue')
        .attr('font-size', '14px').attr('letter-spacing', '2px').text(actorLabel.toUpperCase());
}})();
</script>
</body>
</html>"""

    output_path.write_text(html_content, encoding="utf-8")
    logger.info("HTML report saved to %s", output_path)
    return output_path
