"""Generator module — synthesises multi-table HR datasets from a GenerationConfig.

Public API:
- generate() — Generate a complete synthetic HR dataset
- GenerationConfig — Validated, immutable configuration
- GeneratedDataset — Complete result of a generation run
- RunMetadata — Provenance metadata
- validate() — Check Data_Tables against schema declarations
- to_dataframes() — Return tables as dict of DataFrames
- to_csv() — Write dataset to CSV in Canonical_Form
- from_csv() — Read dataset from CSV
"""

from hr_analytics_lib.generator.config import GenerationConfig
from hr_analytics_lib.generator.pipeline import GeneratedDataset, RunMetadata, generate
from hr_analytics_lib.generator.serializer import from_csv, to_csv, to_dataframes, to_parquet
from hr_analytics_lib.generator.validator import Violation, validate, manifest_to_violations

__all__ = [
    "GenerationConfig",
    "GeneratedDataset",
    "RunMetadata",
    "generate",
    "validate",
    "Violation",
    "manifest_to_violations",
    "to_dataframes",
    "to_csv",
    "from_csv",
    "to_parquet",
]
