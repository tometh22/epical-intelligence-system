"""Unit tests for the Vista narrative classifier pipeline.

Run with:
    python -m pytest tests/test_vista_classifier.py -v

The classifier tests use a mocked Anthropic client so they run without
network or API key. The module-level `@pytest.mark.real_api` test calls
Haiku for real and skips if ANTHROPIC_API_KEY is not set.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.rancia_filter import (  # noqa: E402
    apply_rancia_filter,
    is_rancia,
)
from pipeline.vista_classifier import (  # noqa: E402
    classify_vista_dataframe,
    _parse_response,
)
from pipeline.vista_metrics import compute_vista_metrics  # noqa: E402
from pipeline.vista_models import VistaClassification  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# 15 synthetic mentions
# ──────────────────────────────────────────────────────────────────────

SYNTHETIC_MENTIONS = [
    # ── Eje 1 — Candidato / política (3) ────────────────────────────
    {
        "text": "Galuccio podría ser el próximo Macri. Tiene perfil de presidente para 2027.",
        "author": "@analista_pol", "platform": "X",
        "sentiment": "positivo", "sentiment_toward": "Galuccio",
        "date": "2026-04-25",
        "expected_eje": 1, "expected_rancia": False,
    },
    {
        "text": "El Galperin de la política argentina vendría de Vaca Muerta. Ojo a Galuccio.",
        "author": "@periodista_economia", "platform": "X",
        "sentiment": "positivo", "sentiment_toward": "Galuccio",
        "date": "2026-04-26",
        "expected_eje": 1, "expected_rancia": False,
    },
    {
        "text": "¿Y si Galuccio se anima a la Casa Rosada en 2027? Falta un técnico-empresario presidente.",
        "author": "@cronista_pol", "platform": "X",
        "sentiment": "neutral", "sentiment_toward": "Galuccio",
        "date": "2026-04-27",
        "expected_eje": 1, "expected_rancia": False,
    },

    # ── Eje 2 — Nuevo empresariado (3) ──────────────────────────────
    {
        "text": "Galuccio es el founder argentino industrial que faltaba. Otra generación, formado afuera.",
        "author": "@business_arg", "platform": "LinkedIn",
        "sentiment": "positivo", "sentiment_toward": "Galuccio",
        "date": "2026-04-25",
        "expected_eje": 2, "expected_rancia": False,
    },
    {
        "text": "Bajo perfil, técnico, internacional. Nada que ver con los Pérez Companc o los Bulgheroni.",
        "author": "@analista_oilgas", "platform": "X",
        "sentiment": "positivo", "sentiment_toward": "Galuccio",
        "date": "2026-04-26",
        "expected_eje": 2, "expected_rancia": False,
    },
    {
        "text": "Vista demuestra que el nuevo empresariado argentino no necesita la prebenda estatal de antes.",
        "author": "@think_tank_arg", "platform": "X",
        "sentiment": "positivo", "sentiment_toward": "Vista",
        "date": "2026-04-28",
        "expected_eje": 2, "expected_rancia": False,
    },

    # ── Eje 3 — Rol del empresariado / RIGI (3) ─────────────────────
    {
        "text": "El RIGI es un cheque en blanco para las petroleras. Galuccio aprovecha mientras Galperin habla.",
        "author": "@critico_rigi", "platform": "X",
        "sentiment": "negativo", "sentiment_toward": "Galuccio",
        "date": "2026-04-29",
        "expected_eje": 3, "expected_rancia": False,
    },
    {
        "text": "Los empresarios argentinos deberían comprometerse o callarse. ¿Vista de qué lado está?",
        "author": "@editor_diario", "platform": "X",
        "sentiment": "neutral", "sentiment_toward": "Vista",
        "date": "2026-04-30",
        "expected_eje": 3, "expected_rancia": False,
    },
    {
        "text": "Subsidios estatales a Vista vía RIGI: ¿hasta cuándo el empresariado vive del Estado?",
        "author": "@analista_macro", "platform": "X",
        "sentiment": "negativo", "sentiment_toward": "Vista",
        "date": "2026-05-01",
        "expected_eje": 3, "expected_rancia": False,
    },

    # ── Rancia anti-petrolera (3) — deben ser filtradas ─────────────
    {
        "text": "Fracking asesino, petroleras genocidas, basta de extractivismo asesino en Vaca Muerta.",
        "author": "@activist_eco", "platform": "X",
        "sentiment": "negativo", "sentiment_toward": None,
        "date": "2026-04-25",
        "expected_eje": None, "expected_rancia": True,
    },
    {
        "text": "Veneno, vendepatrias, extractivismo asesino. Basta.",
        "author": "@anon_user", "platform": "X",
        "sentiment": "negativo", "sentiment_toward": None,
        "date": "2026-04-26",
        "expected_eje": None, "expected_rancia": True,
    },
    {
        "text": "Vista contamina y nadie hace nada en Argentina.",
        "author": "@laizquierdadiario", "platform": "X",
        "sentiment": "negativo", "sentiment_toward": "Vista",
        "date": "2026-04-27",
        "expected_eje": None, "expected_rancia": True,
    },

    # ── Eje 0 — irrelevantes / fuera de los tres ejes (3) ───────────
    {
        "text": "VIST cerró +2% hoy, buenos balances trimestrales en NYSE.",
        "author": "@bloomberg_arg", "platform": "X",
        "sentiment": "positivo", "sentiment_toward": "Vista",
        "date": "2026-04-25",
        "expected_eje": 0, "expected_rancia": False,
    },
    {
        "text": "Lindo día en Bariloche con la familia.",
        "author": "@usuario_random", "platform": "X",
        "sentiment": "neutral", "sentiment_toward": None,
        "date": "2026-04-26",
        "expected_eje": 0, "expected_rancia": False,
    },
    {
        "text": "Vista anunció una nueva planta de tratamiento de aguas en Mendoza.",
        "author": "@cuenca_neuquina", "platform": "X",
        "sentiment": "neutral", "sentiment_toward": "Vista",
        "date": "2026-04-28",
        "expected_eje": 0, "expected_rancia": False,
    },
]


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    """The 15 synthetic mentions as a DataFrame with the canonical schema."""
    return pd.DataFrame(SYNTHETIC_MENTIONS)


# ──────────────────────────────────────────────────────────────────────
# Mock Anthropic client
# ──────────────────────────────────────────────────────────────────────

def make_mock_client(responses: Iterable[str]):
    """Build a stand-in for `anthropic.Anthropic` whose `.messages.create()`
    returns each response in `responses` in order. After exhaustion it raises
    StopIteration — which surfaces as a parse_error fallback in the
    classifier (since it catches Exception in _call_haiku_batch).
    """
    iterator = iter(responses)
    call_log: list[dict] = []

    def _create(**kwargs):
        call_log.append(kwargs)
        text = next(iterator)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])

    client = SimpleNamespace(
        messages=SimpleNamespace(create=_create),
        _calls=call_log,
    )
    return client


def _mk_response(classifications: list[dict]) -> str:
    return json.dumps(classifications, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────
# Rancia filter tests
# ──────────────────────────────────────────────────────────────────────

class TestRanciaFilter:

    def test_catches_three_synthetic_rancia(self, synthetic_df):
        rancia_rows = synthetic_df[synthetic_df["expected_rancia"]]
        for _, row in rancia_rows.iterrows():
            flag, reason = is_rancia(row.to_dict())
            assert flag is True, f"Should flag as rancia: {row['text']!r} (reason={reason!r})"
            assert reason, f"Reason should be non-empty for rancia: {row['text']!r}"

    def test_does_not_catch_political_critique_with_rancia_keywords(self):
        # Has 'extractivismo' AND 'asesino' AND 'vendepatrias' (3 keywords)
        # but mentions Milei → political actor present → NOT rancia.
        mention = {
            "text": "Milei vendepatrias por entregar el RIGI a las petroleras. Extractivismo asesino.",
            "author": "@critico_rigi",
        }
        flag, reason = is_rancia(mention)
        assert flag is False
        assert "has_political_actor" in reason

    def test_role_keyword_protects(self):
        mention = {
            "text": "El ministro de energía habla de extractivismo y veneno.",
            "author": "@user",
        }
        flag, _ = is_rancia(mention)
        assert flag is False

    def test_domain_match_catches_even_without_keywords(self):
        # No rancia keywords, but the author handle matches the domain list.
        mention = {
            "text": "Vista anunció nueva inversión en infraestructura.",
            "author": "@laizquierdadiario",
        }
        flag, reason = is_rancia(mention)
        assert flag is True
        assert reason == "rancia_domain"

    def test_below_threshold_is_not_rancia(self):
        # Only one keyword → not rancia regardless of actor presence.
        mention = {"text": "Solo me preocupa el extractivismo en Vaca Muerta.", "author": "@u"}
        flag, _ = is_rancia(mention)
        assert flag is False

    def test_apply_rancia_filter_splits_correctly(self, synthetic_df):
        df_no_rancia, df_rancia = apply_rancia_filter(synthetic_df)
        assert len(df_rancia) == 3, f"Expected 3 rancia rows, got {len(df_rancia)}"
        assert len(df_no_rancia) == 12, f"Expected 12 non-rancia rows, got {len(df_no_rancia)}"
        assert "is_rancia" in df_no_rancia.columns
        assert "rancia_reason" in df_no_rancia.columns
        assert df_no_rancia["is_rancia"].sum() == 0
        assert df_rancia["is_rancia"].all()

    def test_apply_rancia_filter_handles_missing_optional_columns(self):
        df = pd.DataFrame({"text": ["Vista contamina y nadie hace nada"]})
        df_no_rancia, df_rancia = apply_rancia_filter(df)
        assert len(df_no_rancia) + len(df_rancia) == 1


# ──────────────────────────────────────────────────────────────────────
# Classifier tests (mocked Haiku)
# ──────────────────────────────────────────────────────────────────────

class TestVistaClassifierMocked:

    def test_eje_1_political(self, synthetic_df):
        eje_1_df = synthetic_df[synthetic_df["expected_eje"] == 1].reset_index(drop=True)
        canned = [
            {"eje_narrativo": 1, "framing_dominante": "candidato 2027", "confianza": 0.9, "razon": "habla de Casa Rosada y compara con Macri"},
            {"eje_narrativo": 1, "framing_dominante": "el Galperin de la política", "confianza": 0.85, "razon": "comparación política con figura founder"},
            {"eje_narrativo": 1, "framing_dominante": "técnico-empresario para Casa Rosada", "confianza": 0.88, "razon": "explícito sobre 2027"},
        ]
        client = make_mock_client([_mk_response(canned)])

        out_df, stats = classify_vista_dataframe(eje_1_df, client=client, batch_size=10)

        assert (out_df["eje_narrativo"] == 1).all()
        assert (out_df["framing_dominante"].astype(str).str.len() > 0).all()
        assert stats["classified"] == 3
        assert stats["parse_errors"] == 0

    def test_eje_2_empresariado(self, synthetic_df):
        eje_2_df = synthetic_df[synthetic_df["expected_eje"] == 2].reset_index(drop=True)
        canned = [
            {"eje_narrativo": 2, "framing_dominante": "founder industrial argentino", "confianza": 0.9, "razon": "frame founder explícito"},
            {"eje_narrativo": 2, "framing_dominante": "otra generación que los Bulgheroni", "confianza": 0.85, "razon": "comparación generacional"},
            {"eje_narrativo": 2, "framing_dominante": "sin prebenda estatal", "confianza": 0.8, "razon": "tensión nuevo vs viejo empresariado"},
        ]
        client = make_mock_client([_mk_response(canned)])
        out_df, _ = classify_vista_dataframe(eje_2_df, client=client, batch_size=10)
        assert (out_df["eje_narrativo"] == 2).all()

    def test_eje_3_rol(self, synthetic_df):
        eje_3_df = synthetic_df[synthetic_df["expected_eje"] == 3].reset_index(drop=True)
        canned = [
            {"eje_narrativo": 3, "framing_dominante": "RIGI cheque en blanco", "confianza": 0.9, "razon": "crítica explícita al RIGI"},
            {"eje_narrativo": 3, "framing_dominante": "comprometerse o callarse", "confianza": 0.85, "razon": "tensión silenciosos vs comprometidos"},
            {"eje_narrativo": 3, "framing_dominante": "subsidios via RIGI", "confianza": 0.88, "razon": "rol estatal del empresariado"},
        ]
        client = make_mock_client([_mk_response(canned)])
        out_df, _ = classify_vista_dataframe(eje_3_df, client=client, batch_size=10)
        assert (out_df["eje_narrativo"] == 3).all()

    def test_eje_0_irrelevant(self, synthetic_df):
        eje_0_df = synthetic_df[synthetic_df["expected_eje"] == 0].reset_index(drop=True)
        canned = [
            {"eje_narrativo": 0, "framing_dominante": "", "confianza": 0.7, "razon": "cobertura bursátil seca"},
            {"eje_narrativo": 0, "framing_dominante": "", "confianza": 0.95, "razon": "no menciona Vista"},
            {"eje_narrativo": 0, "framing_dominante": "", "confianza": 0.6, "razon": "comunicado técnico sin frame mayor"},
        ]
        client = make_mock_client([_mk_response(canned)])
        out_df, _ = classify_vista_dataframe(eje_0_df, client=client, batch_size=10)
        assert (out_df["eje_narrativo"] == 0).all()

    def test_handles_invalid_json_gracefully(self, synthetic_df):
        # Haiku returns garbage. Classifier must produce fallback rows, not crash.
        client = make_mock_client(["this is not json at all"])
        eje_1_df = synthetic_df[synthetic_df["expected_eje"] == 1].reset_index(drop=True)
        out_df, stats = classify_vista_dataframe(eje_1_df, client=client, batch_size=10)
        assert len(out_df) == len(eje_1_df)
        assert (out_df["eje_narrativo"] == 0).all()
        assert stats["parse_errors"] == 3
        assert (out_df["eje_razon"].str.startswith("parse_error")).all()

    def test_handles_validation_error_per_row(self, synthetic_df):
        # First row is valid, second has eje_narrativo=99 → coerced to 0,
        # third has confianza=2.0 → clamped to 1.0.
        canned = [
            {"eje_narrativo": 1, "framing_dominante": "ok", "confianza": 0.8, "razon": "ok"},
            {"eje_narrativo": 99, "framing_dominante": "bad axis", "confianza": 0.5, "razon": "outlier axis"},
            {"eje_narrativo": 1, "framing_dominante": "ok", "confianza": 2.0, "razon": "outlier conf"},
        ]
        client = make_mock_client([_mk_response(canned)])
        eje_1_df = synthetic_df[synthetic_df["expected_eje"] == 1].reset_index(drop=True)
        out_df, _ = classify_vista_dataframe(eje_1_df, client=client, batch_size=10)
        assert int(out_df.iloc[0]["eje_narrativo"]) == 1
        assert int(out_df.iloc[1]["eje_narrativo"]) == 0  # coerced
        assert float(out_df.iloc[2]["eje_confianza"]) == 1.0  # clamped

    def test_skip_already_classified(self, synthetic_df):
        df = synthetic_df[synthetic_df["expected_eje"] == 1].reset_index(drop=True).copy()
        df["eje_narrativo"] = [1, 1, 1]
        df["framing_dominante"] = ["pre", "pre", "pre"]
        df["eje_confianza"] = [0.9, 0.9, 0.9]
        df["eje_razon"] = ["pre", "pre", "pre"]

        client = make_mock_client([])  # no responses available — would raise if called

        out_df, stats = classify_vista_dataframe(df, client=client, batch_size=10)

        assert stats["to_classify"] == 0
        assert stats["skipped_already_classified"] == 3
        assert stats["classified"] == 0
        assert client._calls == []  # never called Haiku

    def test_parse_response_strips_markdown_fences(self):
        text = '```json\n[{"eje_narrativo": 1, "framing_dominante": "x", "confianza": 0.5, "razon": "ok"}]\n```'
        results = _parse_response(text, expected_n=1)
        assert len(results) == 1
        assert results[0].eje_narrativo == 1


# ──────────────────────────────────────────────────────────────────────
# Full-pipeline integration (rancia + classifier + metrics)
# ──────────────────────────────────────────────────────────────────────

class TestFullPipeline:

    def test_rancia_then_classifier_then_metrics(self, synthetic_df):
        # 1. Rancia filter — should remove 3, leave 12 for the classifier.
        df_no_rancia, df_rancia = apply_rancia_filter(synthetic_df)
        assert len(df_rancia) == 3
        assert len(df_no_rancia) == 12

        # 2. Build a canned response for the 12 remaining mentions in the
        #    order they appear in df_no_rancia.
        canned_for_remaining: list[dict] = []
        for _, row in df_no_rancia.iterrows():
            axis = int(row["expected_eje"])
            canned_for_remaining.append({
                "eje_narrativo": axis,
                "framing_dominante": f"frame_eje_{axis}",
                "confianza": 0.85,
                "razon": f"synthetic eje {axis}",
            })

        client = make_mock_client([_mk_response(canned_for_remaining)])
        df_classified, stats = classify_vista_dataframe(
            df_no_rancia, client=client, batch_size=25,
        )

        # 3. Assertions on classification.
        assert stats["classified"] == 12
        assert stats["parse_errors"] == 0
        assert (df_classified["eje_narrativo"] == df_classified["expected_eje"]).all()

        # The classifier must have been called exactly once with 12 mentions
        # in the user prompt (one batch of 12 ≤ batch_size 25).
        assert len(client._calls) == 1
        prompt = client._calls[0]["messages"][0]["content"]
        # All 12 mentions should appear (numbered 1..12)
        for i in range(1, 13):
            assert f"\n{i}." in "\n" + prompt or prompt.startswith(f"{i}.")

        # 4. None of the 3 rancia mentions reached Haiku.
        rancia_texts = synthetic_df[synthetic_df["expected_rancia"]]["text"].tolist()
        for t in rancia_texts:
            # The first 30 chars of each rancia mention should NOT be in the prompt.
            assert t[:30] not in prompt, f"Rancia mention leaked into Haiku prompt: {t!r}"

        # 5. Metrics — counts per axis match expected.
        metrics = compute_vista_metrics(df_classified)
        assert metrics["total_mentions"] == 12
        assert metrics["by_axis"]["1"]["count"] == 3
        assert metrics["by_axis"]["2"]["count"] == 3
        assert metrics["by_axis"]["3"]["count"] == 3
        assert metrics["by_axis"]["0"]["count"] == 3

        # 6. Top framings exist for each non-zero axis.
        for axis in ("1", "2", "3"):
            assert metrics["top_framings_by_axis"][axis], f"No framings for eje {axis}"
            top = metrics["top_framings_by_axis"][axis][0]
            assert top["framing"] == f"frame_eje_{axis}"
            assert top["count"] == 3


# ──────────────────────────────────────────────────────────────────────
# Optional: real Haiku call (skip if no API key)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.real_api
def test_classifier_against_real_haiku():
    """Call Haiku for real on one mention. Skipped without ANTHROPIC_API_KEY."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    df = pd.DataFrame([{
        "text": "Galuccio podría ser el próximo Macri. Tiene perfil presidencial para 2027.",
        "author": "@analista_pol",
        "platform": "X",
        "sentiment_toward": "Galuccio",
    }])
    out, stats = classify_vista_dataframe(df, batch_size=5)
    assert stats["classified"] == 1
    # We don't lock the exact axis (Haiku is probabilistic), but parse_error
    # should be 0 — i.e. the response was structurally valid.
    assert stats["parse_errors"] == 0
    assert out.iloc[0]["eje_narrativo"] in (0, 1, 2, 3)
