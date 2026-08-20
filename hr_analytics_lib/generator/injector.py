"""Defect injector for the HR Analytics synthetic data generator.

This module applies deliberate, catalogued defects to a clean dataset and
produces a Defect_Manifest recording every mutation. The injector preserves
the following invariants:

- Fixed injection order: defects are applied in DefectType enum declaration order.
- Exact count: round(rate × |eligible|), with a min-1 guarantee when eligible > 0.
- Skip-and-reselect: no duplicate (defect_type, table, row, column) corruption sites.
- Manifest completeness: one row per injected defect.
- Schema preservation: column set and dtypes are unchanged (nullable columns may gain NaN).
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd

from hr_analytics_lib.schema import TABLES, DefectType, TableSchema


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# A candidate corruption site: (table_name, row_index, column_name)
CandidateSite = tuple[str, int, str]

# For DATE_CONTRADICTION, we store paired columns: (table, row_idx, start_col, end_col)
DatePairSite = tuple[str, int, str, str]


# ---------------------------------------------------------------------------
# Eligible population computation (Task 6.1)
# ---------------------------------------------------------------------------

# Columns considered for VALUE_OUT_OF_RANGE
_BOUNDED_NUMERIC_COLUMNS: dict[str, list[str]] = {
    "employees": ["level"],
    "performance_reviews": ["rating"],
    "compensation": ["annual_salary"],
}

# Date-pair columns for DATE_CONTRADICTION: table → (start_col, end_col)
_DATE_PAIR_COLUMNS: dict[str, tuple[str, str]] = {
    "assignments": ("start_date", "end_date"),
    "performance_reviews": ("review_period_start", "review_period_end"),
}


def _compute_eligible_null_injection(
    tables: dict[str, pd.DataFrame],
) -> list[CandidateSite]:
    """NULL_INJECTION eligible: all rows × non-PK, non-nullable columns across all 7 tables."""
    candidates: list[CandidateSite] = []
    for table_name in sorted(tables.keys()):
        schema = TABLES[table_name]
        df = tables[table_name]
        # Get columns that are non-PK AND non-nullable (these are the ones that SHOULD have values)
        target_cols = [
            col.name
            for col in schema.columns
            if not col.is_pk and not col.nullable
        ]
        for col_name in sorted(target_cols):
            for row_idx in range(len(df)):
                candidates.append((table_name, row_idx, col_name))
    return candidates


def _compute_eligible_duplicate_key(
    tables: dict[str, pd.DataFrame],
) -> list[CandidateSite]:
    """DUPLICATE_KEY eligible: all rows × PK columns (need ≥ 2 rows in table)."""
    candidates: list[CandidateSite] = []
    for table_name in sorted(tables.keys()):
        schema = TABLES[table_name]
        df = tables[table_name]
        if len(df) < 2:
            continue
        pk_cols = schema.pk_columns
        for col_name in sorted(pk_cols):
            for row_idx in range(len(df)):
                candidates.append((table_name, row_idx, col_name))
    return candidates


def _compute_eligible_orphan_fk(
    tables: dict[str, pd.DataFrame],
) -> list[CandidateSite]:
    """ORPHAN_FK eligible: all rows × FK columns."""
    candidates: list[CandidateSite] = []
    for table_name in sorted(tables.keys()):
        schema = TABLES[table_name]
        df = tables[table_name]
        fk_cols = schema.fk_columns
        for col_name in sorted(fk_cols):
            for row_idx in range(len(df)):
                candidates.append((table_name, row_idx, col_name))
    return candidates


def _compute_eligible_date_contradiction(
    tables: dict[str, pd.DataFrame],
) -> list[DatePairSite]:
    """DATE_CONTRADICTION eligible: rows with (start, end) date pairs where start < end."""
    candidates: list[DatePairSite] = []
    for table_name in sorted(_DATE_PAIR_COLUMNS.keys()):
        if table_name not in tables:
            continue
        start_col, end_col = _DATE_PAIR_COLUMNS[table_name]
        df = tables[table_name]
        for row_idx in range(len(df)):
            start_val = df.iloc[row_idx][start_col]
            end_val = df.iloc[row_idx][end_col]
            # Only eligible if both non-null and start < end
            if pd.notna(start_val) and pd.notna(end_val) and start_val < end_val:
                candidates.append((table_name, row_idx, start_col, end_col))
    return candidates


def _compute_eligible_value_out_of_range(
    tables: dict[str, pd.DataFrame],
) -> list[CandidateSite]:
    """VALUE_OUT_OF_RANGE eligible: rows × numeric bounded columns."""
    candidates: list[CandidateSite] = []
    for table_name in sorted(_BOUNDED_NUMERIC_COLUMNS.keys()):
        if table_name not in tables:
            continue
        df = tables[table_name]
        for col_name in sorted(_BOUNDED_NUMERIC_COLUMNS[table_name]):
            for row_idx in range(len(df)):
                candidates.append((table_name, row_idx, col_name))
    return candidates


# ---------------------------------------------------------------------------
# Skip-and-reselect sampling (Task 6.2)
# ---------------------------------------------------------------------------


def _sample_with_skip_reselect(
    candidates: list[CandidateSite] | list[DatePairSite],
    count: int,
    rng: np.random.Generator,
    corrupted_sites: set[tuple[str, str, int, str]],
    defect_type: DefectType,
) -> list[CandidateSite] | list[DatePairSite]:
    """Sample candidates with skip-and-reselect for duplicates.

    Track a set of (defect_type, table, row_index, column) already corrupted.
    Skip any candidate that matches an existing corruption site for the SAME defect_type.

    Parameters
    ----------
    candidates : list
        Pool of eligible candidates to sample from.
    count : int
        Number of targets to select.
    rng : np.random.Generator
        Random generator for reproducible sampling.
    corrupted_sites : set
        Set of (defect_type_value, table, row_index, column) already corrupted.
    defect_type : DefectType
        The current defect type being injected.

    Returns
    -------
    list
        Selected candidates (up to `count`), with duplicates skipped.
    """
    if not candidates:
        return []

    # Shuffle candidates deterministically
    indices = rng.permutation(len(candidates))
    selected: list = []

    for idx in indices:
        if len(selected) >= count:
            break
        candidate = candidates[idx]
        # Determine the site key for collision check
        if defect_type == DefectType.DATE_CONTRADICTION:
            # DatePairSite: (table, row_idx, start_col, end_col)
            # Check both columns
            table_name, row_idx, start_col, end_col = candidate  # type: ignore[misc]
            site_key_start = (defect_type.value, table_name, row_idx, start_col)
            site_key_end = (defect_type.value, table_name, row_idx, end_col)
            if site_key_start in corrupted_sites or site_key_end in corrupted_sites:
                continue
        else:
            # CandidateSite: (table, row_idx, column)
            table_name, row_idx, col_name = candidate  # type: ignore[misc]
            site_key = (defect_type.value, table_name, row_idx, col_name)
            if site_key in corrupted_sites:
                continue
        selected.append(candidate)

    return selected


# ---------------------------------------------------------------------------
# Mutation implementations (Task 6.3)
# ---------------------------------------------------------------------------


def _apply_null_injection(
    tables: dict[str, pd.DataFrame],
    site: CandidateSite,
) -> tuple[str, str]:
    """Set value to None/NaN. Returns (original_value_str, mutated_value_str)."""
    table_name, row_idx, col_name = site
    df = tables[table_name]
    original = df.iloc[row_idx][col_name]
    df.iat[row_idx, df.columns.get_loc(col_name)] = None
    return str(original), str(None)


def _apply_duplicate_key(
    tables: dict[str, pd.DataFrame],
    site: CandidateSite,
    rng: np.random.Generator,
) -> tuple[str, str]:
    """Copy PK value from another random row. Returns (original, mutated)."""
    table_name, row_idx, col_name = site
    df = tables[table_name]
    original = df.iloc[row_idx][col_name]

    # Pick a different row to copy from
    other_indices = [i for i in range(len(df)) if i != row_idx]
    donor_idx = rng.choice(other_indices)
    donor_value = df.iloc[donor_idx][col_name]

    df.iat[row_idx, df.columns.get_loc(col_name)] = donor_value
    return str(original), str(donor_value)


def _apply_orphan_fk(
    tables: dict[str, pd.DataFrame],
    site: CandidateSite,
) -> tuple[str, str]:
    """Replace FK value with a UUID not present in target table. Returns (original, mutated)."""
    table_name, row_idx, col_name = site
    df = tables[table_name]
    original = df.iloc[row_idx][col_name]

    orphan_value = f"ORPHAN_{uuid4().hex[:8]}"
    df.iat[row_idx, df.columns.get_loc(col_name)] = orphan_value
    return str(original), str(orphan_value)


def _apply_date_contradiction(
    tables: dict[str, pd.DataFrame],
    site: DatePairSite,
) -> tuple[tuple[str, str], tuple[str, str]]:
    """Swap start/end dates. Returns ((orig_start, mutated_start), (orig_end, mutated_end))."""
    table_name, row_idx, start_col, end_col = site
    df = tables[table_name]

    start_val = df.iloc[row_idx][start_col]
    end_val = df.iloc[row_idx][end_col]

    # Swap: start gets end's value, end gets start's value
    df.iat[row_idx, df.columns.get_loc(start_col)] = end_val
    df.iat[row_idx, df.columns.get_loc(end_col)] = start_val

    return (str(start_val), str(end_val)), (str(end_val), str(start_val))


def _apply_value_out_of_range(
    tables: dict[str, pd.DataFrame],
    site: CandidateSite,
) -> tuple[str, str]:
    """Multiply numeric value by 100. Returns (original, mutated)."""
    table_name, row_idx, col_name = site
    df = tables[table_name]
    original = df.iloc[row_idx][col_name]

    mutated = original * 100
    df.iat[row_idx, df.columns.get_loc(col_name)] = mutated
    return str(original), str(mutated)


# ---------------------------------------------------------------------------
# Main injection function (Tasks 6.4, 6.5, 6.6)
# ---------------------------------------------------------------------------


def inject_defects(
    tables: dict[str, pd.DataFrame],
    corruption_config: dict[DefectType, float],
    rng: np.random.Generator,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, int]]:
    """Inject deliberate defects into a clean dataset.

    Parameters
    ----------
    tables : dict[str, pd.DataFrame]
        Clean dataset tables (will be copied, not modified in place).
    corruption_config : dict[DefectType, float]
        Mapping of defect types to corruption rates in (0.0, 1.0].
    rng : np.random.Generator
        Random number generator for defect injection.

    Returns
    -------
    tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, int]]
        (corrupted_tables, defect_manifest_df, defect_counts)

    Invariants:
    - Fixed injection order: DefectType enum declaration order.
    - Exact count: round(rate × |eligible|), min-1 guarantee.
    - Skip-and-reselect: no duplicate (defect_type, table, row, column) sites.
    - Manifest has one row per injected defect.
    - Schema column set and dtypes preserved (nullable columns may gain NaN).
    """
    # Deep copy tables to avoid mutating originals
    corrupted_tables: dict[str, pd.DataFrame] = {
        name: df.copy() for name, df in tables.items()
    }

    # Track corruption sites: set of (defect_type_value, table, row_index, column)
    corrupted_sites: set[tuple[str, str, int, str]] = set()

    # Manifest rows collected here
    manifest_rows: list[dict[str, str | int]] = []

    # Defect counts per type
    defect_counts: dict[str, int] = {dt.value: 0 for dt in DefectType}

    # Fixed injection order: DefectType enum declaration order (Task 6.4)
    for defect_type in DefectType:
        if defect_type not in corruption_config:
            continue

        rate = corruption_config[defect_type]

        # Compute eligible population (Task 6.1)
        if defect_type == DefectType.NULL_INJECTION:
            candidates = _compute_eligible_null_injection(corrupted_tables)
        elif defect_type == DefectType.DUPLICATE_KEY:
            candidates = _compute_eligible_duplicate_key(corrupted_tables)
        elif defect_type == DefectType.ORPHAN_FK:
            candidates = _compute_eligible_orphan_fk(corrupted_tables)
        elif defect_type == DefectType.DATE_CONTRADICTION:
            candidates = _compute_eligible_date_contradiction(corrupted_tables)
        elif defect_type == DefectType.VALUE_OUT_OF_RANGE:
            candidates = _compute_eligible_value_out_of_range(corrupted_tables)
        else:
            continue

        # Empty eligible → skip (Task 6.5)
        if len(candidates) == 0:
            continue

        # Exact count with min-1 guarantee (Task 6.5)
        count = round(rate * len(candidates))
        count = max(1, count)

        # Sample with skip-and-reselect (Task 6.2)
        selected = _sample_with_skip_reselect(
            candidates, count, rng, corrupted_sites, defect_type
        )

        # Apply mutations (Task 6.3)
        for site in selected:
            if defect_type == DefectType.NULL_INJECTION:
                original_str, mutated_str = _apply_null_injection(
                    corrupted_tables, site  # type: ignore[arg-type]
                )
                table_name, row_idx, col_name = site  # type: ignore[misc]
                corrupted_sites.add((defect_type.value, table_name, row_idx, col_name))
                manifest_rows.append({
                    "table": table_name,
                    "row_index": row_idx,
                    "column": col_name,
                    "defect_type": defect_type.value,
                    "original_value": original_str,
                    "mutated_value": mutated_str,
                })

            elif defect_type == DefectType.DUPLICATE_KEY:
                original_str, mutated_str = _apply_duplicate_key(
                    corrupted_tables, site, rng  # type: ignore[arg-type]
                )
                table_name, row_idx, col_name = site  # type: ignore[misc]
                corrupted_sites.add((defect_type.value, table_name, row_idx, col_name))
                manifest_rows.append({
                    "table": table_name,
                    "row_index": row_idx,
                    "column": col_name,
                    "defect_type": defect_type.value,
                    "original_value": original_str,
                    "mutated_value": mutated_str,
                })

            elif defect_type == DefectType.ORPHAN_FK:
                original_str, mutated_str = _apply_orphan_fk(
                    corrupted_tables, site  # type: ignore[arg-type]
                )
                table_name, row_idx, col_name = site  # type: ignore[misc]
                corrupted_sites.add((defect_type.value, table_name, row_idx, col_name))
                manifest_rows.append({
                    "table": table_name,
                    "row_index": row_idx,
                    "column": col_name,
                    "defect_type": defect_type.value,
                    "original_value": original_str,
                    "mutated_value": mutated_str,
                })

            elif defect_type == DefectType.DATE_CONTRADICTION:
                table_name, row_idx, start_col, end_col = site  # type: ignore[misc]
                (orig_start, mut_start), (orig_end, mut_end) = (
                    _apply_date_contradiction(corrupted_tables, site)  # type: ignore[arg-type]
                )
                # Record both columns as corruption sites
                corrupted_sites.add((defect_type.value, table_name, row_idx, start_col))
                corrupted_sites.add((defect_type.value, table_name, row_idx, end_col))
                # Two manifest rows: one for each column
                manifest_rows.append({
                    "table": table_name,
                    "row_index": row_idx,
                    "column": start_col,
                    "defect_type": defect_type.value,
                    "original_value": orig_start,
                    "mutated_value": mut_start,
                })
                manifest_rows.append({
                    "table": table_name,
                    "row_index": row_idx,
                    "column": end_col,
                    "defect_type": defect_type.value,
                    "original_value": orig_end,
                    "mutated_value": mut_end,
                })

            elif defect_type == DefectType.VALUE_OUT_OF_RANGE:
                original_str, mutated_str = _apply_value_out_of_range(
                    corrupted_tables, site  # type: ignore[arg-type]
                )
                table_name, row_idx, col_name = site  # type: ignore[misc]
                corrupted_sites.add((defect_type.value, table_name, row_idx, col_name))
                manifest_rows.append({
                    "table": table_name,
                    "row_index": row_idx,
                    "column": col_name,
                    "defect_type": defect_type.value,
                    "original_value": original_str,
                    "mutated_value": mutated_str,
                })

        # Update defect counts
        defect_counts[defect_type.value] = len(selected)

    # Build manifest DataFrame (Task 6.6)
    if manifest_rows:
        defect_manifest = pd.DataFrame(manifest_rows)
        # Sort by (table, row_index, column)
        defect_manifest = defect_manifest.sort_values(
            by=["table", "row_index", "column"], ignore_index=True
        )
    else:
        defect_manifest = pd.DataFrame(
            columns=["table", "row_index", "column", "defect_type", "original_value", "mutated_value"]
        )

    return corrupted_tables, defect_manifest, defect_counts
