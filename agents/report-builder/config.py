"""Configuration for the Report Builder agent."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEFAULT_COLUMN_MAPPING: Dict[str, List[str]] = {
    "date": ["date", "fecha", "Date", "Fecha", "Published", "published_date"],
    "text": ["text", "texto", "Text", "Texto", "Content", "content", "mention_text"],
    "sentiment": ["sentiment", "sentimiento", "Sentiment", "Sentimiento"],
    "source": ["source", "fuente", "Source", "Fuente", "Platform", "platform"],
    "author": ["author", "autor", "Author", "Autor"],
    "topic": ["topic", "tema", "Topic", "Tema", "Category", "category"],
    "url": ["url", "URL", "link", "Link"],
    "reach": ["reach", "alcance", "Reach", "Alcance", "impressions", "Impressions"],
    "engagement": ["engagement", "Engagement", "interactions", "Interactions"],
}


def load_column_mapping(client_name: str) -> Dict[str, Any]:
    """Load column mapping for a specific client, falling back to defaults.

    Checks /config/column_mappings/{client_name}.json first. If not found or
    invalid, returns the DEFAULT_COLUMN_MAPPING.

    Args:
        client_name: The client identifier.

    Returns:
        Column mapping dictionary.
    """
    config_path = BASE_DIR / "config" / "column_mappings" / f"{client_name}.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                custom_mapping = json.load(f)
            # Custom mapping is a simple field -> column_name dict.
            # Wrap single strings into lists for uniform handling.
            normalised: Dict[str, List[str]] = {}
            for key, value in custom_mapping.items():
                if isinstance(value, str):
                    normalised[key] = [value]
                elif isinstance(value, list):
                    normalised[key] = value
                else:
                    normalised[key] = [str(value)]
            return normalised
        except (json.JSONDecodeError, OSError):
            pass

    return DEFAULT_COLUMN_MAPPING


def resolve_columns(
    df: pd.DataFrame,
    mapping: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    """Resolve which actual DataFrame column names correspond to each logical field.

    Args:
        df: The DataFrame whose columns to inspect.
        mapping: Column mapping (logical_field -> list of possible column names).

    Returns:
        Dict mapping each logical field to the actual column name found, or None.
    """
    resolved: Dict[str, Optional[str]] = {}
    df_columns = set(df.columns)

    for logical_field, candidates in mapping.items():
        found: Optional[str] = None
        if isinstance(candidates, str):
            candidates = [candidates]
        for candidate in candidates:
            if candidate in df_columns:
                found = candidate
                break
        resolved[logical_field] = found

    return resolved
