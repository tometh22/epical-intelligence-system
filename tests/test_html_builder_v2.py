"""Tests for the v2 HTML builder (parametrized from v10 template).

Run with: python -m pytest tests/test_html_builder_v2.py -v
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agents.report_builder.html_builder_v2 import build_report_html, _fmt, _pct


@pytest.fixture
def full_metrics():
    """Realistic metrics dict simulating MetricsCalculator output."""
    return {
        "total_mentions": 14403,
        "sentiment_breakdown": {
            "negativo": {"count": 10208, "percentage": 70.9},
            "neutro": {"count": 2615, "percentage": 18.2},
            "positivo": {"count": 1580, "percentage": 11.0},
        },
        "volume_by_date": {
            "2026-03-29": 2179,
            "2026-03-30": 4863,
            "2026-03-31": 5354,
            "2026-04-01": 958,
            "2026-04-02": 515,
        },
        "top_sources": [
            ("Twitter", 5035),
            ("Facebook", 4684),
            ("TikTok", 3595),
            ("Instagram", 783),
        ],
        "total_likes": 892000,
        "total_comments": 45000,
        "total_shares": 23000,
        "engagement_by_platform": [
            {
                "platform": "TikTok",
                "mentions": 3595,
                "total_engagement": 500000,
                "avg_engagement": 139.1,
                "engagement_share": 52.1,
                "total_likes": 480000,
                "total_comments": 15000,
                "total_shares": 5000,
                "total_reach": 29000000,
                "avg_reach": 8067.0,
                "reach_share": 44.2,
            },
            {
                "platform": "Twitter",
                "mentions": 5035,
                "total_engagement": 250000,
                "avg_engagement": 49.7,
                "engagement_share": 26.0,
                "total_likes": 200000,
                "total_comments": 30000,
                "total_shares": 20000,
                "total_reach": 22000000,
                "avg_reach": 4369.0,
                "reach_share": 33.5,
            },
            {
                "platform": "Facebook",
                "mentions": 4684,
                "total_engagement": 180000,
                "avg_engagement": 38.4,
                "engagement_share": 18.7,
                "total_likes": 150000,
                "total_comments": 20000,
                "total_shares": 10000,
                "total_reach": 12000000,
                "avg_reach": 2562.0,
                "reach_share": 18.3,
            },
        ],
        "timeline": {
            "daily": [
                {"date": "2026-03-29", "mentions": 2179, "engagement": 150000, "sentiment": {"negativo": 1500, "positivo": 400, "neutro": 279}},
                {"date": "2026-03-30", "mentions": 4863, "engagement": 350000, "sentiment": {"negativo": 3500, "positivo": 800, "neutro": 563}},
                {"date": "2026-03-31", "mentions": 5354, "engagement": 400000, "sentiment": {"negativo": 4000, "positivo": 600, "neutro": 754}},
                {"date": "2026-04-01", "mentions": 958, "engagement": 50000, "sentiment": {"negativo": 600, "positivo": 200, "neutro": 158}},
                {"date": "2026-04-02", "mentions": 515, "engagement": 20000, "sentiment": {"negativo": 300, "positivo": 100, "neutro": 115}},
            ],
            "period_start": "2026-03-29",
            "period_end": "2026-04-02",
            "total_days": 5,
        },
        "spikes": [
            {"date": "2026-03-31", "mentions": 5354, "previous_mentions": 4863, "pct_change": 10.1, "severity": "warning", "description": "Pico de conversación"},
            {"date": "2026-03-30", "mentions": 4863, "previous_mentions": 2179, "pct_change": 123.2, "severity": "critical", "description": "Explosión de TikTok"},
        ],
        "reach_deduplicated": {
            "total_reach_raw": 95000000,
            "total_reach_deduplicated": 63000000,
            "total_reach_formatted": "63M",
            "unique_accounts": 8500,
            "inflation_factor": 1.51,
            "reach_by_platform": [],
            "top_accounts": [],
        },
        "tangential_analysis": {
            "total_tangential": 2084,
            "negative_tangential": 1800,
            "negative_tangential_pct": 86.4,
            "catalyst_detected": True,
            "catalyst_strength": "high",
            "top_themes": [
                {"theme": "equipaje", "count": 350, "pct": 16.8},
                {"theme": "cancelación", "count": 280, "pct": 13.4},
            ],
            "temporal_correlation": {},
            "pre_existing_issues": ["equipaje", "cancelación"],
        },
        "comunicado_impact": {
            "event_date": "2026-03-29",
            "window_days": 7,
            "pre": {"mentions": 21, "engagement": 500, "avg_daily_mentions": 3.0, "sentiment": {}},
            "post": {"mentions": 13869, "engagement": 970000, "avg_daily_mentions": 1980.0, "sentiment": {}},
            "delta": {"mentions_pct": 65900.0, "engagement_pct": 194000.0, "negative_shift": 12.5},
            "peak_day": {"date": "2026-03-31", "mentions": 5354},
            "recovery_days": None,
        },
        "actor_metrics": {
            "cossio": {
                "total_mentions": 11546,
                "sentiment_breakdown": {
                    "negativo": {"count": 9617, "percentage": 83.3},
                    "positivo": {"count": 1337, "percentage": 11.6},
                    "neutro": {"count": 592, "percentage": 5.1},
                },
            },
            "avianca": {
                "total_mentions": 702,
                "sentiment_breakdown": {
                    "negativo": {"count": 384, "percentage": 54.7},
                    "positivo": {"count": 238, "percentage": 33.9},
                    "neutro": {"count": 80, "percentage": 11.4},
                },
            },
        },
        "brand_criticism": {
            "total_negative_brand": 384,
            "categories": [
                {"category": "servicio_al_cliente", "count": 75, "pct": 19.5, "sample_texts": []},
            ],
            "severity_distribution": {"high": 30, "medium": 120, "low": 234},
        },
        "reclassification_stats": {"rules": 2500, "ai": 5000, "remaining": 200, "remaining_pct": 1.4},
    }


@pytest.fixture
def report_sections():
    """Pre-parsed narrative sections."""
    return {
        "cover_title": "La audiencia ya tomó posición.<br><em>La marca ganó.</em>",
        "cover_subtitle": "Análisis profundo de la conversación digital. Lo que revelan los datos no es una crisis de marca.",
        "findings": [
            {"title": "HALLAZGO 1", "text": "El 94% del sentimiento negativo es contra el actor, no contra la marca."},
            {"title": "HALLAZGO 2", "text": "La marca tiene más defensores activos que detractores directos."},
            {"title": "HALLAZGO 3", "text": "El incidente funcionó como catalizador de insatisfacción preexistente."},
        ],
        "exec_implication": "La estrategia no es de contención — es de capitalización.",
        "narratives": [
            {"title": "La seguridad es innegociable", "badge": "Dominante · Favorable", "body": "La narrativa ganadora."},
            {"title": "El castigo es desproporcionado", "badge": "Minoritaria · Riesgo medio", "body": "11.6% de las menciones."},
            {"title": "Los influencers deben tener límites", "badge": "Emergente · Oportunidad", "body": "Trasciende el caso."},
        ],
        "scenarios": [
            {"name": "Sin acción", "description": "La posición favorable se diluye.", "outcome": "Se pierde la oportunidad."},
            {"name": "Respuesta táctica", "description": "Contenido de humanización.", "outcome": "Se protege la posición."},
            {"name": "Posicionamiento proactivo", "description": "Estrategia integral.", "outcome": "El incidente se convierte en activo."},
        ],
        "readings": [
            {"title": "La insatisfacción de servicio es el flanco real", "body": "Las menciones tangenciales revelan el problema.", "signal": "la percepción de servicio condiciona la credibilidad"},
            {"title": "La tripulación es el activo más creíble", "body": "La audiencia separa al personal de la marca.", "signal": "la humanización orgánica supera al comunicado"},
        ],
        "applications": [
            {"title": "Defender la decisión internamente", "body": "Datos verificados que respaldan la posición."},
            {"title": "Calibrar la estrategia legal", "body": "La audiencia ya sancionó al actor."},
            {"title": "Llevar evidencia a CX", "body": "Quejas tangenciales como evidencia cuantificada."},
            {"title": "Briefear contenido con fundamento", "body": "Lecturas estratégicas briefeables a agencia."},
        ],
        "closing_standard": "14,403 menciones. 70.9% negativo. Crisis aparente.",
        "closing_deep": "94% del negativo es contra el actor. La marca tiene una ventana de capitalización.",
        "closing_question": "Dos lecturas del mismo dataset producen dos estrategias opuestas.",
        "data_insight": "<strong>El dato que invierte la lectura:</strong> de las 10,208 menciones negativas, 9,617 (94%) critican al actor, no a la marca.",
        "platform_insight": "La marca no pierde en ninguna plataforma. La oportunidad es ofensiva, no defensiva.",
        "timeline_insight": "La precisión importa más que la velocidad cuando la marca tiene la posición de autoridad.",
    }


class TestBuildReportHTML:
    def test_generates_valid_html(self, full_metrics, report_sections, tmp_path):
        out = tmp_path / "test_report.html"
        result = build_report_html(
            client_name="TestCorp",
            period="Marzo-Abril 2026",
            report_text="",
            metrics=full_metrics,
            anomalies=[],
            output_path=str(out),
            report_sections=report_sections,
            client_role="la Dirección de Comunicaciones",
        )
        assert result.exists()
        html = result.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_contains_google_fonts_link_tag(self, full_metrics, report_sections, tmp_path):
        """Rule 14: Google Fonts via <link> tag, not @import."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert '<link href="https://fonts.googleapis.com/css2' in html
        assert "@import" not in html

    def test_contains_playfair_dm_sans_jetbrains(self, full_metrics, report_sections, tmp_path):
        """Rule 14: Playfair Display + DM Sans + JetBrains Mono."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "Playfair Display" in html
        assert "DM Sans" in html
        assert "JetBrains Mono" in html

    def test_chartjs_via_cloudflare(self, full_metrics, report_sections, tmp_path):
        """Rule 19: Chart.js 4.4.1 via Cloudflare CDN."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1" in html

    def test_charts_have_height_wrapper(self, full_metrics, report_sections, tmp_path):
        """Rule 15: Charts inside div with position:relative and height."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        # Every <canvas> should be preceded by a div with position:relative;height
        import re
        canvases = re.findall(r'<div style="position:relative;height:\d+px"><canvas', html)
        assert len(canvases) >= 2, f"Expected >=2 wrapped charts, found {len(canvases)}"

    def test_callout_box_colors(self, full_metrics, report_sections, tmp_path):
        """Rule 17: insight=blue, sowhat=orange, risk=red."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "class=\"insight\"" in html or "class=\"insight " in html  # blue
        assert "class=\"sowhat\"" in html or "class=\"sowhat " in html  # orange
        assert "class=\"risk-box\"" in html or "class=\"risk-box " in html  # red (catalyst slide)

    def test_kpi_uses_dm_sans_not_mono(self, full_metrics, report_sections, tmp_path):
        """Rule 16: KPI big numbers use DM Sans bold, not JetBrains Mono."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        # kpi-v class should be styled with font-weight:700 (DM Sans inherited from body)
        # and NOT have font-family:mono
        assert "kpi-v" in html
        # The CSS defines .kpi-v with font-weight:700, inheriting DM Sans from body
        assert ".kpi-v{font-size:30px;font-weight:700;color:var(--dark)}" in html

    def test_platform_svgs(self, full_metrics, report_sections, tmp_path):
        """Rule 18: Platform logos as SVG inline."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "<svg" in html  # At least one SVG for platform icons

    def test_contains_all_standard_slides(self, full_metrics, report_sections, tmp_path):
        """Verify all standard slides are present."""
        out = tmp_path / "report.html"
        build_report_html("TestCorp", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "COVER" in html
        assert "EXEC SUMMARY" in html
        assert "METHODOLOGY" in html
        assert "THE DATA" in html
        assert "PLATFORMS" in html
        assert "TIMELINE" in html
        assert "NARRATIVES" in html
        assert "SCENARIOS" in html
        assert "STRATEGIC READINGS" in html
        assert "APPLICATIONS" in html
        assert "CLOSING" in html

    def test_optional_catalyst_present(self, full_metrics, report_sections, tmp_path):
        """Catalyst slide shows when tangential data has catalyst_detected=True."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "CATALYST" in html
        assert "efecto catalizador" in html.lower()

    def test_optional_catalyst_absent(self, full_metrics, report_sections, tmp_path):
        """Catalyst slide hidden when no catalyst detected."""
        full_metrics["tangential_analysis"]["catalyst_detected"] = False
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "CATALYST" not in html

    def test_optional_comunicado_present(self, full_metrics, report_sections, tmp_path):
        """Comunicado impact slide shows when event_date in data."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "COMUNICADO IMPACT" in html

    def test_optional_comunicado_absent(self, full_metrics, report_sections, tmp_path):
        """Comunicado slide hidden when no comunicado_impact data."""
        del full_metrics["comunicado_impact"]
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "COMUNICADO IMPACT" not in html

    def test_actor_slides_generated(self, full_metrics, report_sections, tmp_path):
        """Actor slides auto-generated from actor_metrics."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        assert "ACTOR: COSSIO" in html
        assert "ACTOR: AVIANCA" in html

    def test_no_tool_names(self, full_metrics, report_sections, tmp_path):
        """Rule 9: No internal tool names."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text().lower()
        assert "youscan" not in html
        assert "sentimia" not in html
        assert "claude" not in html
        assert "haiku" not in html
        assert "brandwatch" not in html

    def test_signal_arrow_in_readings(self, full_metrics, report_sections, tmp_path):
        """Rule 8: Readings have 'Señal →' tag."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        html = out.read_text()
        # Check for signal markers
        assert "Señal →" in html or "Señal →".replace("→", "&rarr;") in html or "rec-signal" in html

    def test_minimal_metrics(self, tmp_path):
        """Works with minimal metrics dict (graceful degradation)."""
        minimal = {
            "total_mentions": 500,
            "sentiment_breakdown": {"positivo": {"count": 300, "percentage": 60}, "negativo": {"count": 200, "percentage": 40}},
            "volume_by_date": {"2026-03-01": 250, "2026-03-02": 250},
            "top_sources": [("Twitter", 500)],
        }
        out = tmp_path / "minimal.html"
        result = build_report_html("MinimalCorp", "Marzo 2026", "## RESUMEN\nTest content.", minimal, [], str(out))
        assert result.exists()
        html = result.read_text()
        assert "MinimalCorp" in html
        assert "<!DOCTYPE html>" in html

    def test_file_size_reasonable(self, full_metrics, report_sections, tmp_path):
        """Generated HTML should be substantial but not bloated."""
        out = tmp_path / "report.html"
        build_report_html("X", "P", "", full_metrics, [], str(out), report_sections=report_sections)
        size = out.stat().st_size
        assert size > 15000, f"HTML too small: {size} bytes"
        assert size < 500000, f"HTML too large: {size} bytes"


class TestFormatHelpers:
    def test_fmt_thousands(self):
        assert _fmt(692000) == "692K"
        assert _fmt(5400) == "5.4K"

    def test_fmt_millions(self):
        assert _fmt(29000000) == "29M"

    def test_fmt_small(self):
        assert _fmt(500) == "500"

    def test_pct(self):
        assert _pct(70.9) == "70.9%"
        assert _pct(0) == "0.0%"


class TestSectionParser:
    def test_parses_structured_format(self):
        from agents.report_builder.html_builder_v2 import _parse_sections_from_text

        text = """\
FRAMEWORK_NAME: El análisis profundo
FRAMEWORK_THESIS: Lo que los datos realmente dicen.

===EXECUTIVE_CARD_1===
TITLE: Hallazgo uno
BODY: El primer dato importante.

===EXECUTIVE_CARD_2===
TITLE: Hallazgo dos
BODY: El segundo dato.

===NARRATIVE_1===
TITLE: La seguridad importa
BADGE: Dominante
BODY: La narrativa principal del caso.

===SCENARIO_A===
NAME: Sin acción
DESCRIPTION: Todo se enfría.
OUTCOME: Oportunidad perdida.
"""
        sections = _parse_sections_from_text(text)
        assert sections["cover_title"] == "El análisis profundo"
        assert len(sections["findings"]) >= 2
        assert len(sections["narratives"]) >= 1
        assert sections["narratives"][0]["title"] == "La seguridad importa"

    def test_parses_markdown_format(self):
        from agents.report_builder.html_builder_v2 import _parse_sections_from_text

        text = """\
## Resumen ejecutivo
1. Primer hallazgo importante del análisis.
2. Segundo hallazgo que cambia la lectura.

## Narrativas principales
### La seguridad es lo primero
La narrativa dominante en la conversación.

### El castigo es excesivo
Una narrativa minoritaria pero riesgosa.

## Lecturas estratégicas
### El servicio es el flanco real
Las quejas preexistentes son más urgentes.
Señal → la percepción de servicio condiciona todo.
"""
        sections = _parse_sections_from_text(text)
        assert len(sections["findings"]) >= 1
        assert len(sections["narratives"]) >= 1
        assert len(sections["readings"]) >= 1

    def test_empty_text(self):
        from agents.report_builder.html_builder_v2 import _parse_sections_from_text
        sections = _parse_sections_from_text("")
        assert sections["findings"] == []
        assert sections["narratives"] == []
