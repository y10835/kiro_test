"""Schema definitions for the HR Analytics synthetic data generator.

This module is the single source of truth for all table schemas, column definitions,
and structural invariants. It preserves the following guarantees:

- Every table has a fixed set of typed columns with explicit nullability flags.
- Primary key, foreign key, and sort-key metadata is declared per-column.
- The DefectType enum defines the closed taxonomy of injectable defects.
- SCHEMA_VERSION and DEFECT_TAXONOMY_VERSION track breaking changes to schema
  or defect taxonomy so downstream consumers can detect incompatibilities.
- This module is declarations only — no IO, no validation logic, no imports from
  generator/ or metrics/.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# ---------------------------------------------------------------------------
# Versioning constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0.0"
DEFECT_TAXONOMY_VERSION: str = "1.0.0"


# ---------------------------------------------------------------------------
# Defect taxonomy
# ---------------------------------------------------------------------------


class DefectType(StrEnum):
    """Closed taxonomy of injectable data quality defects."""

    NULL_INJECTION = "NULL_INJECTION"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    ORPHAN_FK = "ORPHAN_FK"
    DATE_CONTRADICTION = "DATE_CONTRADICTION"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# Column & Table schema dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnDef:
    """Definition of a single column within a table schema."""

    name: str
    dtype: str  # "str", "date", "int64", "float64"
    nullable: bool
    is_pk: bool = False
    is_fk: bool = False
    fk_target: str | None = None  # e.g., "departments.department_id"
    sort_position: int | None = None  # None = not part of sort key


@dataclass(frozen=True)
class TableSchema:
    """Immutable schema descriptor for one table in the HR dataset."""

    name: str
    columns: tuple[ColumnDef, ...]

    @property
    def column_names(self) -> list[str]:
        """Return ordered list of column names."""
        return [col.name for col in self.columns]

    @property
    def sort_keys(self) -> list[str]:
        """Return column names participating in the sort key, ordered by sort_position."""
        return [
            col.name
            for col in sorted(
                (c for c in self.columns if c.sort_position is not None),
                key=lambda c: c.sort_position,  # type: ignore[arg-type]
            )
        ]

    @property
    def pk_columns(self) -> list[str]:
        """Return column names marked as primary key."""
        return [col.name for col in self.columns if col.is_pk]

    @property
    def fk_columns(self) -> list[str]:
        """Return column names marked as foreign key."""
        return [col.name for col in self.columns if col.is_fk]

    @property
    def non_nullable_columns(self) -> list[str]:
        """Return column names that must not contain NULL values."""
        return [col.name for col in self.columns if not col.nullable]


# ---------------------------------------------------------------------------
# Table definitions (7 core tables)
# ---------------------------------------------------------------------------

TABLES: dict[str, TableSchema] = {
    "departments": TableSchema(
        name="departments",
        columns=(
            ColumnDef(name="department_id", dtype="str", nullable=False, is_pk=True, sort_position=0),
            ColumnDef(name="department_name", dtype="str", nullable=False),
            ColumnDef(name="created_date", dtype="date", nullable=False),
        ),
    ),
    "employees": TableSchema(
        name="employees",
        columns=(
            ColumnDef(name="employee_id", dtype="str", nullable=False, is_pk=True, sort_position=0),
            ColumnDef(name="hire_date", dtype="date", nullable=False, sort_position=1),
            ColumnDef(name="separation_date", dtype="date", nullable=True),
            ColumnDef(name="separation_type", dtype="str", nullable=True),
            ColumnDef(name="level", dtype="int64", nullable=False),
            ColumnDef(
                name="department_id",
                dtype="str",
                nullable=False,
                is_fk=True,
                fk_target="departments.department_id",
            ),
        ),
    ),
    "employment_events": TableSchema(
        name="employment_events",
        columns=(
            ColumnDef(name="event_id", dtype="str", nullable=False, is_pk=True),
            ColumnDef(
                name="employee_id",
                dtype="str",
                nullable=False,
                is_fk=True,
                fk_target="employees.employee_id",
                sort_position=0,
            ),
            ColumnDef(name="event_date", dtype="date", nullable=False, sort_position=1),
            ColumnDef(name="event_type", dtype="str", nullable=False),
            ColumnDef(name="from_department_id", dtype="str", nullable=True),
            ColumnDef(name="to_department_id", dtype="str", nullable=True),
            ColumnDef(name="from_level", dtype="int64", nullable=True),
            ColumnDef(name="to_level", dtype="int64", nullable=True),
        ),
    ),
    "assignments": TableSchema(
        name="assignments",
        columns=(
            ColumnDef(name="assignment_id", dtype="str", nullable=False, is_pk=True),
            ColumnDef(
                name="employee_id",
                dtype="str",
                nullable=False,
                is_fk=True,
                fk_target="employees.employee_id",
                sort_position=0,
            ),
            ColumnDef(
                name="department_id",
                dtype="str",
                nullable=False,
                is_fk=True,
                fk_target="departments.department_id",
            ),
            ColumnDef(name="level", dtype="int64", nullable=False),
            ColumnDef(name="start_date", dtype="date", nullable=False, sort_position=1),
            ColumnDef(name="end_date", dtype="date", nullable=True),
        ),
    ),
    "compensation": TableSchema(
        name="compensation",
        columns=(
            ColumnDef(name="compensation_id", dtype="str", nullable=False, is_pk=True),
            ColumnDef(
                name="employee_id",
                dtype="str",
                nullable=False,
                is_fk=True,
                fk_target="employees.employee_id",
                sort_position=0,
            ),
            ColumnDef(name="effective_date", dtype="date", nullable=False, sort_position=1),
            ColumnDef(name="annual_salary", dtype="float64", nullable=False),
            ColumnDef(name="currency", dtype="str", nullable=False),
        ),
    ),
    "performance_reviews": TableSchema(
        name="performance_reviews",
        columns=(
            ColumnDef(name="review_id", dtype="str", nullable=False, is_pk=True),
            ColumnDef(
                name="employee_id",
                dtype="str",
                nullable=False,
                is_fk=True,
                fk_target="employees.employee_id",
                sort_position=0,
            ),
            ColumnDef(name="review_date", dtype="date", nullable=False, sort_position=1),
            ColumnDef(name="review_period_start", dtype="date", nullable=False),
            ColumnDef(name="review_period_end", dtype="date", nullable=False),
            ColumnDef(name="rating", dtype="int64", nullable=False),
            ColumnDef(
                name="reviewer_employee_id",
                dtype="str",
                nullable=True,
                is_fk=True,
                fk_target="employees.employee_id",
            ),
        ),
    ),
    "org_periods": TableSchema(
        name="org_periods",
        columns=(
            ColumnDef(name="period", dtype="str", nullable=False, sort_position=0),
            ColumnDef(name="grain_type", dtype="str", nullable=False, sort_position=1),
            ColumnDef(name="grain_key", dtype="str", nullable=False, sort_position=2),
            ColumnDef(name="opening", dtype="int64", nullable=False),
            ColumnDef(name="hires", dtype="int64", nullable=False),
            ColumnDef(name="separations", dtype="int64", nullable=False),
            ColumnDef(name="transfers_in", dtype="int64", nullable=False),
            ColumnDef(name="transfers_out", dtype="int64", nullable=False),
            ColumnDef(name="closing", dtype="int64", nullable=False),
            ColumnDef(name="total_labor_cost", dtype="float64", nullable=False),
        ),
    ),
}



# ---------------------------------------------------------------------------
# Defect manifest schema (not part of core TABLES — tracks injected defects)
# ---------------------------------------------------------------------------

DEFECT_MANIFEST_SCHEMA: TableSchema = TableSchema(
    name="defect_manifest",
    columns=(
        ColumnDef(name="table", dtype="str", nullable=False, sort_position=0),
        ColumnDef(name="row_index", dtype="int64", nullable=False, sort_position=1),
        ColumnDef(name="column", dtype="str", nullable=False, sort_position=2),
        ColumnDef(name="defect_type", dtype="str", nullable=False),
        ColumnDef(name="original_value", dtype="str", nullable=False),
        ColumnDef(name="mutated_value", dtype="str", nullable=False),
    ),
)
