"""Pydantic v2 models for the Vista narrative classifier.

These models are the contract between Haiku's JSON output and the
DataFrame columns produced by the classifier. They are deliberately
permissive (clamping/truncating instead of raising) so that one bad
mention does not poison a whole batch.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class VistaMentionInput(BaseModel):
    """A single mention sent to Haiku for narrative classification."""

    text: str
    autor: Optional[str] = None
    plataforma: Optional[str] = None
    sentiment_toward: Optional[str] = None


class VistaClassification(BaseModel):
    """One classification result. Mirrors the JSON object Haiku returns.

    Validators are mode='before' so that quirky model output (string
    integers, out-of-bound confidence, oversized strings) is coerced
    rather than rejected. The classifier owns the fallback path for
    truly unparseable responses.
    """

    eje_narrativo: Literal[0, 1, 2, 3]
    framing_dominante: str = ""
    confianza: float = Field(ge=0.0, le=1.0)
    razon: str = ""

    @field_validator("eje_narrativo", mode="before")
    @classmethod
    def _coerce_axis(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return n if n in (0, 1, 2, 3) else 0

    @field_validator("confianza", mode="before")
    @classmethod
    def _coerce_confianza(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("framing_dominante", mode="before")
    @classmethod
    def _coerce_framing(cls, v):
        return str(v or "").strip()[:80]

    @field_validator("razon", mode="before")
    @classmethod
    def _coerce_razon(cls, v):
        return str(v or "").strip()[:200]


class VistaBatchResponse(BaseModel):
    """Wrapper around a list of classifications, one per mention in the batch."""

    results: List[VistaClassification]
