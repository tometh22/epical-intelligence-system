"""Data parsing utilities for YouScan CSV/Excel exports."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from agents.shared.logger import get_logger

logger = get_logger("report-builder")


def parse_export(filepath: Union[str, Path]) -> pd.DataFrame:
    """Read a CSV or Excel file and return a pandas DataFrame.

    Auto-detects format by file extension. Handles common encoding issues.

    Args:
        filepath: Path to the input file (.csv, .xlsx, .xls).

    Returns:
        Raw DataFrame with original columns.

    Raises:
        ValueError: If the file format is not supported.
        FileNotFoundError: If the file does not exist.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")

    ext = filepath.suffix.lower()

    if ext == ".csv":
        # Try utf-8 first, then latin-1 as fallback
        for encoding in ("utf-8", "latin-1"):
            try:
                df = pd.read_csv(filepath, encoding=encoding)
                logger.info("Parsed CSV with encoding %s: %d rows, %d columns",
                            encoding, len(df), len(df.columns))
                return df
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not decode CSV file {filepath} with utf-8 or latin-1")

    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(filepath, engine="openpyxl" if ext == ".xlsx" else None)
        logger.info("Parsed Excel file: %d rows, %d columns", len(df), len(df.columns))
        return df

    else:
        raise ValueError(f"Unsupported file format: {ext}. Use .csv, .xlsx, or .xls")


def clean_data(
    df: pd.DataFrame,
    column_map: Dict[str, Optional[str]],
) -> Tuple[pd.DataFrame, List[str]]:
    """Apply column mapping, clean, and standardize the DataFrame.

    Args:
        df: Raw DataFrame from parse_export.
        column_map: Resolved column mapping (logical_field -> actual column name or None).

    Returns:
        Tuple of (cleaned DataFrame with standardized column names, list of data quality issues).
    """
    issues: List[str] = []
    renamed: Dict[str, str] = {}

    for logical_field, actual_col in column_map.items():
        if actual_col is not None and actual_col in df.columns:
            renamed[actual_col] = logical_field
        else:
            issues.append(f"Column not found for '{logical_field}'")

    df_clean = df.rename(columns=renamed)

    # Keep only the mapped columns that exist
    available_cols = [col for col in column_map.keys() if col in df_clean.columns]
    df_clean = df_clean[available_cols].copy()

    # Drop rows with no text content
    if "text" in df_clean.columns:
        before_count = len(df_clean)
        df_clean = df_clean.dropna(subset=["text"])
        df_clean = df_clean[df_clean["text"].astype(str).str.strip() != ""]
        dropped = before_count - len(df_clean)
        if dropped > 0:
            issues.append(f"Dropped {dropped} rows with empty text")
    else:
        issues.append("No 'text' column found — cannot filter empty rows")

    # Normalize dates
    if "date" in df_clean.columns:
        try:
            df_clean["date"] = pd.to_datetime(df_clean["date"], errors="coerce")
            null_dates = df_clean["date"].isna().sum()
            if null_dates > 0:
                issues.append(f"{null_dates} rows have unparseable dates")
        except Exception as e:
            issues.append(f"Date parsing error: {e}")

    # Normalize sentiment values to lowercase
    if "sentiment" in df_clean.columns:
        df_clean["sentiment"] = df_clean["sentiment"].astype(str).str.strip().str.lower()

    # Convert numeric columns
    for col in ("reach", "engagement"):
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce")

    logger.info("Cleaned data: %d rows, %d columns. Issues: %d",
                len(df_clean), len(df_clean.columns), len(issues))
    return df_clean, issues
