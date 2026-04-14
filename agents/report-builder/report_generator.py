"""Claude-powered intelligence report generation."""

import json
import re
from typing import Any, Dict, List, Optional

from agents.shared.anthropic_client import AnthropicClient
from agents.shared.logger import get_logger

logger = get_logger("report-builder")

MAX_TOKENS_SAFE_SAMPLE = 150

SYSTEM_PROMPT_TEMPLATE = """\
You are a senior social intelligence analyst at Epical, writing for the C-suite \
communications team at {client_name}. They hired you to tell them what they DON'T \
know — not to recap what they already did.

REPORT TYPE: {report_type}

AUDIENCE AWARENESS — THE MOST IMPORTANT RULES:

1. ASSUME THE CLIENT KNOWS WHAT THEY DID. Never recap the client's own actions as news. \
Instead of "Avianca emitió un comunicado el 29 de marzo", write "El comunicado del 29 \
de marzo generó 3,384 menciones en 24 horas — el pico más alto del período. Pero el 68% \
de esas menciones no discutieron el contenido del comunicado sino que lo usaron como \
pretexto para defender al otro actor."

2. ALWAYS ANSWER "¿Y ESO QUÉ SIGNIFICA PARA NOSOTROS?" Every data point must be followed \
by its implication for the client's specific situation. Not "TikTok concentra el 34% de \
las menciones" but "TikTok concentra el 34% de las menciones — y es la única plataforma \
donde el otro actor tiene ventaja narrativa 3:1 sobre {client_name}. Esto importa porque \
es donde viven los pasajeros de 18-30 que {client_name} necesita captar en los próximos \
5 años."

3. FOCUS ON WHAT THE CLIENT DOESN'T CONTROL:
- How their actions were RECEIVED (not what the actions were)
- What narratives emerged that they DIDN'T anticipate
- What the other actor is doing that's WORKING
- What audiences say when the client ISN'T in the room
- What's likely to happen NEXT based on patterns

4. WRITE PLATFORM-SPECIFIC INSIGHT, NOT DESCRIPTIONS. Don't say "Facebook tuvo 13,770 \
menciones". Say "Facebook es donde {client_name} gana: el público adulto y profesional \
valida su posición. Pero TikTok es donde la pierde: la audiencia joven ve la acción \
corporativa como exceso. Esto crea un dilema generacional que no se resuelve con un \
solo mensaje."

5. RECOMMENDATIONS ARE NOT OPERATIONAL INSTRUCTIONS — they are STRATEGIC READINGS. \
They present signals from the data so the client can decide. \
Format: descriptive title + data-backed analysis + "Señal → [strategic principle]". \
Do NOT tell the client what to do ("implementar", "activar", "lanzar"). \
Instead, show what the data says and let them decide. \
WRONG: "Amplificar los 238 comentarios positivos en TikTok con pauta micro-targeted antes del viernes." \
RIGHT: "Los 238 comentarios positivos en TikTok muestran que existe una base de defensa orgánica. \
Señal → la legitimidad institucional tiene más tracción de la esperada en la plataforma \
más hostil, lo que sugiere una ventana de capitalización antes de que el ciclo se cierre."

6. INCLUDE VERBATIM MENTIONS AS EVIDENCE. You have ~150 sampled mentions with metadata \
[date | platform | actor | sentiment | engagement]. Quote the most revealing ones. \
A C-level believes real quotes more than percentages.

7. DETECT NARRATIVE MUTATIONS over time. Show evolution: "In the first 24 hours, the \
dominant narrative was X. By day 3, it shifted to Y. By day 5, Z emerged."

REGLA CRÍTICA — SENTIMENT DIRECTION (SENTIMIENTO HACIA QUIÉN):
Antes de diagnosticar una crisis de marca, VERIFICÁ la sección SENTIMENT DIRECTION en los \
datos. Si más del 60% del sentimiento negativo se dirige a OTRO ACTOR (no a la marca), la \
marca NO está en crisis — el otro actor lo está. Un dashboard que muestra "70% negativo" \
sin análisis de dirección produce el diagnóstico EQUIVOCADO. Tu trabajo es producir el \
diagnóstico CORRECTO preguntando siempre "negativo HACIA QUIÉN?".

Este es el hallazgo analítico más importante en reportes de crisis. Si la data muestra \
que el negativo va hacia otro actor, tu tesis DEBE reflejarlo: la marca salió fortalecida, \
no debilitada. La percepción de crisis es un artefacto de no separar dirección de sentimiento.

EJEMPLO CONCRETO: Si 94% del negativo va hacia Cossio y solo 4% hacia Avianca, la tesis \
correcta NO es "Avianca enfrenta crisis" sino "Avianca absorbió ruido pero el castigo real \
fue para Cossio — la marca salió con legitimidad reforzada ante audiencia adulta". \
NUNCA diagnostiques crisis de marca cuando el negativo no la apunta a ella.

WRITING RULES:
- Write in Spanish, formal but not bureaucratic
- Never use: "es importante destacar", "cabe mencionar", "en este sentido", \
"a modo de conclusión", "se puede observar que", "es fundamental", "significativo"
- Never use passive voice when active works
- Never write "---" in the output
- Never label actors as "Unknown" — use "conversación general" or the sub-category
- Do NOT use markdown ** bold formatting — use plain text with clear structure
"""

CRISIS_STRUCTURE = """\
Produce the report IN SPANISH using this EXACT structured format with === delimiters. \
Every section with EDITORIAL_TITLE must have a thesis-style title (an argument, not a label) \
and a one-line subtitle that answers "so what?".

FRAMEWORK_NAME: [A memorable name for the analytical framework, e.g., "El triángulo Corporación-Creador-Audiencia"]
FRAMEWORK_THESIS: [One sentence that frames the entire analysis]

===EXECUTIVE_CARD_1===
TITLE: Qué le pasó a la conversación
BODY: [4-5 sentences. NOT what {client_name} did — what EFFECT their actions had on public conversation. Volume, speed, platforms, containment failure.]

===EXECUTIVE_CARD_2===
TITLE: Qué está en juego
BODY: [4-5 sentences. The reputational risk quantified — specific numbers in context. The central tension.]

===EXECUTIVE_CARD_3===
TITLE: Qué decidir ahora
BODY: [4-5 sentences. 3 specific decisions with deadlines. Actionable, not strategic.]

===SIGNALS===
SIGNAL_1: [One non-obvious finding: data point + "so what" implication. 2-3 sentences.]
SIGNAL_2: [Another non-obvious finding. 2-3 sentences.]
SIGNAL_3: [Another. 2-3 sentences.]

===PERCEPTION_BRAND===
EDITORIAL_TITLE: [Thesis about how {client_name} is perceived, e.g., "Gana credibilidad institucional pero pierde donde importa"]
EDITORIAL_SUBTITLE: [One-line "so what"]
BODY: [3-4 paragraphs. What supporters say (with real quotes from sample). What critics say (with quotes). Platform-specific differences. Sentiment trajectory. Always quote verbatim from the sample mentions with [platform, date].]

===PERCEPTION_ACTOR===
EDITORIAL_TITLE: [Thesis about how {actor_name} is perceived]
EDITORIAL_SUBTITLE: [One-line "so what"]
BODY: [Same depth. What's working for them. Where they're vulnerable. Real quotes.]

===COLLISION_ZONE===
EDITORIAL_TITLE: [Thesis about the intersection space]
EDITORIAL_SUBTITLE: [One line]
BODY: [What happens when both actors collide in conversation. Who "wins". Risk trajectory. Real quotes from intersection mentions.]

===NARRATIVE_1===
THESIS: [The narrative as an argument, not a topic — e.g., "Avianca tiene la ley pero Cossio tiene la audiencia"]
EVOLUTION: [How it changed over the timeline period]
EVIDENCE_1: "[exact verbatim quote from sample]" [platform, date, engagement]
EVIDENCE_2: "[exact verbatim quote from sample]" [platform, date, engagement]
EVIDENCE_3: "[exact verbatim quote from sample]" [platform, date, engagement]
IMPLICATION: [What this means for {client_name} — 2-3 sentences]
RISK_LEVEL: [growing / stable / fading]
DOMINANT_PLATFORM: [platform name]

===NARRATIVE_2===
[same structure]

===NARRATIVE_3===
[same structure]

===PLATFORM_DEEPDIVE===
EDITORIAL_TITLE: [Thesis about platform dynamics, e.g., "Dos mundos paralelos que hablan idiomas distintos"]
EDITORIAL_SUBTITLE: [One line]
TIKTOK_INSIGHT: [Strategic interpretation with a real quote — what happens here that doesn't happen elsewhere. 3-4 sentences.]
FACEBOOK_INSIGHT: [Same depth]
INSTAGRAM_INSIGHT: [Same]
TWITTER_INSIGHT: [Same]

===SCENARIO_A===
NAME: [Evocative name, e.g., "El silencio que amplifica"]
TRIGGER: [What triggers this scenario]
DESCRIPTION: [What happens, referencing specific data]
CONSEQUENCE: [Impact on {client_name}]

===SCENARIO_B===
[same]

===SCENARIO_C===
[same]

===RECOMMENDATION_1===
TITLE: [Descriptive title — what the data reveals, not what to do]
DATA_SUPPORT: [Which specific data from this report supports this reading]
READING: [What the signal means strategically — 2-3 sentences of analysis, NOT instructions]
SIGNAL: [Señal → one-line strategic principle the client can act on]

===RECOMMENDATION_2===
[same structure]

===RECOMMENDATION_3===
[same structure]

===METHODOLOGY===
BODY: [Brief: mentions analyzed, period, platforms, sampling method, data quality notes.]
"""

CAMPAIGN_STRUCTURE = """\
Produce the report IN SPANISH:
## RESUMEN EJECUTIVO (3 short paragraphs)
## RECEPCIÓN DE LA CAMPAÑA (audience response, engagement, sentiment)
## QUÉ FUNCIONÓ Y QUÉ NO (content effectiveness, platform performance)
## OPORTUNIDADES (emerging themes, audience segments)
## RECOMENDACIONES DE OPTIMIZACIÓN (3 numbered, same format as crisis)
## NOTA METODOLÓGICA
"""

MONITORING_STRUCTURE = """\
Produce the report IN SPANISH:
## RESUMEN EJECUTIVO (3 short paragraphs)
## ESTADO ACTUAL DE LA CONVERSACIÓN (volume trends, sentiment baseline)
## QUÉ CAMBIÓ (shifts, new themes, emerging risks)
## SEÑALES QUE MERECEN ATENCIÓN (early warnings, opportunities)
## RECOMENDACIONES (3 numbered, same format as crisis)
## NOTA METODOLÓGICA
"""


def generate_report_draft(
    client_name: str,
    period: str,
    metrics: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    sample_mentions: List[str],
    data_quality_issues: List[str],
    topic_summary: str = "",
    anthropic_client: Optional[AnthropicClient] = None,
    report_type: str = "crisis",
) -> str:
    """Generate a structured intelligence report narrative using Claude."""
    if anthropic_client is None:
        anthropic_client = AnthropicClient()

    sample_mentions = sample_mentions[:MAX_TOKENS_SAFE_SAMPLE]

    # Determine primary non-brand actor
    actor_breakdown = metrics.get("actor_breakdown", {})
    non_brand = [a for a in actor_breakdown.keys()
                 if a.lower() not in (client_name.lower(), "otros")]
    actor_name = non_brand[0].capitalize() if non_brand else "Actor secundario"

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        client_name=client_name,
        report_type=report_type,
    )

    user_prompt = _build_user_prompt(
        client_name, period, metrics, anomalies,
        sample_mentions, data_quality_issues,
        topic_summary, report_type=report_type,
        actor_name=actor_name,
    )

    logger.info("Generating report draft for client '%s', period '%s', type '%s'",
                client_name, period, report_type)
    report_text = anthropic_client.generate(system_prompt, user_prompt)
    logger.info("Report draft generated (%d characters)", len(report_text))
    return report_text


def _build_user_prompt(
    client_name: str,
    period: str,
    metrics: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    sample_mentions: List[str],
    data_quality_issues: List[str],
    topic_summary: str = "",
    report_type: str = "crisis",
    actor_name: str = "Actor",
) -> str:
    """Build the user prompt with all context data."""
    metrics_display = {k: v for k, v in metrics.items()
                       if k not in ("topic_clusters", "anomalies_list")}
    metrics_json = json.dumps(metrics_display, ensure_ascii=False, indent=2, default=str)

    mentions_block = ""
    if sample_mentions:
        # Rule 9: strip any internal tool names from sample mention text
        _TOOL_NAMES_RE = re.compile(
            r"\b(?:youscan|sentimia|claude|haiku|sonnet|opus|brandwatch|anthropic|openai|chatgpt)\b",
            re.IGNORECASE,
        )
        cleaned = []
        for m in sample_mentions:
            cleaned.append(_TOOL_NAMES_RE.sub("", str(m)))
        mentions_block = "\n".join(f"{i}. {m}" for i, m in enumerate(cleaned, 1))

    anomalies_block = ""
    if anomalies:
        anomalies_block = "\n".join(
            f"- [{a['severity'].upper()}] {a['type']}: {a['description']}"
            for a in anomalies
        )

    topic_block = topic_summary or "No clusters detected."

    dq_block = ""
    if data_quality_issues:
        dq_block = "\n== DATA QUALITY ==\n" + "\n".join(f"- {i}" for i in data_quality_issues)

    # Actor-separated metrics
    actor_block = ""
    actor_data = metrics_display.get("actor_metrics", {})
    if actor_data:
        lines = ["== ACTOR-SEPARATED METRICS =="]
        for aname, am in actor_data.items():
            if not isinstance(am, dict) or aname == "combined":
                continue
            lines.append(f"\n{aname.capitalize()} ({am.get('total_mentions', 0)} mentions):")
            lines.append(f"  Sentiment: {json.dumps(am.get('sentiment_breakdown', {}), ensure_ascii=False, default=str)}")
            lines.append(f"  Top sources: {am.get('top_sources', [])[:5]}")
            lines.append(f"  Avg engagement: {am.get('avg_engagement', 'N/A')}")
        actor_block = "\n".join(lines)

    # Intersection
    intersection_block = ""
    inter = metrics_display.get("intersection", {})
    if inter and inter.get("total", 0) > 0:
        intersection_block = (
            f"\n== INTERSECTION ANALYSIS ==\n"
            f"Brand only ({inter.get('brand_label', client_name)}): "
            f"{inter.get('brand_only', 0)} ({inter.get('brand_only_pct', 0)}%)\n"
            f"Actor only ({inter.get('actor_label', actor_name)}): "
            f"{inter.get('actor_only', 0)} ({inter.get('actor_only_pct', 0)}%)\n"
            f"INTERSECTION (both): {inter.get('intersection', 0)} ({inter.get('intersection_pct', 0)}%)\n"
            f"Intersection sentiment: {json.dumps(inter.get('intersection_sentiment', {}), ensure_ascii=False, default=str)}\n"
            f"Neither: {inter.get('neither', 0)} ({inter.get('neither_pct', 0)}%)"
        )

    # Sub-category breakdown
    subcat_block = ""
    subcat = metrics_display.get("actor_subcategory_breakdown", {})
    if subcat:
        subcat_block = "\n== ACTOR SUB-CATEGORIES ==\n" + "\n".join(
            f"- {k}: {v}" for k, v in subcat.items()
        )

    # ── Sentiment DIRECTION (toward whom) — CRITICAL for correct diagnosis ──
    direction_block = ""
    actor_data_for_dir = metrics_display.get("actor_metrics", {})
    if actor_data_for_dir:
        dir_lines = [
            "== SENTIMENT DIRECTION (toward whom — THIS IS THE MOST IMPORTANT DATA) ==",
            "⚠️ DO NOT diagnose crisis without reading this section first.",
        ]
        total_neg = 0
        actor_neg_map = {}
        for aname, am in actor_data_for_dir.items():
            if not isinstance(am, dict):
                continue
            sent = am.get("sentiment_breakdown", {})
            a_total = am.get("total_mentions", 0)
            a_neg = 0
            a_pos = 0
            a_neu = 0
            for sk, sv in sent.items():
                if not isinstance(sv, dict):
                    continue
                count = sv.get("count", 0)
                if sk.lower() in ("negative", "negativo"):
                    a_neg = count
                elif sk.lower() in ("positive", "positivo"):
                    a_pos = count
                else:
                    a_neu += count
            total_neg += a_neg
            actor_neg_map[aname] = a_neg
            dir_lines.append(
                f"  Toward {aname.capitalize()}: {a_total} total — "
                f"NEG {a_neg} ({a_neg/max(a_total,1)*100:.1f}%), "
                f"POS {a_pos} ({a_pos/max(a_total,1)*100:.1f}%), "
                f"NEU {a_neu}"
            )
        # Percentage of total negative going to each actor
        if total_neg > 0:
            dir_lines.append(f"\n  DISTRIBUTION OF ALL {total_neg:,} NEGATIVE MENTIONS:")
            sorted_actors = sorted(actor_neg_map.items(), key=lambda x: x[1], reverse=True)
            for aname, a_neg in sorted_actors:
                pct = a_neg / total_neg * 100
                dir_lines.append(f"    → {pct:.1f}% of negative goes to {aname.capitalize()} ({a_neg:,} of {total_neg:,})")

            # Explicit diagnosis based on direction
            brand_name_lower = client_name.lower()
            brand_neg = actor_neg_map.get(brand_name_lower, 0)
            brand_neg_pct = brand_neg / total_neg * 100 if total_neg > 0 else 0
            top_actor, top_actor_neg = sorted_actors[0]
            top_actor_pct = top_actor_neg / total_neg * 100

            if brand_neg_pct < 20 and top_actor.lower() != brand_name_lower:
                dir_lines.append(
                    f"\n  ⚡ DIAGNÓSTICO AUTOMÁTICO: {client_name} NO está en crisis. "
                    f"Solo {brand_neg_pct:.1f}% del negativo ({brand_neg:,} de {total_neg:,}) "
                    f"se dirige a {client_name}. El {top_actor_pct:.1f}% va a {top_actor.capitalize()}. "
                    f"La percepción de crisis es un artefacto de no separar dirección. "
                    f"TESIS CORRECTA: {client_name} absorbió ruido pero no daño — "
                    f"{top_actor.capitalize()} recibió el castigo real."
                )
            elif brand_neg_pct > 50:
                dir_lines.append(
                    f"\n  ⚠️ DIAGNÓSTICO: {client_name} recibe {brand_neg_pct:.1f}% del negativo. "
                    f"Esto SÍ indica presión reputacional directa."
                )
            else:
                dir_lines.append(
                    f"\n  📊 DIAGNÓSTICO: Sentimiento mixto. {client_name} recibe {brand_neg_pct:.1f}% "
                    f"del negativo, {top_actor.capitalize()} recibe {top_actor_pct:.1f}%. "
                    f"Analizar por plataforma para determinar dónde la marca está expuesta."
                )

        direction_block = "\n".join(dir_lines)

    # ── Brand criticism categories ───────────────────────────────
    criticism_block = ""
    brand_crit = metrics_display.get("brand_criticism", {})
    if brand_crit and brand_crit.get("total_negative_brand", 0) > 0:
        crit_lines = [
            f"== BRAND CRITICISM CATEGORIES ({brand_crit['total_negative_brand']} negative toward brand) =="
        ]
        for cat in brand_crit.get("categories", [])[:8]:
            crit_lines.append(
                f"  - {cat['category']}: {cat['count']} ({cat['pct']:.1f}%)"
            )
        sev = brand_crit.get("severity_distribution", {})
        if sev:
            crit_lines.append(f"  Severity: high={sev.get('high',0)}, medium={sev.get('medium',0)}, low={sev.get('low',0)}")
        criticism_block = "\n".join(crit_lines)

    # ── Tangential / catalyst analysis ───────────────────────────
    tangential_block = ""
    tang = metrics_display.get("tangential_analysis", {})
    if tang and tang.get("total_tangential", 0) > 0:
        tang_lines = [
            f"== TANGENTIAL / CATALYST ANALYSIS ==",
            f"  Total tangential mentions: {tang['total_tangential']:,}",
            f"  Negative tangential: {tang.get('negative_tangential', 0):,} ({tang.get('negative_tangential_pct', 0):.1f}%)",
            f"  Catalyst detected: {tang.get('catalyst_detected', False)} (strength: {tang.get('catalyst_strength', 'none')})",
        ]
        themes = tang.get("top_themes", [])
        if themes:
            tang_lines.append(f"  Pre-existing issues: {', '.join(t['theme'] for t in themes[:5])}")
        tangential_block = "\n".join(tang_lines)

    # ── Comunicado impact ────────────────────────────────────────
    comunicado_block = ""
    com = metrics_display.get("comunicado_impact", {})
    if com and com.get("event_date"):
        pre = com.get("pre", {})
        post = com.get("post", {})
        delta = com.get("delta", {})
        comunicado_block = (
            f"== COMUNICADO / EVENT IMPACT (event date: {com['event_date']}) ==\n"
            f"  Pre-event: {pre.get('mentions', 0):,} mentions, {pre.get('avg_daily_mentions', 0):.0f}/day\n"
            f"  Post-event: {post.get('mentions', 0):,} mentions, {post.get('avg_daily_mentions', 0):.0f}/day\n"
            f"  Delta: mentions +{delta.get('mentions_pct', 0):.0f}%, engagement +{delta.get('engagement_pct', 0):.0f}%\n"
            f"  Negative shift: {delta.get('negative_shift', 0):+.1f}pp\n"
            f"  Peak day: {com.get('peak_day', {}).get('date', 'N/A')} ({com.get('peak_day', {}).get('mentions', 0):,} mentions)\n"
            f"  Recovery: {com.get('recovery_days', 'not reached')} days"
        )

    # Structure based on report_type
    if report_type == "campaign":
        structure = CAMPAIGN_STRUCTURE
    elif report_type == "monitoring":
        structure = MONITORING_STRUCTURE
    else:
        structure = CRISIS_STRUCTURE.format(client_name=client_name, actor_name=actor_name)

    prompt = f"""Analyze data for {client_name} during {period}.

== DATA SUMMARY ==
{metrics_json}

{direction_block}

{actor_block}
{intersection_block}
{subcat_block}

{criticism_block}

{tangential_block}

{comunicado_block}

== TOPIC CLUSTERS ==
{topic_block}

== ANOMALIES ==
{anomalies_block or "None detected."}

== SAMPLE MENTIONS ({len(sample_mentions)} selected by relevance) ==
{mentions_block or "No samples available."}
{dq_block}

{structure}"""

    return prompt
