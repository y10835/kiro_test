"""Serializer — CSV/JSON/Parquet I/O with Canonical_Form and round-trip fidelity.

Invariants:
- to_dataframes() returns dict of DataFrames without writing to filesystem.
- to_csv() writes each table as Canonical_Form CSV + metadata.json + defect_manifest.csv.
- from_csv() reads back with schema-aware dtype parsing for round-trip fidelity.
- OutputExistsError raised when target directory is non-empty and overwrite=False.
- Canonical_Form rules: column order per schema, sort by declared sort key,
  ISO-8601 dates, 2-decimal floats for monetary, empty string for NULL,
  RFC 4180 quoting, UTF-8, LF, header row, trailing newline.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from hr_analytics_lib.exceptions import OutputExistsError
from hr_analytics_lib.generator.pipeline import GeneratedDataset, RunMetadata
from hr_analytics_lib.schema import DEFECT_MANIFEST_SCHEMA, TABLES, TableSchema


# Columns that use 2-decimal monetary formatting
_MONETARY_COLUMNS: set[str] = {"annual_salary", "total_labor_cost"}


def _get_schema_for_table(table_name: str) -> TableSchema:
    """Look up the TableSchema for a given table name."""
    if table_name == "defect_manifest":
        return DEFECT_MANIFEST_SCHEMA
    return TABLES[table_name]


def _sort_dataframe(df: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Sort a DataFrame by the schema-declared sort keys."""
    sort_keys = schema.sort_keys
    if sort_keys:
        return df.sort_values(sort_keys, ignore_index=True)
    return df


def _reorder_columns(df: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Reorder DataFrame columns to match schema declaration order."""
    col_order = schema.column_names
    # Only include columns that actually exist in the DataFrame
    available = [c for c in col_order if c in df.columns]
    return df[available]


def _format_for_csv(df: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Apply Canonical_Form formatting to a DataFrame for CSV output.

    - Date columns → YYYY-MM-DD strings
    - Monetary float columns → 2 decimal place strings
    - NULL/NaN → empty string
    """
    formatted = df.copy()

    for col_def in schema.columns:
        col_name = col_def.name
        if col_name not in formatted.columns:
            continue

        if col_def.dtype == "date":
            # Convert date objects/Timestamps to ISO-8601 strings
            formatted[col_name] = formatted[col_name].apply(
                lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) and x is not None else ""
            )
        elif col_def.dtype == "float64" and col_name in _MONETARY_COLUMNS:
            # Format monetary values to 2 decimal places
            formatted[col_name] = formatted[col_name].apply(
                lambda x: f"{x:.2f}" if pd.notna(x) else ""
            )
        elif col_def.dtype == "int64":
            # Format integers (handle nullable ints)
            formatted[col_name] = formatted[col_name].apply(
                lambda x: str(int(x)) if pd.notna(x) else ""
            )
        else:
            # String columns: NaN → empty string
            formatted[col_name] = formatted[col_name].apply(
                lambda x: str(x) if pd.notna(x) and x is not None else ""
            )

    return formatted


def to_dataframes(dataset: GeneratedDataset) -> dict[str, pd.DataFrame]:
    """Return tables as a dict of DataFrames (in-memory access).

    Task 8.1.

    Returns a shallow copy of the tables dict plus the defect_manifest.
    Does not write to filesystem.

    Parameters
    ----------
    dataset : GeneratedDataset
        The complete generated dataset.

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping of table name → DataFrame for all 7 data tables
        plus the defect_manifest.
    """
    result = dict(dataset.tables)
    result["defect_manifest"] = dataset.defect_manifest
    return result


def to_csv(dataset: GeneratedDataset, directory: Path, overwrite: bool = False) -> None:
    """Write dataset to CSV files in Canonical_Form.

    Task 8.2 + Task 8.4 (OutputExistsError guard).

    Writes:
    - One CSV per table (7 tables + defect_manifest.csv)
    - metadata.json

    Canonical_Form rules:
    1. Column order matches schema.py declaration
    2. Rows sorted by declared sort key
    3. Dates as YYYY-MM-DD
    4. Floats: 2 decimal places for monetary (annual_salary, total_labor_cost)
    5. NULL as empty string
    6. RFC 4180 quoting
    7. UTF-8, no BOM
    8. LF line endings
    9. Header always present
    10. Trailing newline after last row

    Parameters
    ----------
    dataset : GeneratedDataset
        The complete generated dataset to serialize.
    directory : Path
        Target directory for CSV files.
    overwrite : bool
        If True, allows writing even when directory contains existing files.
        Default False.

    Raises
    ------
    OutputExistsError
        If directory contains CSV/JSON files and overwrite=False.
    """
    directory = Path(directory)

    # Task 8.4: OutputExistsError guard
    if directory.exists() and not overwrite:
        existing_files = [
            f for f in directory.iterdir()
            if f.suffix in (".csv", ".json")
        ]
        if existing_files:
            raise OutputExistsError(
                f"Directory not empty: {directory} contains "
                f"{len(existing_files)} existing file(s). "
                f"Use overwrite=True to force."
            )

    # Create directory if it doesn't exist
    directory.mkdir(parents=True, exist_ok=True)

    # Write each data table
    for table_name in TABLES:
        if table_name not in dataset.tables:
            continue
        df = dataset.tables[table_name]
        schema = _get_schema_for_table(table_name)

        # Apply canonical form: reorder columns, sort, format
        df = _reorder_columns(df, schema)
        df = _sort_dataframe(df, schema)
        df = _format_for_csv(df, schema)

        # Write CSV
        filepath = directory / f"{table_name}.csv"
        df.to_csv(
            filepath,
            index=False,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
            encoding="utf-8",
        )

    # Write defect_manifest.csv
    manifest_schema = DEFECT_MANIFEST_SCHEMA
    manifest_df = dataset.defect_manifest.copy()
    manifest_df = _reorder_columns(manifest_df, manifest_schema)
    manifest_df = _sort_dataframe(manifest_df, manifest_schema)
    manifest_df = _format_for_csv(manifest_df, manifest_schema)

    manifest_path = directory / "defect_manifest.csv"
    manifest_df.to_csv(
        manifest_path,
        index=False,
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
        encoding="utf-8",
    )

    # Write metadata.json
    metadata_dict = asdict(dataset.metadata)
    metadata_path = directory / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def from_csv(directory: Path) -> GeneratedDataset:
    """Read a previously written dataset from CSV files.

    Task 8.3.

    Uses schema-aware dtype parsing for round-trip fidelity:
    - date columns parsed as datetime64 then converted to date objects
    - int columns as int64
    - float columns as float64
    - str columns as object
    - nullable columns: empty string → None/NaN

    Parameters
    ----------
    directory : Path
        Directory containing CSV files and metadata.json previously
        written by to_csv().

    Returns
    -------
    GeneratedDataset
        Reconstructed dataset with proper dtypes.
    """
    directory = Path(directory)

    # Read metadata.json
    metadata_path = directory / "metadata.json"
    metadata_dict = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = RunMetadata(
        library_version=metadata_dict["library_version"],
        resolved_seed=metadata_dict["resolved_seed"],
        config_hash=metadata_dict["config_hash"],
        generation_timestamp=metadata_dict["generation_timestamp"],
        table_row_counts=metadata_dict["table_row_counts"],
        defect_counts=metadata_dict["defect_counts"],
    )

    # Read each data table
    tables: dict[str, pd.DataFrame] = {}
    for table_name, schema in TABLES.items():
        filepath = directory / f"{table_name}.csv"
        if not filepath.exists():
            continue
        df = _read_csv_with_schema(filepath, schema)
        tables[table_name] = df

    # Read defect_manifest
    manifest_path = directory / "defect_manifest.csv"
    if manifest_path.exists():
        defect_manifest = _read_csv_with_schema(manifest_path, DEFECT_MANIFEST_SCHEMA)
    else:
        defect_manifest = pd.DataFrame(
            columns=DEFECT_MANIFEST_SCHEMA.column_names
        )

    return GeneratedDataset(
        tables=tables,
        defect_manifest=defect_manifest,
        metadata=metadata,
    )


def _read_csv_with_schema(filepath: Path, schema: TableSchema) -> pd.DataFrame:
    """Read a CSV file with schema-aware dtype parsing.

    Parameters
    ----------
    filepath : Path
        Path to the CSV file.
    schema : TableSchema
        The schema definition for this table.

    Returns
    -------
    pd.DataFrame
        DataFrame with correct dtypes as specified by schema.
    """
    # Determine which columns are date columns for special parsing
    date_columns = [col.name for col in schema.columns if col.dtype == "date"]
    str_columns = [col.name for col in schema.columns if col.dtype == "str"]
    int_columns = [col.name for col in schema.columns if col.dtype == "int64"]
    float_columns = [col.name for col in schema.columns if col.dtype == "float64"]

    # Read all columns as strings first to handle empty strings (NULLs) properly
    df = pd.read_csv(
        filepath,
        encoding="utf-8",
        dtype=str,
        keep_default_na=False,
    )

    # Parse date columns
    for col_name in date_columns:
        if col_name not in df.columns:
            continue
        col_def = next(c for c in schema.columns if c.name == col_name)
        if col_def.nullable:
            # Nullable dates: empty string → None
            df[col_name] = df[col_name].apply(
                lambda x: pd.Timestamp(x).date() if x != "" else None
            )
        else:
            # Non-nullable dates: parse directly
            df[col_name] = pd.to_datetime(df[col_name]).dt.date

    # Parse int columns
    for col_name in int_columns:
        if col_name not in df.columns:
            continue
        col_def = next(c for c in schema.columns if c.name == col_name)
        if col_def.nullable:
            # Nullable ints: empty string → NaN, then use Int64 (nullable int)
            df[col_name] = df[col_name].apply(
                lambda x: int(x) if x != "" else pd.NA
            )
            df[col_name] = df[col_name].astype("Int64")
        else:
            # Non-nullable ints: parse directly as int64
            df[col_name] = df[col_name].astype("int64")

    # Parse float columns
    for col_name in float_columns:
        if col_name not in df.columns:
            continue
        col_def = next(c for c in schema.columns if c.name == col_name)
        if col_def.nullable:
            df[col_name] = df[col_name].apply(
                lambda x: float(x) if x != "" else float("nan")
            )
        else:
            df[col_name] = df[col_name].astype("float64")

    # Parse str columns
    for col_name in str_columns:
        if col_name not in df.columns:
            continue
        col_def = next(c for c in schema.columns if c.name == col_name)
        if col_def.nullable:
            # Nullable strings: empty string → None
            df[col_name] = df[col_name].apply(
                lambda x: x if x != "" else None
            )
        # Non-nullable strings remain as-is (already str/object)

    return df


def to_parquet(dataset: GeneratedDataset, directory: Path, overwrite: bool = False) -> None:
    """Write dataset to Parquet files (optional, requires pyarrow).

    Task 8.5.

    Writes one .parquet file per table plus metadata.json.

    Parameters
    ----------
    dataset : GeneratedDataset
        The complete generated dataset.
    directory : Path
        Target directory for Parquet files.
    overwrite : bool
        If True, allows writing even when directory contains existing files.
        Default False.

    Raises
    ------
    NotImplementedError
        If pyarrow is not installed.
    OutputExistsError
        If directory contains files and overwrite=False.
    """
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        raise NotImplementedError(
            "Parquet output requires pyarrow. Install with: pip install hr-analytics-lib[parquet]"
        )

    directory = Path(directory)

    # OutputExistsError guard
    if directory.exists() and not overwrite:
        existing_files = [
            f for f in directory.iterdir()
            if f.suffix in (".parquet", ".json")
        ]
        if existing_files:
            raise OutputExistsError(
                f"Directory not empty: {directory} contains "
                f"{len(existing_files)} existing file(s). "
                f"Use overwrite=True to force."
            )

    directory.mkdir(parents=True, exist_ok=True)

    # Write each data table as Parquet
    for table_name in TABLES:
        if table_name not in dataset.tables:
            continue
        df = dataset.tables[table_name]
        schema = _get_schema_for_table(table_name)

        # Apply canonical ordering
        df = _reorder_columns(df, schema)
        df = _sort_dataframe(df, schema)

        filepath = directory / f"{table_name}.parquet"
        df.to_parquet(filepath, index=False, engine="pyarrow")

    # Write defect_manifest
    manifest_schema = DEFECT_MANIFEST_SCHEMA
    manifest_df = dataset.defect_manifest.copy()
    manifest_df = _reorder_columns(manifest_df, manifest_schema)
    manifest_df = _sort_dataframe(manifest_df, manifest_schema)

    manifest_path = directory / "defect_manifest.parquet"
    manifest_df.to_parquet(manifest_path, index=False, engine="pyarrow")

    # Write metadata.json
    metadata_dict = asdict(dataset.metadata)
    metadata_path = directory / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
