"""Narrative classifier for Vista Energy mentions.

For each mention, asks Haiku to assign one of four narrative axes
(0/1/2/3) and the dominant framing string. See `EJE_DEFINITIONS` for
the axis ontology.

Operates on a pandas DataFrame with at minimum a 'text' column.
Optional metadata columns ('author', 'platform', 'sentiment_toward')
are passed to Haiku as context. Output columns added:
    eje_narrativo     Int64 (0/1/2/3, nullable)
    framing_dominante string
    eje_confianza     float
    eje_razon         string
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable, List, Optional, Tuple

import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

from agents.shared.logger import get_logger
from pipeline.vista_models import VistaClassification, VistaMentionInput

load_dotenv()

logger = get_logger("vista")

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

HAIKU_MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 15
MAX_RETRIES_PER_BATCH = 1
MAX_OUTPUT_TOKENS = 8192  # ~280 tokens/result × 15 = 4200; double-headroom for safety
MAX_TEXT_CHARS = 500  # truncate mention text sent to Haiku


EJE_DEFINITIONS = """\
TRES EJES NARRATIVOS sobre Miguel Galuccio (CEO Vista Energy, NYSE:VIST) y Vista:

EJE 1 — "Candidato de este estilo"
Empresario candidato. Salto a la política. Comparaciones con Macri / Milei /
Galperin como figura política. Conversación sobre Casa Rosada / 2027 /
presidencial. Sub-frame "empresario que se compromete con el país" como figura
pública post-empresarial. Galuccio como posible candidato. Especulación
electoral con su nombre.
Ejemplos textuales:
- "Galuccio podría ser el próximo Macri"
- "El nuevo Galperin de la política"
- "¿Y si va por la Casa Rosada en 2027?"
- "Falta un técnico-empresario en la política argentina"

EJE 2 — "Nuevo empresariado"
Galuccio como arquetipo del nuevo empresario argentino. Comparaciones
generacionales con Pérez Companc / Bulgheroni / Macri padre / Rocca padre.
Atributos founder / técnico / internacional / low profile / global. Tensión
viejo vs nuevo empresariado. Frame "founder argentino industrial". Generación
post-prebenda.
Ejemplos textuales:
- "Galuccio es el founder argentino que faltaba"
- "Otra generación: ya no son los Pérez Companc"
- "Bajo perfil, técnico, formado afuera"
- "Vista demuestra que se puede sin Estado"

EJE 3 — "Rol de empresarios en esta nueva época"
Debate post-Milei sobre el rol público del empresariado. Tensiones apolíticos
vs políticos, técnicos vs ideológicos, locales vs internacionales, silenciosos
vs comprometidos. Frame "empresarios crueles". Subsidios RIGI. Posicionamiento
de Galuccio en ese mapa. Discusión sectorial sobre el lugar del empresariado.
Ejemplos textuales:
- "El RIGI es un cheque en blanco para los empresarios"
- "Los empresarios deberían comprometerse o callarse"
- "Galperin habla, Galuccio calla — ¿qué es mejor?"
- "Subsidios estatales a las petroleras: ¿hasta cuándo?"

EJE 0 — Ninguno de los tres
Mención de Galuccio / Vista que NO encaja en los ejes anteriores. Por ejemplo:
cobertura técnica de Vaca Muerta sin frame político/empresarial mayor; dato
bursátil seco; comentario casual sin peso institucional; mención de viajes /
CSR / lifestyle; spam o copy genérico de PR.
"""


RELEVANCE_AGUILO = """\
FILTRO DE RELEVANCIA (Criterio Aguiló):
Solo cuentan menciones que provengan de — o citen explícitamente a — actores
con peso institucional:
- Políticos en ejercicio o reconocidos
- Funcionarios públicos
- Empresarios identificables (CEO, fundadores, directivos públicos)
- Periodistas, columnistas, editores
- Analistas, economistas, consultores
- Think tanks, fundaciones, cámaras
- Cuentas anónimas con peso institucional comprobable (verificadas con +50K
  seguidores, columnistas habituales, etc.)

Si la mención es de una cuenta sin peso (usuario común, troll, bot, comentario
sin contexto), clasificá eje_narrativo=0 con baja confianza. La calidad del
frame importa más que el volumen.
"""


SYSTEM_PROMPT = f"""You are a narrative classifier for mentions about Miguel \
Galuccio (CEO Vista Energy, NYSE:VIST) and Vista Energy.

Context: Galuccio appeared in the LA NACION + EY interview series "Hacedores \
que inspiran" on April 24, 2026. We are tracking how the conversation evolved \
from April 24 to May 5, 2026.

Your task: classify each mention into ONE of four narrative axes AND extract \
its dominant framing.

{EJE_DEFINITIONS}

{RELEVANCE_AGUILO}

For each mention, return a JSON object with:
- eje_narrativo: 0, 1, 2, or 3 (integer)
- framing_dominante: short string (≤80 chars) describing the SPECIFIC frame
  the mention reproduces. Examples: "padre de Vaca Muerta",
  "cheque en blanco a US$8B", "founder industrial argentino",
  "el que volvió", "subsidios via RIGI", "low profile vs Galperin".
  Empty string if no clear frame.
- confianza: 0.0–1.0 (your confidence in the classification)
- razon: short justification (≤200 chars) for audit purposes

Detect SUBTLE framings, not just literal mentions. A mention saying
"otro tipo distinto al de los Pérez Companc" is eje 2 even if it never
uses the word "founder".

Respond with ONLY a JSON array, one entry per mention, in input order.
No markdown fences. No prose before or after.

Example response for 2 mentions:
[
  {{"eje_narrativo": 1, "framing_dominante": "candidato técnico para 2027", "confianza": 0.85, "razon": "compara explícitamente con Macri y menciona Casa Rosada"}},
  {{"eje_narrativo": 0, "framing_dominante": "", "confianza": 0.6, "razon": "cobertura bursátil seca, sin frame político ni empresarial"}}
]
"""


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

def _fallback_classification(reason: str) -> VistaClassification:
    return VistaClassification(
        eje_narrativo=0,
        framing_dominante="",
        confianza=0.0,
        razon=f"parse_error:{reason}"[:200],
    )


def _build_user_prompt(batch: List[VistaMentionInput]) -> str:
    lines = [f"Classify these {len(batch)} mentions about Galuccio / Vista:"]
    for i, m in enumerate(batch, 1):
        meta_parts = []
        if m.plataforma:
            meta_parts.append(f"plataforma={m.plataforma}")
        if m.autor:
            meta_parts.append(f"autor={m.autor}")
        if m.sentiment_toward:
            meta_parts.append(f"sentiment_toward={m.sentiment_toward}")
        meta_str = f" [{', '.join(meta_parts)}]" if meta_parts else ""
        text = (m.text or "")[:MAX_TEXT_CHARS]
        lines.append(f"{i}.{meta_str} {text}")
    return "\n".join(lines)


def _parse_response(text: str, expected_n: int) -> List[VistaClassification]:
    """Parse a Haiku response into a list of VistaClassification.

    Resilient to markdown fences and short/long arrays. On unrecoverable
    failure, returns a list of fallback classifications of the expected
    length so the caller can still write rows.
    """
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s — first 200 chars: %r", e, cleaned[:200])
        return [_fallback_classification("json_decode") for _ in range(expected_n)]

    if not isinstance(data, list):
        logger.warning("Response is not a JSON array (got %s)", type(data).__name__)
        return [_fallback_classification("not_a_list") for _ in range(expected_n)]

    results: List[VistaClassification] = []
    for item in data:
        try:
            results.append(VistaClassification.model_validate(item))
        except ValidationError as e:
            logger.warning("Validation failed for item %r: %s", item, e)
            results.append(_fallback_classification("validation"))

    while len(results) < expected_n:
        results.append(_fallback_classification("missing_in_response"))

    return results[:expected_n]


def _call_haiku_batch(
    client: Anthropic,
    batch: List[VistaMentionInput],
) -> List[VistaClassification]:
    """Send one batch to Haiku, with one retry on transport/parse error."""
    if not batch:
        return []

    user_prompt = _build_user_prompt(batch)
    last_err: Optional[Exception] = None

    for attempt in range(MAX_RETRIES_PER_BATCH + 1):
        try:
            message = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            response_text = message.content[0].text
            return _parse_response(response_text, len(batch))
        except Exception as e:  # noqa: BLE001 — transport/SDK errors are heterogeneous
            last_err = e
            logger.warning("Haiku call failed on attempt %d/%d: %s",
                           attempt + 1, MAX_RETRIES_PER_BATCH + 1, e)

    logger.error("All %d attempts failed for batch of %d (last error: %s)",
                 MAX_RETRIES_PER_BATCH + 1, len(batch), last_err)
    return [_fallback_classification("api_error") for _ in batch]


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def classify_vista_dataframe(
    df: pd.DataFrame,
    *,
    client: Optional[Anthropic] = None,
    batch_size: int = BATCH_SIZE,
    skip_already_classified: bool = True,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> Tuple[pd.DataFrame, dict]:
    """Add narrative-axis columns to a DataFrame.

    Args:
        df: Input frame. Required column: text. Optional: author, platform,
            sentiment_toward.
        client: Anthropic client. If None, builds one from ANTHROPIC_API_KEY.
            Inject a mock for tests.
        batch_size: Mentions per Haiku call.
        skip_already_classified: If True, skip rows that already have
            eje_narrativo populated. Enables re-running on a partially
            classified CSV without re-billing the full dataset.
        on_progress: Callback (batch_index_1based, total_batches).

    Returns:
        (enriched_df, stats_dict)
    """
    if df is None or df.empty:
        return (df.copy() if df is not None else pd.DataFrame()), {
            "total_rows": 0, "to_classify": 0, "skipped_already_classified": 0,
            "classified": 0, "parse_errors": 0,
        }

    if "text" not in df.columns:
        raise ValueError("classify_vista_dataframe: input DataFrame must have a 'text' column")

    df = df.copy()

    # Ensure target columns exist with sensible defaults
    if "eje_narrativo" not in df.columns:
        df["eje_narrativo"] = pd.NA
    if "framing_dominante" not in df.columns:
        df["framing_dominante"] = ""
    if "eje_confianza" not in df.columns:
        df["eje_confianza"] = pd.NA
    if "eje_razon" not in df.columns:
        df["eje_razon"] = ""

    if skip_already_classified:
        # Treat NaN / "" / non-numeric as not yet classified
        existing = pd.to_numeric(df["eje_narrativo"], errors="coerce")
        mask = existing.isna()
    else:
        mask = pd.Series(True, index=df.index)

    indices_to_classify = df.index[mask].tolist()
    n_to_classify = len(indices_to_classify)
    n_skipped = len(df) - n_to_classify

    stats = {
        "total_rows": len(df),
        "to_classify": n_to_classify,
        "skipped_already_classified": int(n_skipped),
        "classified": 0,
        "parse_errors": 0,
    }

    if n_to_classify == 0:
        logger.info("classify_vista_dataframe: nothing to classify (all rows already done)")
        df["eje_narrativo"] = pd.to_numeric(df["eje_narrativo"], errors="coerce").astype("Int64")
        return df, stats

    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set and no client provided. "
                "Set the env var or inject a client."
            )
        client = Anthropic(api_key=api_key)

    has_author = "author" in df.columns
    has_platform = "platform" in df.columns
    has_sent_toward = "sentiment_toward" in df.columns

    def _value(idx, col, present):
        if not present:
            return None
        v = df.at[idx, col]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        return s or None

    total_batches = (n_to_classify + batch_size - 1) // batch_size

    logger.info(
        "classify_vista_dataframe: %d rows → %d to classify in %d batches of %d",
        len(df), n_to_classify, total_batches, batch_size,
    )

    for b_idx in range(total_batches):
        start = b_idx * batch_size
        batch_indices = indices_to_classify[start:start + batch_size]

        batch_inputs: List[VistaMentionInput] = []
        for i in batch_indices:
            text_val = df.at[i, "text"]
            text_str = "" if (text_val is None or (isinstance(text_val, float) and pd.isna(text_val))) else str(text_val)
            batch_inputs.append(VistaMentionInput(
                text=text_str,
                autor=_value(i, "author", has_author),
                plataforma=_value(i, "platform", has_platform),
                sentiment_toward=_value(i, "sentiment_toward", has_sent_toward),
            ))

        results = _call_haiku_batch(client, batch_inputs)

        for idx, result in zip(batch_indices, results):
            df.at[idx, "eje_narrativo"] = int(result.eje_narrativo)
            df.at[idx, "framing_dominante"] = result.framing_dominante
            df.at[idx, "eje_confianza"] = float(result.confianza)
            df.at[idx, "eje_razon"] = result.razon
            stats["classified"] += 1
            if result.razon.startswith("parse_error"):
                stats["parse_errors"] += 1

        logger.info(
            "Batch %d/%d done — total classified=%d, parse_errors=%d",
            b_idx + 1, total_batches, stats["classified"], stats["parse_errors"],
        )

        if on_progress is not None:
            try:
                on_progress(b_idx + 1, total_batches)
            except Exception as e:  # noqa: BLE001 — caller's bug shouldn't kill the run
                logger.warning("on_progress callback raised: %s", e)

    # Cast to nullable int / float for clean CSV output
    df["eje_narrativo"] = pd.to_numeric(df["eje_narrativo"], errors="coerce").astype("Int64")
    df["eje_confianza"] = pd.to_numeric(df["eje_confianza"], errors="coerce")

    return df, stats
