"""Tests for the Epical rules validator (25 rules).

Run with: python -m pytest tests/test_rules.py -v
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agents.report_builder.rules import RulesValidator, RuleViolation


@pytest.fixture
def validator():
    return RulesValidator()


@pytest.fixture
def clean_metrics():
    """Metrics that pass all data rules."""
    return {
        "total_mentions": 1000,
        "sentiment_breakdown": {
            "negativo": {"count": 600, "percentage": 60.0},
            "positivo": {"count": 300, "percentage": 30.0},
            "neutro": {"count": 100, "percentage": 10.0},
        },
        "actor_breakdown": {"brand": 600, "actor": 300, "otros": 100},
        "engagement_by_platform": [
            {"platform": "Twitter", "engagement_share": 50.0},
            {"platform": "TikTok", "engagement_share": 50.0},
        ],
        "reach_deduplicated": {
            "total_reach_raw": 1000000,
            "total_reach_deduplicated": 800000,
            "inflation_factor": 1.25,
        },
    }


# ── Data Rules (1-7) ────────────────────────────────────────────

class TestDataRules:
    def test_rule1_no_audit(self, validator, clean_metrics):
        violations = validator.validate_all(metrics=clean_metrics, audit_accuracy=None)
        r1 = [v for v in violations if v.rule_id == 1]
        assert len(r1) == 1
        assert "auditoría" in r1[0].message.lower()

    def test_rule3_inflated_reach(self, validator):
        metrics = {
            "reach_deduplicated": {
                "total_reach_raw": 5000000,
                "total_reach_deduplicated": 2000000,
                "inflation_factor": 2.5,
            },
        }
        violations = validator.validate_all(metrics=metrics, audit_accuracy=90.0)
        r3 = [v for v in violations if v.rule_id == 3]
        assert len(r3) == 1
        assert "inflado" in r3[0].message.lower()

    def test_rule4_sentiment_sums(self, validator):
        metrics = {
            "sentiment_breakdown": {
                "negativo": {"count": 600, "percentage": 60.0},
                "positivo": {"count": 300, "percentage": 30.0},
                # Missing 10% — should trigger
            },
        }
        violations = validator.validate_all(metrics=metrics, audit_accuracy=90.0)
        r4 = [v for v in violations if v.rule_id == 4]
        assert len(r4) >= 1

    def test_rule6_low_accuracy_blocks(self, validator, clean_metrics):
        violations = validator.validate_all(metrics=clean_metrics, audit_accuracy=60.0)
        r6 = [v for v in violations if v.rule_id == 6]
        assert len(r6) == 1
        assert r6[0].severity == "error"
        assert "75%" in r6[0].message

    def test_rule6_high_accuracy_passes(self, validator, clean_metrics):
        violations = validator.validate_all(metrics=clean_metrics, audit_accuracy=90.0)
        r6 = [v for v in violations if v.rule_id == 6]
        assert len(r6) == 0


# ── Editorial Rules (8-12) ──────────────────────────────────────

class TestEditorialRules:
    def test_rule8_operational_instructions(self, validator):
        text = "Avianca debe implementar un protocolo de crisis."
        violations = validator.validate_all(report_text=text)
        r8 = [v for v in violations if v.rule_id == 8]
        assert len(r8) >= 1

    def test_rule8_strategic_reading_ok(self, validator):
        text = "Señal → la percepción de servicio condiciona la credibilidad."
        violations = validator.validate_all(report_text=text)
        r8 = [v for v in violations if v.rule_id == 8]
        assert len(r8) == 0

    def test_rule9_forbidden_tool_names(self, validator):
        for name in ["YouScan", "SentimIA", "Claude", "Haiku", "Brandwatch"]:
            violations = validator.validate_all(report_text=f"Usamos {name} para procesar.")
            r9 = [v for v in violations if v.rule_id == 9]
            assert len(r9) >= 1, f"Failed to catch forbidden name: {name}"
            assert r9[0].severity == "error"

    def test_rule9_allowed_names(self, validator):
        text = "Epical Perception Engine detectó 25 matices emocionales."
        violations = validator.validate_all(report_text=text)
        r9 = [v for v in violations if v.rule_id == 9]
        assert len(r9) == 0

    def test_rule9_in_html(self, validator):
        html = '<p>Procesamos con YouScan los datos.</p>'
        violations = validator.validate_all(html_content=html)
        r9 = [v for v in violations if v.rule_id == 9]
        assert len(r9) >= 1


# ── Design Rules (13-19) ────────────────────────────────────────

class TestDesignRules:
    def test_rule14_fonts_present(self, validator):
        html = """<link href="fonts.googleapis.com/css2?family=Playfair Display&family=DM Sans&family=JetBrains Mono">"""
        violations = validator.validate_all(html_content=html)
        r14 = [v for v in violations if v.rule_id == 14]
        assert len(r14) == 0

    def test_rule14_fonts_missing(self, validator):
        html = "<html><body>No fonts</body></html>"
        violations = validator.validate_all(html_content=html)
        r14 = [v for v in violations if v.rule_id == 14]
        assert len(r14) == 3  # Playfair + DM Sans + JetBrains

    def test_rule14_import_forbidden(self, validator):
        html = '@import url("fonts.googleapis.com/css2?family=Playfair+Display&family=DM+Sans&family=JetBrains+Mono");'
        violations = validator.validate_all(html_content=html)
        r14 = [v for v in violations if v.rule_id == 14]
        import_violations = [v for v in r14 if "@import" in v.message]
        assert len(import_violations) == 1

    def test_rule15_chart_wrapper(self, validator):
        html = '<div style="position:relative;height:280px"><canvas id="chart1"></canvas></div>'
        violations = validator.validate_all(html_content=html)
        r15 = [v for v in violations if v.rule_id == 15]
        assert len(r15) == 0

    def test_rule15_unwrapped_chart(self, validator):
        html = '<div><canvas id="chart1"></canvas></div>'
        violations = validator.validate_all(html_content=html)
        r15 = [v for v in violations if v.rule_id == 15]
        assert len(r15) >= 1

    def test_rule19_chartjs_cdn(self, validator):
        html = '<canvas id="x"></canvas><script src="cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>'
        violations = validator.validate_all(html_content=html)
        r19 = [v for v in violations if v.rule_id == 19]
        assert len(r19) == 0


# ── Narrative Rules (20-25) ─────────────────────────────────────

class TestNarrativeRules:
    def test_rule20_obvious_thesis(self, validator):
        metrics = {"sentiment_breakdown": {"negativo": {"count": 700, "percentage": 70.0}}}
        text = "El 70% del sentimiento es negativo. La marca está en crisis."
        violations = validator.validate_all(report_text=text, metrics=metrics)
        r20 = [v for v in violations if v.rule_id == 20]
        assert len(r20) >= 1

    def test_rule20_deep_thesis(self, validator):
        metrics = {"sentiment_breakdown": {"negativo": {"count": 700, "percentage": 70.0}}}
        text = "Pero la pregunta es hacia quién se dirige ese sentimiento negativo."
        violations = validator.validate_all(report_text=text, metrics=metrics)
        r20 = [v for v in violations if v.rule_id == 20]
        assert len(r20) == 0

    def test_rule24_missing_minority_narrative(self, validator):
        text = "Todo bien con la marca, la conversación es positiva."
        violations = validator.validate_all(report_text=text)
        r24 = [v for v in violations if v.rule_id == 24]
        assert len(r24) >= 1

    def test_rule25_missing_closing_comparison(self, validator):
        text = "Recomendamos continuar con la estrategia actual."
        violations = validator.validate_all(report_text=text)
        r25 = [v for v in violations if v.rule_id == 25]
        assert len(r25) >= 1

    def test_rule25_proper_closing(self, validator):
        text = "La diferencia entre monitoreo estándar y análisis profundo es lo que importa."
        violations = validator.validate_all(report_text=text)
        r25 = [v for v in violations if v.rule_id == 25]
        assert len(r25) == 0


# ── Format report ───────────────────────────────────────────────

class TestFormatReport:
    def test_no_violations(self, validator):
        report = validator.format_report([])
        assert "✅" in report

    def test_with_violations(self, validator):
        violations = [
            RuleViolation(9, "editorial", "Tool name detected", "error"),
            RuleViolation(20, "narrative", "Obvious thesis", "warning"),
        ]
        report = validator.format_report(violations)
        assert "❌" in report
        assert "⚠️" in report
        assert "R9" in report
        assert "R20" in report
