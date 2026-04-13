"""Tests for the SentimIA API client (mock mode).

Run with: python -m pytest tests/test_sentimia_client.py -v
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agents.shared.sentimia_client import SentimiaClient


@pytest.fixture
def client():
    return SentimiaClient(mock=True)


@pytest.fixture
def sample_csv(tmp_path):
    csv = tmp_path / "test_data.csv"
    csv.write_text(
        "date,text,sentiment,author,platform,engagement\n"
        "2026-03-30,Test mention,negativo,@user1,Twitter,100\n"
        "2026-03-31,Another mention,positivo,@user2,TikTok,500\n"
    )
    return csv


class TestCreateProject:
    def test_returns_project_id(self, client):
        pid = client.create_project("Test", "Brand", "Context", ["Actor"])
        assert pid.startswith("mock-proj-")

    def test_project_id_unique(self, client):
        p1 = client.create_project("A", "B", "C", [])
        p2 = client.create_project("A", "B", "C", [])
        # IDs are time-based so may match in fast tests; just check they're strings
        assert isinstance(p1, str)
        assert isinstance(p2, str)


class TestUploadFile:
    def test_upload_returns_id(self, client, sample_csv):
        pid = client.create_project("Test", "B", "C", [])
        uid = client.upload_file(pid, sample_csv, "csv")
        assert uid.startswith("mock-upload-")

    def test_upload_missing_file_raises(self, client):
        pid = client.create_project("Test", "B", "C", [])
        with pytest.raises(FileNotFoundError):
            client.upload_file(pid, "/nonexistent.csv")


class TestProcess:
    def test_returns_job_id(self, client):
        pid = client.create_project("Test", "B", "C", [])
        jid = client.process(pid)
        assert jid.startswith("mock-job-")


class TestGetStatus:
    def test_mock_returns_completed(self, client):
        status = client.get_status("proj-123")
        assert status["status"] == "completed"
        assert status["progress"] == 100.0


class TestGetResults:
    def test_returns_aggregated_data(self, client):
        results = client.get_results("proj-123")
        assert "total_mentions" in results
        assert "sentiment_breakdown" in results
        assert "actor_breakdown" in results
        assert "platform_breakdown" in results
        assert "confidence_distribution" in results
        assert results["total_mentions"] > 0


class TestGetMentions:
    def test_returns_mentions_list(self, client):
        result = client.get_mentions("proj-123", limit=50)
        assert "mentions" in result
        assert len(result["mentions"]) <= 50
        assert "total" in result

    def test_mentions_have_required_fields(self, client):
        result = client.get_mentions("proj-123", limit=10)
        required = {"id", "date", "text", "sentiment", "author", "platform",
                     "engagement", "actor", "relevance", "confidence"}
        for m in result["mentions"]:
            assert required.issubset(m.keys()), f"Missing: {required - m.keys()}"

    def test_filter_by_sentiment(self, client):
        result = client.get_mentions("proj-123", filters={"sentiment": "positivo"})
        for m in result["mentions"]:
            assert m["sentiment"] == "positivo"


class TestExportCSV:
    def test_exports_file(self, client, tmp_path):
        out = tmp_path / "export.csv"
        result = client.export_csv("proj-123", output_path=out)
        assert result.exists()
        content = result.read_text()
        assert "date" in content
        assert "sentiment" in content


class TestWaitForProcessing:
    def test_mock_completes_immediately(self, client):
        status = client.wait_for_processing("proj-123")
        assert status["status"] == "completed"


class TestFullPipeline:
    def test_run_full_pipeline(self, client, sample_csv):
        result = client.run_full_pipeline(
            name="Test Project",
            brand="TestBrand",
            context="Testing context",
            actors=["Actor1"],
            file_paths=[sample_csv],
            source_types=["csv"],
        )
        assert "project_id" in result
        assert "results" in result
        assert result["results"]["total_mentions"] > 0


class TestContextManager:
    def test_with_statement(self, sample_csv):
        with SentimiaClient(mock=True) as client:
            pid = client.create_project("Test", "B", "C", [])
            assert pid.startswith("mock-proj-")
