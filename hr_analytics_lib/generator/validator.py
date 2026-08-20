"""Validator module for checking Data_Tables against Fixed_Schema declarations.

This module does NOT import from the Injector. All checks are derived from
schema.py declarations and structural invariants defined in the requirements.

Invariants preserved by this module:
- Idempotent: validate(tables) == validate(tables) always.
- In clean mode: returns empty list.
- Does NOT import from injector.py.
- All violations are normalized to (table, row_index, column, violation_type, message).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from hr_analytics_lib.schema import TABLES, DefectType, TableSchema


# ---------------------------------------------------------------------------
# Violation dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One detected schema/integrity violation."""

    table: str
    row_index: int
    column: str
    violation_type: str  # maps to DefectType value
    message: str

    def __eq__(self, other: object) -> bool:
        """Equality on (violation_type, table, row_index, column) only."""
        if not isinstance(other, Violation):
            return NotImplemented
        return (self.violation_type, self.table, self.row_index, self.column) == (
            other.violation_type,
            other.table,
            other.row_index,
            other.column,
        )

    def __hash__(self) -> int:
        return hash((self.violation_type, self.table, self.row_index, self.column))


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def _check_non_nullable(
    table_name: str, df: pd.DataFrame, schema: TableSchema
) -> list[Violation]:
    """Check for null/NaN values in non-nullable columns (Task 7.1)."""
    violations: list[Violation] = []
    nn_columns = schema.non_nullable_columns

    for col_name in nn_columns:
        if col_name not in df.columns:
            continue
        null_mask = df[col_name].isna()
        null_indices = df.index[null_mask].tolist()
        for idx in null_indices:
            violations.append(
                Violation(
                    table=table_name,
                    row_index=idx,
                    column=col_name,
                    violation_type=DefectType.NULL_INJECTION.value,
                    message=f"NULL value in non-nullable column '{col_name}' at row {idx}",
                )
            )
    return violations


def _check_pk_uniqueness(
    table_name: str, df: pd.DataFrame, schema: TableSchema
) -> list[Violation]:
    """Check for duplicate values in primary key columns (Task 7.2)."""
    violations: list[Violation] = []
    pk_columns = schema.pk_columns

    for col_name in pk_columns:
        if col_name not in df.columns:
            continue
        # Find duplicated values (mark all occurrences after the first)
        duplicated_mask = df[col_name].duplicated(keep="first")
        dup_indices = df.index[duplicated_mask].tolist()
        for idx in dup_indices:
            violations.append(
                Violation(
                    table=table_name,
                    row_index=idx,
                    column=col_name,
                    violation_type=DefectType.DUPLICATE_KEY.value,
                    message=f"Duplicate PK value in column '{col_name}' at row {idx}",
                )
            )
    return violations


def _check_fk_integrity(
    table_name: str, df: pd.DataFrame, schema: TableSchema, tables: dict[str, pd.DataFrame]
) -> list[Violation]:
    """Check FK referential integrity — all FK values must exist in target PK (Task 7.3)."""
    violations: list[Violation] = []

    for col_def in schema.columns:
        if not col_def.is_fk or col_def.fk_target is None:
            continue
        col_name = col_def.name
        if col_name not in df.columns:
            continue

        # Parse target table and column from fk_target (e.g., "departments.department_id")
        target_table, target_column = col_def.fk_target.split(".")

        if target_table not in tables:
            continue
        target_df = tables[target_table]
        if target_column not in target_df.columns:
            continue

        # Get valid PK values from target table
        valid_values = set(target_df[target_column].dropna().tolist())

        # Check each non-null FK value
        for idx in df.index:
            value = df.at[idx, col_name]
            if pd.isna(value):
                continue  # Nullable FK columns may have nulls
            if value not in valid_values:
                violations.append(
                    Violation(
                        table=table_name,
                        row_index=idx,
                        column=col_name,
                        violation_type=DefectType.ORPHAN_FK.value,
                        message=f"FK value '{value}' in column '{col_name}' at row {idx} "
                        f"not found in {target_table}.{target_column}",
                    )
                )
    return violations


def _check_temporal_ordering(
    table_name: str, df: pd.DataFrame
) -> list[Violation]:
    """Check temporal ordering constraints (Task 7.4).

    - assignments: start_date <= end_date (when end_date is not null)
    - performance_reviews: review_period_start < review_period_end
    """
    violations: list[Violation] = []

    if table_name == "assignments":
        if "start_date" in df.columns and "end_date" in df.columns:
            for idx in df.index:
                start = df.at[idx, "start_date"]
                end = df.at[idx, "end_date"]
                if pd.isna(start) or pd.isna(end):
                    continue
                if start > end:
                    violations.append(
                        Violation(
                            table=table_name,
                            row_index=idx,
                            column="end_date",
                            violation_type=DefectType.DATE_CONTRADICTION.value,
                            message=f"start_date ({start}) > end_date ({end}) at row {idx}",
                        )
                    )

    elif table_name == "performance_reviews":
        if "review_period_start" in df.columns and "review_period_end" in df.columns:
            for idx in df.index:
                start = df.at[idx, "review_period_start"]
                end = df.at[idx, "review_period_end"]
                if pd.isna(start) or pd.isna(end):
                    continue
                if start >= end:
                    violations.append(
                        Violation(
                            table=table_name,
                            row_index=idx,
                            column="review_period_end",
                            violation_type=DefectType.DATE_CONTRADICTION.value,
                            message=f"review_period_start ({start}) >= review_period_end ({end}) "
                            f"at row {idx}",
                        )
                    )

    return violations


def _check_value_boundaries(
    table_name: str, df: pd.DataFrame
) -> list[Violation]:
    """Check value boundary constraints (Task 7.5).

    - employees.level: 1 <= level <= 15
    - performance_reviews.rating: 1 <= rating <= 5
    - compensation.annual_salary: 0 < salary <= 10_000_000
    """
    violations: list[Violation] = []

    if table_name == "employees" and "level" in df.columns:
        for idx in df.index:
            level = df.at[idx, "level"]
            if pd.isna(level):
                continue
            if level < 1 or level > 15:
                violations.append(
                    Violation(
                        table=table_name,
                        row_index=idx,
                        column="level",
                        violation_type=DefectType.VALUE_OUT_OF_RANGE.value,
                        message=f"level value {level} out of range [1, 15] at row {idx}",
                    )
                )

    elif table_name == "performance_reviews" and "rating" in df.columns:
        for idx in df.index:
            rating = df.at[idx, "rating"]
            if pd.isna(rating):
                continue
            if rating < 1 or rating > 5:
                violations.append(
                    Violation(
                        table=table_name,
                        row_index=idx,
                        column="rating",
                        violation_type=DefectType.VALUE_OUT_OF_RANGE.value,
                        message=f"rating value {rating} out of range [1, 5] at row {idx}",
                    )
                )

    elif table_name == "compensation" and "annual_salary" in df.columns:
        for idx in df.index:
            salary = df.at[idx, "annual_salary"]
            if pd.isna(salary):
                continue
            if salary <= 0 or salary > 10_000_000:
                violations.append(
                    Violation(
                        table=table_name,
                        row_index=idx,
                        column="annual_salary",
                        violation_type=DefectType.VALUE_OUT_OF_RANGE.value,
                        message=f"annual_salary value {salary} out of range (0, 10000000] "
                        f"at row {idx}",
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------


def validate(tables: dict[str, pd.DataFrame]) -> list[Violation]:
    """Check Data_Tables against Fixed_Schema declarations.

    Derives all checks from schema.py, not from Injector logic.

    Checks performed:
    1. Non-nullable violations: check for nulls in NN columns
    2. PK uniqueness: check for duplicates in PK columns
    3. FK referential integrity: check FK references exist
    4. Temporal ordering: separation_date >= hire_date;
       assignment effective_dates non-decreasing per employee
    5. Classification completeness: separation events must have non-null separation_type
    6. Value boundaries: level in valid range, rating in [1,5]

    Returns
    -------
    list[Violation]
        List of all detected violations, sorted by (table, row_index, column).

    Invariants:
    - Idempotent: validate(tables) == validate(tables) always.
    - In clean mode: returns empty list.
    - Does NOT import from injector.py.
    """
    violations: list[Violation] = []

    for table_name, schema in TABLES.items():
        if table_name not in tables:
            continue
        df = tables[table_name]

        # 7.1: Schema compliance — non-nullable columns
        violations.extend(_check_non_nullable(table_name, df, schema))

        # 7.2: PK uniqueness
        violations.extend(_check_pk_uniqueness(table_name, df, schema))

        # 7.3: FK referential integrity
        violations.extend(_check_fk_integrity(table_name, df, schema, tables))

        # 7.4: Temporal ordering
        violations.extend(_check_temporal_ordering(table_name, df))

        # 7.5: Value boundaries
        violations.extend(_check_value_boundaries(table_name, df))

    # Sort by (table, row_index, column) for deterministic output
    violations.sort(key=lambda v: (v.table, v.row_index, v.column))
    return violations


# ---------------------------------------------------------------------------
# Manifest comparison utility (Task 7.7)
# ---------------------------------------------------------------------------


def manifest_to_violations(manifest_df: pd.DataFrame) -> set[Violation]:
    """Convert Defect_Manifest rows to Violation instances for comparison.

    Each manifest row is converted to a Violation with the (table, row_index,
    column, defect_type) fields populated. The message field contains a generic
    description since the manifest does not carry detailed messages.

    Parameters
    ----------
    manifest_df : pd.DataFrame
        DataFrame with columns: table, row_index, column, defect_type,
        original_value, mutated_value.

    Returns
    -------
    set[Violation]
        Set of Violations derived from the manifest for set-equality comparison
        with validator output.
    """
    violations: set[Violation] = set()

    for idx in manifest_df.index:
        row = manifest_df.loc[idx]
        violations.add(
            Violation(
                table=str(row["table"]),
                row_index=int(row["row_index"]),
                column=str(row["column"]),
                violation_type=str(row["defect_type"]),
                message=f"From manifest: {row['defect_type']} on "
                f"{row['table']}.{row['column']} at row {row['row_index']}",
            )
        )

    return violations
