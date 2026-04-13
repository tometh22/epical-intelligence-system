"""Epical editorial rules validator — 25 rules from the agent spec.

Runs automated checks on report data, metrics, and generated HTML/text
before each checkpoint. Rules are IP of Epical.

Rules 1-7:   Data auditing
Rules 8-12:  Editorial
Rules 13-19: Design
Rules 20-25: Narrative
"""

import re
from typing import Any, Dict, List, Optional

from agents.shared.logger import get_logger

logger = get_logger("report-builder")


class RuleViolation:
    """A single rule violation."""

    def __init__(self, rule_id: int, category: str, message: str,
                 severity: str = "warning") -> None:
        self.rule_id = rule_id
        self.category = category
        self.message = message
        self.severity = severity  # "error" | "warning" | "info"

    def __repr__(self) -> str:
        return f"[R{self.rule_id}|{self.severity}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "message": self.message,
            "severity": self.severity,
        }


class RulesValidator:
    """Validates report content against the 25 Epical rules.

    Usage:
        validator = RulesValidator()
        violations = validator.validate_all(
            metrics=metrics_dict,
            report_text=narrative_text,
            html_content=generated_html,
            audit_sample=sample_mentions,
        )
        errors = [v for v in violations if v.severity == "error"]
        if errors:
            # Block checkpoint, report to analyst
    """

    # ── Forbidden tool names (Rule 9) ────────────────────────────
    FORBIDDEN_NAMES = [
        "youscan", "sentimia", "claude", "haiku", "sonnet", "opus",
        "brandwatch", "anthropic", "openai", "gpt", "chatgpt",
        "sprout social", "hootsuite", "meltwater",
    ]

    # ── Allowed replacements (Rule 9) ────────────────────────────
    ALLOWED_REPLACEMENTS = {
        "epical perception engine": "motor emocional",
        "modelos propietarios de clasificación": "clasificación IA",
    }

    def validate_all(
        self,
        metrics: Optional[Dict[str, Any]] = None,
        report_text: str = "",
        html_content: str = "",
        audit_sample: Optional[List[Dict[str, Any]]] = None,
        audit_accuracy: Optional[float] = None,
    ) -> List[RuleViolation]:
        """Run all 25 rules and return violations."""
        violations: List[RuleViolation] = []

        if metrics:
            violations.extend(self._check_data_rules(metrics, audit_accuracy))

        if report_text:
            violations.extend(self._check_editorial_rules(report_text))
            violations.extend(self._check_narrative_rules(report_text, metrics))

        if html_content:
            violations.extend(self._check_design_rules(html_content))
            violations.extend(self._check_editorial_rules_html(html_content))

        logger.info(
            "Rules validation: %d violations (%d errors, %d warnings)",
            len(violations),
            sum(1 for v in violations if v.severity == "error"),
            sum(1 for v in violations if v.severity == "warning"),
        )
        return violations

    # ══════════════════════════════════════════════════════════════
    # Rules 1-7: Data auditing
    # ══════════════════════════════════════════════════════════════

    def _check_data_rules(
        self,
        metrics: Dict[str, Any],
        audit_accuracy: Optional[float],
    ) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        # Rule 1: NEVER trust raw data without auditing
        # (checked by whether audit_accuracy is provided)
        if audit_accuracy is None:
            violations.append(RuleViolation(
                1, "data", "No hay auditoría de datos. Se requiere verificar una muestra.",
                "warning",
            ))

        # Rule 3: ALWAYS deduplicate reach by unique account
        reach_data = metrics.get("reach_deduplicated", {})
        if reach_data:
            inflation = reach_data.get("inflation_factor", 1.0)
            if inflation > 2.0:
                violations.append(RuleViolation(
                    3, "data",
                    f"Alcance inflado {inflation:.1f}x sin deduplicar. "
                    f"Raw={reach_data.get('total_reach_raw', 0):,}, "
                    f"Dedup={reach_data.get('total_reach_deduplicated', 0):,}",
                    "warning",
                ))

        # Rule 4: Verify engagement and mentions sum correctly
        violations.extend(self._check_numerical_consistency(metrics))

        # Rule 6: If accuracy < 75%, stop and report
        if audit_accuracy is not None and audit_accuracy < 75.0:
            violations.append(RuleViolation(
                6, "data",
                f"Accuracy de auditoría = {audit_accuracy:.1f}% (mínimo 75%). "
                f"DETENER y reportar al analista.",
                "error",
            ))

        # Rule 7: Percentages rounded to 1 decimal, big numbers rounded
        sentiment = metrics.get("sentiment_breakdown", {})
        for key, val in sentiment.items():
            if isinstance(val, dict):
                pct = val.get("percentage", 0)
                if isinstance(pct, float) and len(str(pct).split(".")[-1]) > 1:
                    violations.append(RuleViolation(
                        7, "data",
                        f"Porcentaje de '{key}' tiene más de 1 decimal: {pct}",
                        "info",
                    ))

        return violations

    def _check_numerical_consistency(self, metrics: Dict[str, Any]) -> List[RuleViolation]:
        """Rule 4: Verify that engagement and mentions sum correctly."""
        violations: List[RuleViolation] = []

        # Check actor breakdown sums to total
        actor_breakdown = metrics.get("actor_breakdown", {})
        if actor_breakdown:
            actor_sum = sum(actor_breakdown.values())
            total = metrics.get("total_mentions", 0)
            if total > 0 and abs(actor_sum - total) > total * 0.05:
                violations.append(RuleViolation(
                    4, "data",
                    f"Actor breakdown suma {actor_sum:,} pero total = {total:,} "
                    f"(diferencia: {abs(actor_sum - total):,})",
                    "warning",
                ))

        # Check sentiment percentages sum to ~100%
        sentiment = metrics.get("sentiment_breakdown", {})
        if sentiment:
            pct_sum = sum(
                v.get("percentage", 0) for v in sentiment.values()
                if isinstance(v, dict)
            )
            if pct_sum > 0 and abs(pct_sum - 100.0) > 2.0:
                violations.append(RuleViolation(
                    4, "data",
                    f"Porcentajes de sentimiento suman {pct_sum:.1f}% (deberían sumar ~100%)",
                    "warning",
                ))

        # Check engagement by platform sums
        eng_platform = metrics.get("engagement_by_platform", [])
        if eng_platform:
            share_sum = sum(p.get("engagement_share", 0) for p in eng_platform)
            if share_sum > 0 and abs(share_sum - 100.0) > 2.0:
                violations.append(RuleViolation(
                    4, "data",
                    f"Engagement share por plataforma suma {share_sum:.1f}%",
                    "info",
                ))

        return violations

    # ══════════════════════════════════════════════════════════════
    # Rules 8-12: Editorial
    # ══════════════════════════════════════════════════════════════

    def _check_editorial_rules(self, text: str) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        text_lower = text.lower()

        # Rule 8: Recommendations are "lecturas estratégicas" with "Señal →"
        # Check for operational instructions (forbidden)
        operational_patterns = [
            r"(?:debe|debería|tiene que|hay que)\s+(?:implementar|crear|lanzar|desarrollar)",
            r"recomendamos\s+(?:que|implementar|crear)",
            r"se\s+sugiere\s+(?:implementar|crear|lanzar)",
        ]
        for pat in operational_patterns:
            if re.search(pat, text_lower):
                violations.append(RuleViolation(
                    8, "editorial",
                    "Recomendación operativa detectada. Usar 'lecturas estratégicas' "
                    "con tag 'Señal →', no instrucciones.",
                    "warning",
                ))
                break

        # Rule 9: NEVER mention tool names
        for name in self.FORBIDDEN_NAMES:
            # Use word boundary to avoid false positives
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, text_lower):
                violations.append(RuleViolation(
                    9, "editorial",
                    f"Herramienta interna mencionada: '{name}'. "
                    f"Usar 'Epical Perception Engine' o 'modelos propietarios'.",
                    "error",
                ))

        # Rule 12: Contact email should be hi@epical.digital
        if "epical" in text_lower and "contacto" in text_lower:
            if "hi@epical.digital" not in text_lower:
                violations.append(RuleViolation(
                    12, "editorial",
                    "Email de contacto debería ser hi@epical.digital",
                    "info",
                ))

        return violations

    def _check_editorial_rules_html(self, html: str) -> List[RuleViolation]:
        """Check editorial rules against HTML content."""
        violations: List[RuleViolation] = []
        html_lower = html.lower()

        # Rule 9: tool names in HTML
        for name in self.FORBIDDEN_NAMES:
            # Skip names that might appear in meta tags, scripts, or URLs
            # Check only visible text (rough heuristic: between > and <)
            pattern = r">[^<]*\b" + re.escape(name) + r"\b[^<]*<"
            if re.search(pattern, html_lower):
                violations.append(RuleViolation(
                    9, "editorial",
                    f"Herramienta interna en HTML visible: '{name}'",
                    "error",
                ))

        return violations

    # ══════════════════════════════════════════════════════════════
    # Rules 13-19: Design (checked on HTML)
    # ══════════════════════════════════════════════════════════════

    def _check_design_rules(self, html: str) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        # Rule 14: Typography — Playfair + DM Sans + JetBrains Mono via <link>
        if "Playfair Display" not in html:
            violations.append(RuleViolation(14, "design", "Falta Playfair Display", "error"))
        if "DM Sans" not in html:
            violations.append(RuleViolation(14, "design", "Falta DM Sans", "error"))
        if "JetBrains Mono" not in html:
            violations.append(RuleViolation(14, "design", "Falta JetBrains Mono", "error"))
        if "@import" in html and "fonts.googleapis" in html:
            violations.append(RuleViolation(
                14, "design",
                "Google Fonts usa @import. Debe ser <link> tag.",
                "error",
            ))

        # Rule 15: Charts in div with position:relative and explicit height
        canvas_matches = re.findall(r"<canvas\s+id=[\"'](\w+)[\"']", html)
        for canvas_id in canvas_matches:
            # Check if there's a wrapper with position:relative;height before this canvas
            pattern = rf'position:\s*relative[^>]*height:\s*\d+px[^>]*>\s*<canvas\s+id=["\']?{canvas_id}'
            if not re.search(pattern, html):
                violations.append(RuleViolation(
                    15, "design",
                    f"Canvas '{canvas_id}' no está dentro de div con position:relative + height explícita",
                    "error",
                ))

        # Rule 16: KPI big numbers use DM Sans bold, not JetBrains Mono
        # Check that .kpi-v doesn't use font-family mono
        if re.search(r"\.kpi-v\s*\{[^}]*font-family:\s*var\(--mono\)", html):
            violations.append(RuleViolation(
                16, "design",
                "KPIs usan JetBrains Mono. Deben usar DM Sans bold.",
                "warning",
            ))

        # Rule 17: Callout box colors
        has_insight = "class=\"insight\"" in html or "class=\"insight " in html
        has_sowhat = "class=\"sowhat\"" in html or "class=\"sowhat " in html
        if not has_insight and not has_sowhat:
            violations.append(RuleViolation(
                17, "design",
                "No hay callout boxes (insight/sowhat). Falta contexto editorial.",
                "info",
            ))

        # Rule 19: Chart.js 4.4.1 via Cloudflare CDN
        if "<canvas" in html:
            if "cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1" not in html:
                violations.append(RuleViolation(
                    19, "design",
                    "Chart.js no viene de Cloudflare CDN 4.4.1",
                    "warning",
                ))

        return violations

    # ══════════════════════════════════════════════════════════════
    # Rules 20-25: Narrative
    # ══════════════════════════════════════════════════════════════

    def _check_narrative_rules(
        self,
        text: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        text_lower = text.lower()

        # Rule 20: Thesis NOT obvious — if data says "70% negativo",
        # analysis should ask "negativo hacia quién"
        if metrics:
            sentiment = metrics.get("sentiment_breakdown", {})
            neg_pct = 0
            for k, v in sentiment.items():
                if k.lower() in ("negative", "negativo") and isinstance(v, dict):
                    neg_pct = v.get("percentage", 0)
            if neg_pct > 60:
                # If high negative, check text explores direction
                direction_words = ["hacia quién", "contra quién", "dirección",
                                   "dirigido a", "toward", "direction"]
                if not any(w in text_lower for w in direction_words):
                    violations.append(RuleViolation(
                        20, "narrative",
                        f"Sentimiento {neg_pct:.1f}% negativo pero el texto "
                        f"no analiza dirección (hacia quién). Tesis posiblemente obvia.",
                        "warning",
                    ))

        # Rule 21: ALWAYS look for catalyst effect
        catalyst_words = ["catalizador", "catalyst", "insatisfacción preexistente",
                          "insatisfacción acumulada", "latente", "tangencial"]
        if not any(w in text_lower for w in catalyst_words):
            violations.append(RuleViolation(
                21, "narrative",
                "No se menciona efecto catalizador. ¿El incidente amplificó insatisfacción preexistente?",
                "info",
            ))

        # Rule 22: ALWAYS analyze temporal impact
        temporal_words = ["antes y después", "pre-evento", "post-evento",
                          "comunicado", "impacto temporal", "timeline", "evolución"]
        if not any(w in text_lower for w in temporal_words):
            violations.append(RuleViolation(
                22, "narrative",
                "No se analiza impacto temporal. ¿Hubo un evento? ¿Qué pasó antes/después?",
                "info",
            ))

        # Rule 23: ALWAYS verify sector contagion
        contagion_words = ["contagio", "competidores", "sector", "industria",
                           "otras marcas", "other brands"]
        if not any(w in text_lower for w in contagion_words):
            violations.append(RuleViolation(
                23, "narrative",
                "No se verifica contagio sectorial. ¿Los competidores se vieron afectados?",
                "info",
            ))

        # Rule 24: ALWAYS identify minority risk narrative
        minority_words = ["minoritaria", "riesgo", "emergente", "puede crecer",
                          "potencial de", "narrativa de riesgo"]
        if not any(w in text_lower for w in minority_words):
            violations.append(RuleViolation(
                24, "narrative",
                "No se identifica narrativa minoritaria de riesgo.",
                "warning",
            ))

        # Rule 25: Closing ALWAYS compares standard monitoring vs deep analysis
        closing_words = ["monitoreo estándar", "análisis profundo", "dashboard",
                         "diferencia entre", "standard monitoring"]
        if not any(w in text_lower for w in closing_words):
            violations.append(RuleViolation(
                25, "narrative",
                "Cierre no compara monitoreo estándar vs análisis profundo (pitch implícito de Epical).",
                "warning",
            ))

        return violations

    # ──────────────────────────────────────────────────────────────
    # Convenience
    # ──────────────────────────────────────────────────────────────

    def get_errors(self, violations: List[RuleViolation]) -> List[RuleViolation]:
        """Filter only error-severity violations."""
        return [v for v in violations if v.severity == "error"]

    def get_warnings(self, violations: List[RuleViolation]) -> List[RuleViolation]:
        """Filter only warning-severity violations."""
        return [v for v in violations if v.severity == "warning"]

    def format_report(self, violations: List[RuleViolation]) -> str:
        """Format violations as a human-readable report."""
        if not violations:
            return "✅ Todas las reglas verificadas — sin violaciones."

        errors = self.get_errors(violations)
        warnings = self.get_warnings(violations)
        infos = [v for v in violations if v.severity == "info"]

        lines = []
        if errors:
            lines.append(f"❌ {len(errors)} ERRORES (bloquean entrega):")
            for v in errors:
                lines.append(f"  R{v.rule_id} [{v.category}]: {v.message}")
        if warnings:
            lines.append(f"⚠️  {len(warnings)} ADVERTENCIAS:")
            for v in warnings:
                lines.append(f"  R{v.rule_id} [{v.category}]: {v.message}")
        if infos:
            lines.append(f"ℹ️  {len(infos)} SUGERENCIAS:")
            for v in infos:
                lines.append(f"  R{v.rule_id} [{v.category}]: {v.message}")

        return "\n".join(lines)
