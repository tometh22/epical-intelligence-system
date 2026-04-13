"""Tests for the Conversational Report Builder Agent.

Tests the state machine transitions and checkpoint flow.
Uses SentimIA mock mode to avoid real API calls.

Run with: python -m pytest tests/test_agent.py -v
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agents.report_builder.agent import (
    ReportBuilderAgent,
    AgentState,
    CheckpointMessage,
)


@pytest.fixture
def sample_csv(tmp_path):
    """Create a realistic test CSV."""
    import pandas as pd
    from datetime import datetime, timedelta

    n = 200
    base_date = datetime(2026, 3, 29)
    rows = []
    for i in range(n):
        rows.append({
            "date": (base_date + timedelta(days=i % 10)).strftime("%Y-%m-%d"),
            "text": [
                "Terrible servicio de la marca, irresponsable total",
                "Apoyo total a la marca, hicieron bien",
                "El actor fue irresponsable con los pasajeros",
                "¿Justicia o exageración? Gran debate",
                "La seguridad aérea es lo primero, no es un juego",
            ][i % 5],
            "sentiment": ["negativo", "positivo", "negativo", "neutro", "positivo"][i % 5],
            "author": f"@user_{i % 30}",
            "platform": ["Twitter", "Facebook", "TikTok", "Instagram"][i % 4],
            "engagement": (i + 1) * 10,
            "likes": (i + 1) * 8,
            "comments": i,
            "shares": i // 2,
            "reach": (i % 30 + 1) * 5000,
            "actor": ["brand", "actor", "brand", "otros", "actor"][i % 5],
        })

    df = pd.DataFrame(rows)
    csv_path = tmp_path / "test_data.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def agent(sample_csv, tmp_path):
    """Create an agent in mock mode for testing."""
    return ReportBuilderAgent(
        client_name="TestCorp",
        period="Marzo 2026",
        brief="Análisis de la conversación digital sobre TestCorp.",
        file_paths=[str(sample_csv)],
        brand="TestCorp",
        actors=["Actor1"],
        source_types=["csv"],
        client_role="la Dirección de Comunicaciones",
        report_type="crisis",
        sentimia_mock=True,
        output_dir=str(tmp_path / "outputs"),
    )


class TestAgentLifecycle:
    def test_initial_state(self, agent):
        assert agent.state == AgentState.INIT

    def test_phase1_reaches_checkpoint1(self, agent):
        result = agent.run_phase1()
        assert agent.state == AgentState.CHECKPOINT_1
        assert isinstance(result, CheckpointMessage)
        assert result.checkpoint == 1

    def test_checkpoint1_has_required_info(self, agent):
        result = agent.run_phase1()
        assert "TESIS PRINCIPAL" in result.summary
        assert "HALLAZGOS" in result.summary
        assert "AUDITORÍA" in result.summary
        assert "HTML borrador" in result.summary
        assert len(result.attachments) >= 1

    def test_advance_from_checkpoint1_to_checkpoint2(self, agent):
        agent.run_phase1()
        result = agent.advance("La tesis está bien, pero agregá más análisis de plataformas.")
        assert agent.state == AgentState.CHECKPOINT_2
        assert isinstance(result, CheckpointMessage)
        assert result.checkpoint == 2

    def test_approve_checkpoint1(self, agent):
        agent.run_phase1()
        result = agent.advance("Ok, seguí")
        assert agent.state == AgentState.CHECKPOINT_2
        assert result.checkpoint == 2

    def test_advance_from_checkpoint2_to_checkpoint3(self, agent):
        agent.run_phase1()
        agent.advance("Ok, seguí")
        result = agent.advance("Listo, generá el PDF")
        assert agent.state == AgentState.CHECKPOINT_3
        assert isinstance(result, CheckpointMessage)
        assert result.checkpoint == 3

    def test_checkpoint3_has_verification(self, agent):
        agent.run_phase1()
        agent.advance("Ok")
        result = agent.advance("Dale, PDF")
        assert "Verificación final" in result.summary
        assert "slides" in result.details
        assert "charts" in result.details

    def test_advance_from_checkpoint3_to_done(self, agent):
        agent.run_phase1()
        agent.advance("Ok")
        agent.advance("Listo")
        result = agent.advance("Perfecto, gracias")
        assert agent.state == AgentState.DONE
        assert isinstance(result, dict)
        assert result["status"] == "completed"

    def test_full_lifecycle(self, agent):
        """Full 3-checkpoint lifecycle end to end."""
        # Phase 1
        cp1 = agent.run_phase1()
        assert cp1.checkpoint == 1

        # Phase 2
        cp2 = agent.advance("Agregá más detalle sobre las plataformas")
        assert cp2.checkpoint == 2

        # Phase 3
        cp3 = agent.advance("Listo, generá el PDF")
        assert cp3.checkpoint == 3

        # Done
        final = agent.advance("Ok")
        assert final["status"] == "completed"
        assert final["html_versions"] >= 1


class TestAgentState:
    def test_cannot_advance_from_init(self, agent):
        with pytest.raises(RuntimeError, match="Cannot advance"):
            agent.advance("feedback")

    def test_cannot_advance_from_processing(self, agent):
        agent.state = AgentState.PROCESSING
        with pytest.raises(RuntimeError, match="Cannot advance"):
            agent.advance("feedback")


class TestAgentOutputs:
    def test_html_generated(self, agent):
        agent.run_phase1()
        assert agent.ctx.html_path is not None
        assert Path(agent.ctx.html_path).exists()

    def test_json_generated(self, agent):
        agent.run_phase1()
        assert agent.ctx.json_path is not None
        assert Path(agent.ctx.json_path).exists()

    def test_html_version_increments(self, agent):
        agent.run_phase1()
        v1 = agent.ctx.html_version
        agent.advance("Cambiá la tesis")
        assert agent.ctx.html_version == v1 + 1

    def test_metrics_populated(self, agent):
        agent.run_phase1()
        m = agent.ctx.metrics
        assert m.get("total_mentions", 0) > 0
        assert "sentiment_breakdown" in m
        assert "engagement_by_platform" in m
        assert "timeline" in m
        assert "spikes" in m
        assert "reach_deduplicated" in m


class TestAgentRules:
    def test_rules_validated_at_checkpoint1(self, agent):
        cp1 = agent.run_phase1()
        # rule_violations should be a non-empty string (at minimum info-level)
        assert isinstance(cp1.rule_violations, str)

    def test_rules_validated_at_checkpoint3(self, agent):
        agent.run_phase1()
        agent.advance("Ok")
        cp3 = agent.advance("PDF")
        assert "violations_report" in cp3.details


class TestFeedbackLog:
    def test_feedback_recorded(self, agent):
        agent.run_phase1()
        agent.advance("Cambiar tesis")
        assert len(agent.ctx.feedback_log) == 1
        assert agent.ctx.feedback_log[0]["feedback"] == "Cambiar tesis"

    def test_multiple_feedbacks(self, agent):
        agent.run_phase1()
        agent.advance("Feedback 1")
        agent.advance("Feedback 2")
        agent.advance("Done")
        assert len(agent.ctx.feedback_log) == 3
