"""QA audit system for Report Builder — verifies numerical consistency,
narrative contradictions, and unsupported claims before delivery."""

import json
import re
import html as html_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from anthropic import Anthropic
from dotenv import load_dotenv
import os

from agents.shared.logger import get_logger

load_dotenv()

logger = get_logger("report-builder")

HAIKU_MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Layer 1: Numerical consistency
# ---------------------------------------------------------------------------

def _extract_numbers_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract all numbers + their context from report text."""
    findings = []  # type: List[Dict[str, Any]]

    # Match patterns like "27,847 menciones", "12.8%", "3.5x", etc.
    patterns = [
        (r'([\d,.]+)\s*%', 'percentage'),
        (r'([\d,.]+)\s*mencion', 'mention_count'),
        (r'([\d,.]+)\s*interaccion', 'engagement'),
        (r'([\d,.]+)\s*likes?', 'likes'),
        (r'([\d,.]+)\s*comentarios', 'comments'),
        (r'([\d,.]+)\s*veces', 'multiplier'),
        (r'([\d,.]+)\s*d[ií]as', 'days'),
        (r'ratio[^0-9]*([\d,.]+)[:\s]*([\d,.]+)', 'ratio'),
    ]

    for pattern, ptype in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            context_start = max(0, m.start() - 40)
            context_end = min(len(text), m.end() + 40)
            context = text[context_start:context_end].strip()
            findings.append({
                "type": ptype,
                "raw_match": m.group(0),
                "value": m.group(1).replace(',', '.').replace('.', '', m.group(1).count('.') - 1) if '.' in m.group(1) else m.group(1).replace(',', ''),
                "context": context,
                "position": m.start(),
            })

    return findings


def _check_numerical_consistency(
    report_text: str,
    metrics: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Cross-reference numbers in text against actual metrics."""
    checks = []  # type: List[Dict[str, Any]]

    total_mentions = metrics.get("total_mentions", 0)
    sentiment = metrics.get("sentiment_breakdown", {})
    actor_breakdown = metrics.get("actor_breakdown", {})
    avg_engagement = metrics.get("avg_engagement")
    intersection = metrics.get("intersection", {})

    # Build reference values
    references = {
        "total_mentions": total_mentions,
        "avg_engagement": avg_engagement,
    }

    # Sentiment percentages
    for key, val in sentiment.items():
        if isinstance(val, dict):
            pct = val.get("percentage", 0)
            references[f"sentiment_{key}_pct"] = pct
            references[f"sentiment_{key}_count"] = val.get("count", 0)

    # Actor percentages
    actor_total = sum(actor_breakdown.values()) if actor_breakdown else 1
    for actor, count in actor_breakdown.items():
        references[f"actor_{actor}_count"] = count
        references[f"actor_{actor}_pct"] = round(count / max(actor_total, 1) * 100, 1)

    # Actor-separated metrics (sentiment per actor)
    actor_metrics = metrics.get("actor_metrics", {})
    for actor_name, am in actor_metrics.items():
        if not isinstance(am, dict):
            continue
        am_sentiment = am.get("sentiment_breakdown", {})
        for skey, sval in am_sentiment.items():
            if isinstance(sval, dict):
                references[f"actor_{actor_name}_{skey}_pct"] = sval.get("percentage", 0)
                references[f"actor_{actor_name}_{skey}_count"] = sval.get("count", 0)
        if am.get("total_mentions"):
            references[f"actor_{actor_name}_total"] = am["total_mentions"]
        if am.get("avg_engagement") is not None:
            references[f"actor_{actor_name}_engagement"] = am["avg_engagement"]

    # Intersection
    if intersection:
        for key in ("brand_only", "actor_only", "intersection", "neither"):
            references[f"inter_{key}"] = intersection.get(key, 0)
            references[f"inter_{key}_pct"] = intersection.get(f"{key}_pct", 0)

    # Build a set of ALL known valid numbers from the data (counts, not percentages)
    valid_counts = {total_mentions}  # type: set
    for key, val in sentiment.items():
        if isinstance(val, dict) and "count" in val:
            valid_counts.add(val["count"])
    for actor, cnt in actor_breakdown.items():
        valid_counts.add(cnt)
    if intersection:
        for key in ("brand_only", "actor_only", "intersection", "neither"):
            v = intersection.get(key)
            if v is not None:
                valid_counts.add(v)
    # Add actor-separated mention counts
    for actor_name, am in actor_metrics.items():
        if isinstance(am, dict) and am.get("total_mentions"):
            valid_counts.add(am["total_mentions"])
        am_sent = am.get("sentiment_breakdown", {}) if isinstance(am, dict) else {}
        for sval in am_sent.values():
            if isinstance(sval, dict) and "count" in sval:
                valid_counts.add(sval["count"])
    # Add top source/author counts
    top_sources = metrics.get("top_sources", [])
    for item in top_sources:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            valid_counts.add(int(item[1]))
    # Add topic cluster counts
    for tc in metrics.get("topic_clusters", []):
        mc = tc.get("mention_count")
        if mc is not None:
            valid_counts.add(int(mc))

    # Check: numbers followed by "menciones" — cross-reference against ALL known counts
    mention_pattern = re.compile(r'([\d,\.]+)\s*mencion', re.IGNORECASE)
    for m in mention_pattern.finditer(report_text):
        raw = m.group(1).replace(',', '').replace('.', '')
        try:
            found = int(raw)
        except ValueError:
            continue
        # Check if this number matches any known valid count (±5%)
        matched_any = False
        for vc in valid_counts:
            if vc == 0:
                continue
            diff_pct = abs(found - vc) / vc * 100
            if diff_pct <= 5:
                matched_any = True
                break
        if matched_any:
            status = "PASS"
        elif found == total_mentions:
            status = "PASS"
        else:
            # Only flag as WARNING (not ERROR) — Claude may cite derived stats
            status = "WARNING"
        checks.append({
            "check": "Mención numérica en texto",
            "expected": "coincide con dato conocido" if matched_any else f"total={total_mentions:,}",
            "found": f"{found:,}",
            "status": status,
            "context": report_text[max(0, m.start()-30):m.end()+30],
        })

    # Check: sentiment percentages mentioned in text
    # Only flag percentages near relevant keywords
    _pct_keywords = (
        "sentimiento", "menciones", "mención", "positivo", "negativo", "neutro",
        "engagement", "alcance", "volumen", "clasificar", "actor", "conversación",
    )
    pct_pattern = re.compile(r'([\d,.]+)\s*%', re.IGNORECASE)
    for m in pct_pattern.finditer(report_text):
        raw = m.group(1).replace(',', '.')
        try:
            found_pct = float(raw)
        except ValueError:
            continue

        # Only check percentages that appear near relevant keywords (within 80 chars)
        proximity_start = max(0, m.start() - 80)
        proximity_end = min(len(report_text), m.end() + 80)
        proximity_text = report_text[proximity_start:proximity_end].lower()
        if not any(kw in proximity_text for kw in _pct_keywords):
            continue

        # Find closest matching reference percentage (within ±5%)
        context = report_text[max(0, m.start()-60):m.end()+60].lower()
        best_match = None
        best_diff = 999.0
        for ref_key, ref_val in references.items():
            if ref_val is None or not isinstance(ref_val, (int, float)):
                continue
            if "pct" not in ref_key:
                continue
            diff = abs(ref_val - found_pct)
            if diff < best_diff:
                best_diff = diff
                best_match = (ref_key, ref_val)

        if best_match and best_diff <= 5.0:
            ref_key, ref_val = best_match
            if best_diff <= 2.0:
                status = "PASS"
            elif best_diff <= 5.0:
                status = "WARNING"
            else:
                status = "ERROR"
            checks.append({
                "check": f"Porcentaje: {ref_key}",
                "expected": f"{ref_val}%",
                "found": f"{found_pct}%",
                "status": status,
                "context": context.strip(),
            })

    # Check: engagement average
    if avg_engagement is not None:
        eng_pattern = re.compile(r'([\d,.]+)\s*(?:interacciones?\s*promedio|engagement\s*promedio|promedio.*?interaccion)', re.IGNORECASE)
        for m in eng_pattern.finditer(report_text):
            raw = m.group(1).replace(',', '.')
            try:
                found_eng = float(raw)
            except ValueError:
                continue
            diff = abs(found_eng - avg_engagement)
            status = "PASS" if diff < 1 else ("WARNING" if diff < 5 else "ERROR")
            checks.append({
                "check": "Engagement promedio",
                "expected": f"{avg_engagement:.2f}",
                "found": f"{found_eng:.2f}",
                "status": status,
                "context": report_text[max(0, m.start()-30):m.end()+30],
            })

    # Add passed checks for key metrics that weren't mentioned (informational)
    if not any(c["check"] == "Total menciones en texto" for c in checks):
        checks.append({
            "check": "Total menciones en texto",
            "expected": f"{total_mentions:,}",
            "found": "No mencionado",
            "status": "WARNING",
            "context": "",
        })

    return checks


# ---------------------------------------------------------------------------
# Layer 2: Narrative contradiction detection (via Haiku)
# ---------------------------------------------------------------------------

def _check_contradictions(
    report_text: str,
    api_key: str,
) -> List[Dict[str, Any]]:
    """Use Haiku to detect contradictions between narrative sections."""
    client = Anthropic(api_key=api_key)

    system = (
        "Eres un analista de control de calidad revisando un informe de inteligencia social. "
        "Lee las siguientes secciones narrativas e identifica contradicciones donde una sección "
        "dice algo inconsistente con otra. Para cada contradicción lista:\n"
        "- Sección A (cita)\n- Sección B (cita)\n- Por qué se contradicen\n"
        "- Severidad: HIGH / MEDIUM / LOW\n"
        "Si no hay contradicciones, responde: NONE FOUND\n"
        "Responde en español. Formato JSON array."
    )

    user = f"Revisa este informe:\n\n{report_text[:6000]}"

    try:
        message = client.messages.create(
            model=HAIKU_MODEL, max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        response = message.content[0].text.strip()

        if "NONE FOUND" in response.upper() or "ninguna contradicción" in response.lower():
            return []

        # Try to parse JSON
        cleaned = re.sub(r'^```json\s*', '', response)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            items = json.loads(cleaned)
            if isinstance(items, list):
                return items
        except json.JSONDecodeError:
            pass

        # Fallback: return as single finding
        return [{"section_a": "", "section_b": "", "explanation": response, "severity": "MEDIUM"}]

    except Exception as e:
        logger.error("Contradiction check failed: %s", e)
        return [{"section_a": "", "section_b": "", "explanation": f"Error en verificación: {e}", "severity": "LOW"}]


# ---------------------------------------------------------------------------
# Layer 3: Unsupported claims detection (via Haiku)
# ---------------------------------------------------------------------------

def _check_unsupported_claims(
    report_text: str,
    metrics: Dict[str, Any],
    api_key: str,
) -> List[Dict[str, Any]]:
    """Use Haiku to detect claims not supported by the data."""
    client = Anthropic(api_key=api_key)

    # Build slim metrics — include actor_metrics and volume_by_date (compact)
    metrics_slim = {}
    for k, v in metrics.items():
        if k == "topic_clusters":
            continue  # too large, not cited numerically
        elif k == "actor_metrics":
            # Include only sentiment breakdowns per actor
            compact_actors = {}
            for aname, adata in (v if isinstance(v, dict) else {}).items():
                if isinstance(adata, dict):
                    compact_actors[aname] = {
                        "total_mentions": adata.get("total_mentions", 0),
                        "sentiment_breakdown": adata.get("sentiment_breakdown", {}),
                        "avg_engagement": adata.get("avg_engagement"),
                    }
            metrics_slim["actor_metrics"] = compact_actors
        elif k == "volume_by_date" and isinstance(v, dict) and len(v) > 20:
            # Compact: only include dates with significant volume
            metrics_slim[k] = {d: c for d, c in v.items() if c >= 5}
        else:
            metrics_slim[k] = v

    system = (
        "Eres un auditor de informes verificando precisión factual. "
        "Verifica afirmaciones del texto contra el JSON de métricas proporcionado.\n\n"
        "REGLAS DE SEVERIDAD (respeta estrictamente):\n"
        "- HIGH: SOLO cuando un número específico CONTRADICE directamente un dato en las métricas "
        "(ej: dice '60% positivo' pero las métricas dicen 13%). Errores factuales claros.\n"
        "- MEDIUM: Número no encontrado directamente en métricas pero podría ser un cálculo "
        "derivado válido (ej: porcentajes calculados de volume_by_date, sumas de subcategorías). "
        "También cuantificadores vagos reemplazables por datos.\n"
        "- LOW: Afirmaciones interpretativas que no contradicen los datos.\n\n"
        "IMPORTANTE: Los porcentajes derivados de volume_by_date (ej: '61% del volumen desde fecha X'), "
        "de actor_metrics (ej: '21% negativo para Avianca'), o de intersection (ej: '7.7% brand_only') "
        "son datos VÁLIDOS aunque no aparezcan como porcentaje literal en las métricas — "
        "el analista los calculó a partir de los datos. NO los marques como HIGH.\n\n"
        "Para cada hallazgo: claim, issue, suggestion, severity.\n"
        "Si todo está correcto: ALL VERIFIED\n"
        "Responde en español. Formato JSON array."
    )

    user = (
        f"== MÉTRICAS ==\n{json.dumps(metrics_slim, ensure_ascii=False, indent=2, default=str)[:3000]}\n\n"
        f"== TEXTO NARRATIVO ==\n{report_text[:5000]}"
    )

    try:
        message = client.messages.create(
            model=HAIKU_MODEL, max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        response = message.content[0].text.strip()

        if "ALL VERIFIED" in response.upper() or "todo correcto" in response.lower():
            return []

        cleaned = re.sub(r'^```json\s*', '', response)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            items = json.loads(cleaned)
            if isinstance(items, list):
                return items
        except json.JSONDecodeError:
            pass

        return [{"claim": "", "issue": response, "suggestion": "", "severity": "MEDIUM"}]

    except Exception as e:
        logger.error("Unsupported claims check failed: %s", e)
        return [{"claim": "", "issue": f"Error en verificación: {e}", "suggestion": "", "severity": "LOW"}]


# ---------------------------------------------------------------------------
# QA Report HTML generation
# ---------------------------------------------------------------------------

def _build_qa_html(
    client_name: str,
    period: str,
    numerical_checks: List[Dict[str, Any]],
    contradictions: List[Dict[str, Any]],
    unsupported: List[Dict[str, Any]],
) -> str:
    """Generate the QA report HTML."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    errors = sum(1 for c in numerical_checks if c["status"] == "ERROR")
    errors += sum(1 for c in contradictions if (str(c.get("severity") or "")).upper() == "HIGH")
    errors += sum(1 for c in unsupported if (str(c.get("severity") or "")).upper() == "HIGH")

    warnings = sum(1 for c in numerical_checks if c["status"] == "WARNING")
    warnings += sum(1 for c in contradictions if (str(c.get("severity") or "")).upper() == "MEDIUM")
    warnings += sum(1 for c in unsupported if (str(c.get("severity") or "")).upper() == "MEDIUM")

    passed = sum(1 for c in numerical_checks if c["status"] == "PASS")

    if errors > 0:
        overall = "NO ENVIAR"
        overall_color = "#FF1B6B"
        overall_icon = "&#10060;"
    elif warnings > 0:
        overall = "REVISAR"
        overall_color = "#FFB800"
        overall_icon = "&#9888;&#65039;"
    else:
        overall = "APROBADO"
        overall_color = "#00D4FF"
        overall_icon = "&#9989;"

    # Build numerical checks table
    num_rows = ""
    for c in numerical_checks:
        color = {"PASS": "#00D4FF", "WARNING": "#FFB800", "ERROR": "#FF1B6B"}.get(c["status"], "#5A6378")
        num_rows += f"""<tr>
            <td style="padding:10px 12px;color:#fff;">{html_mod.escape(c["check"])}</td>
            <td style="padding:10px 12px;color:#A0AEC0;font-family:'JetBrains Mono',monospace;">{html_mod.escape(str(c["expected"]))}</td>
            <td style="padding:10px 12px;color:#A0AEC0;font-family:'JetBrains Mono',monospace;">{html_mod.escape(str(c["found"]))}</td>
            <td style="padding:10px 12px;"><span style="background:{color}22;color:{color};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">{c["status"]}</span></td>
        </tr>"""

    # Build contradiction cards
    contra_html = ""
    if not contradictions:
        contra_html = '<p style="color:#00D4FF;font-size:14px;">&#9989; No se detectaron contradicciones narrativas.</p>'
    else:
        for c in contradictions:
            sev = c.get("severity", "MEDIUM").upper()
            sev_color = {"HIGH": "#FF1B6B", "MEDIUM": "#FFB800", "LOW": "#5A6378"}.get(sev, "#5A6378")
            explanation = html_mod.escape(c.get("explanation", c.get("issue", "")))
            section_a = html_mod.escape(str(c.get("section_a", c.get("seccion_a", ""))))
            section_b = html_mod.escape(str(c.get("section_b", c.get("seccion_b", ""))))
            contra_html += f"""<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-left:3px solid {sev_color};border-radius:0 12px 12px 0;padding:20px;margin-bottom:12px;">
                <span style="background:{sev_color}22;color:{sev_color};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">{sev}</span>
                {f'<p style="color:#A0AEC0;font-size:13px;margin-top:10px;"><strong>Sección A:</strong> {section_a}</p>' if section_a else ''}
                {f'<p style="color:#A0AEC0;font-size:13px;margin-top:6px;"><strong>Sección B:</strong> {section_b}</p>' if section_b else ''}
                <p style="color:#fff;font-size:14px;margin-top:10px;">{explanation}</p>
            </div>"""

    # Build unsupported claims cards
    unsup_html = ""
    if not unsupported:
        unsup_html = '<p style="color:#00D4FF;font-size:14px;">&#9989; Todas las afirmaciones están respaldadas por datos.</p>'
    else:
        for c in unsupported:
            sev = c.get("severity", "MEDIUM").upper()
            sev_color = {"HIGH": "#FF1B6B", "MEDIUM": "#FFB800", "LOW": "#5A6378"}.get(sev, "#5A6378")
            claim = html_mod.escape(str(c.get("claim", c.get("afirmacion", ""))))
            issue = html_mod.escape(str(c.get("issue", c.get("problema", ""))))
            suggestion = html_mod.escape(str(c.get("suggestion", c.get("sugerencia", ""))))
            unsup_html += f"""<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-left:3px solid {sev_color};border-radius:0 12px 12px 0;padding:20px;margin-bottom:12px;">
                <span style="background:{sev_color}22;color:{sev_color};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">{sev}</span>
                {f'<p style="color:#FFB800;font-size:13px;margin-top:10px;font-style:italic;">"{claim}"</p>' if claim else ''}
                <p style="color:#fff;font-size:14px;margin-top:10px;">{issue}</p>
                {f'<p style="color:#00D4FF;font-size:13px;margin-top:8px;"><strong>Sugerencia:</strong> {suggestion}</p>' if suggestion else ''}
            </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QA Report — {html_mod.escape(client_name)}</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'IBM Plex Sans',system-ui,sans-serif;background:#050D1A;color:#A0AEC0;line-height:1.6;padding:40px;}}
.container{{max-width:1000px;margin:0 auto;}}
h1{{font-family:'Bebas Neue',sans-serif;font-size:36px;color:#fff;letter-spacing:3px;}}
h2{{font-family:'Bebas Neue',sans-serif;font-size:24px;color:#fff;letter-spacing:2px;margin:40px 0 16px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.06);}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{text-align:left;padding:10px 12px;color:#FF1B6B;font-size:11px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid rgba(255,27,107,0.3);}}
tr{{border-bottom:1px solid rgba(255,255,255,0.04);}}
</style>
</head>
<body>
<div class="container">
<h1>AUDITORÍA DE CALIDAD</h1>
<p style="color:#5A6378;font-size:13px;margin-top:4px;">{html_mod.escape(client_name)} &bull; {html_mod.escape(period)} &bull; {now}</p>

<div style="background:rgba(255,255,255,0.03);border:1px solid {overall_color}44;border-left:4px solid {overall_color};border-radius:0 16px 16px 0;padding:24px;margin:32px 0;">
    <div style="display:flex;align-items:center;gap:16px;">
        <span style="font-size:32px;">{overall_icon}</span>
        <div>
            <div style="font-family:'Bebas Neue',sans-serif;font-size:28px;color:{overall_color};letter-spacing:2px;">{overall}</div>
            <div style="font-size:13px;color:#A0AEC0;">
                <span style="color:#FF1B6B;font-weight:700;">{errors} errores</span> &bull;
                <span style="color:#FFB800;font-weight:700;">{warnings} advertencias</span> &bull;
                <span style="color:#00D4FF;font-weight:700;">{passed} verificaciones pasadas</span>
            </div>
        </div>
    </div>
</div>

<h2>VERIFICACIONES NUMÉRICAS</h2>
<table>
<thead><tr><th>Verificación</th><th>Esperado</th><th>Encontrado</th><th>Estado</th></tr></thead>
<tbody>{num_rows}</tbody>
</table>

<h2>CONTRADICCIONES NARRATIVAS</h2>
{contra_html}

<h2>AFIRMACIONES SIN SOPORTE</h2>
{unsup_html}

<h2>VERIFICACIONES APROBADAS</h2>
<details style="margin-top:8px;">
<summary style="color:#00D4FF;cursor:pointer;font-size:14px;">{passed} verificaciones pasaron correctamente (click para expandir)</summary>
<div style="margin-top:12px;">
{"".join(f'<p style="color:#5A6378;font-size:12px;margin:4px 0;">✓ {html_mod.escape(c["check"])}: {html_mod.escape(str(c["expected"]))}</p>' for c in numerical_checks if c["status"] == "PASS")}
</div>
</details>

<div style="margin-top:48px;padding-top:24px;border-top:1px solid rgba(255,255,255,0.04);text-align:center;">
    <p style="color:#5A6378;font-size:12px;">Este reporte fue auditado por el Sistema de QA de Epical Intelligence.</p>
    <p style="color:#5A6378;font-size:12px;">Revisión final requerida antes de envío al cliente.</p>
    <p style="color:#FF1B6B;font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:3px;margin-top:12px;">EPICAL</p>
</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main QA function
# ---------------------------------------------------------------------------

def run_qa_audit(
    report_text: str,
    metrics: Dict[str, Any],
    client_name: str,
    period: str,
    output_path: Union[str, Path],
    use_ai: bool = True,
) -> Dict[str, Any]:
    """Run full QA audit on a generated report.

    Args:
        report_text: The Claude-generated narrative text.
        metrics: The calculated metrics dictionary.
        client_name: Client name.
        period: Reporting period.
        output_path: Path to save the QA HTML report.
        use_ai: Whether to run AI-powered checks (layers 2 & 3).

    Returns:
        Dict with qa_status, qa_errors, qa_warnings, qa_file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Running QA audit for %s...", client_name)

    # Layer 1: Numerical consistency
    logger.info("QA Layer 1: Numerical consistency checks...")
    numerical_checks = _check_numerical_consistency(report_text, metrics)
    logger.info("Layer 1: %d checks (%d pass, %d warn, %d error)",
                len(numerical_checks),
                sum(1 for c in numerical_checks if c["status"] == "PASS"),
                sum(1 for c in numerical_checks if c["status"] == "WARNING"),
                sum(1 for c in numerical_checks if c["status"] == "ERROR"))

    contradictions = []  # type: List[Dict[str, Any]]
    unsupported = []  # type: List[Dict[str, Any]]

    if use_ai:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            # Layer 2: Narrative contradictions
            logger.info("QA Layer 2: Narrative contradiction detection...")
            contradictions = _check_contradictions(report_text, api_key)
            logger.info("Layer 2: %d contradictions found", len(contradictions))

            # Layer 3: Unsupported claims
            logger.info("QA Layer 3: Unsupported claims detection...")
            unsupported = _check_unsupported_claims(report_text, metrics, api_key)
            logger.info("Layer 3: %d unsupported claims found", len(unsupported))
        else:
            logger.warning("No ANTHROPIC_API_KEY — skipping AI-powered QA checks")

    # Calculate overall status
    errors = sum(1 for c in numerical_checks if c["status"] == "ERROR")
    errors += sum(1 for c in contradictions if (str(c.get("severity") or "")).upper() == "HIGH")
    errors += sum(1 for c in unsupported if (str(c.get("severity") or "")).upper() == "HIGH")

    warnings = sum(1 for c in numerical_checks if c["status"] == "WARNING")
    warnings += sum(1 for c in contradictions if (str(c.get("severity") or "")).upper() == "MEDIUM")
    warnings += sum(1 for c in unsupported if (str(c.get("severity") or "")).upper() == "MEDIUM")

    if errors > 0:
        qa_status = "NO ENVIAR"
    elif warnings > 0:
        qa_status = "REVISAR"
    else:
        qa_status = "APROBADO"

    # Generate QA HTML
    qa_html = _build_qa_html(client_name, period, numerical_checks, contradictions, unsupported)
    output_path.write_text(qa_html, encoding="utf-8")
    logger.info("QA report saved to %s — Status: %s (%d errors, %d warnings)",
                output_path, qa_status, errors, warnings)

    return {
        "qa_status": qa_status,
        "qa_errors": errors,
        "qa_warnings": warnings,
        "qa_file": str(output_path),
    }
