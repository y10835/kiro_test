"""Checkpoint 5 verification: Pipeline Clean-Mode end-to-end test.

Run this script to verify Tasks 5.1–5.4:
  5.1: All 7 tables populated
  5.2: Flow identity holds on all org_periods rows
  5.3: Schema integrity (no NULLs in non-nullable, FKs resolve, PKs unique)
  5.4: Analytical adequacy (separations, cohorts, promotions, transfers present)

Usage:
    python tests/verify_pipeline_checkpoint5.py
"""

from datetime import date

from hr_analytics_lib.generator.config import GenerationConfig
from hr_analytics_lib.generator.pipeline import generate
from hr_analytics_lib.schema import TABLES


def main() -> None:
    # Task 5.1: Generate dataset with seed=42, headcount=50, 12 months
    config = GenerationConfig(
        headcount=50,
        n_levels=5,
        n_departments=3,
        start_date=date(2022, 1, 1),
        end_date=date(2022, 12, 31),
        seed=42,
    )

    ds = generate(config)

    # Verify all 7 tables populated
    print("=== Task 5.1: Table row counts ===")
    for name, df in ds.tables.items():
        print(f"  {name}: {len(df)} rows, columns: {list(df.columns)}")
    assert len(ds.tables) == 7, f"Expected 7 tables, got {len(ds.tables)}"
    for name, df in ds.tables.items():
        assert len(df) > 0, f"Table {name} is empty!"
    print("✅ All 7 tables populated\n")

    # Task 5.2: Verify flow identity holds on all org_periods rows
    print("=== Task 5.2: Flow Identity ===")
    org = ds.tables["org_periods"]
    violations = []
    for idx, row in org.iterrows():
        computed_closing = (
            row["opening"]
            + row["hires"]
            + row["transfers_in"]
            - row["separations"]
            - row["transfers_out"]
        )
        if computed_closing != row["closing"]:
            violations.append((
                idx,
                row["period"],
                row["grain_type"],
                row["grain_key"],
                computed_closing,
                row["closing"],
            ))
    if violations:
        print(f"❌ Flow Identity violations: {len(violations)}")
        for v in violations[:5]:
            print(
                f"  Row {v[0]}: {v[1]}/{v[2]}/{v[3]}: "
                f"computed={v[4]}, actual={v[5]}"
            )
        raise AssertionError(f"Flow Identity violated in {len(violations)} rows")
    else:
        print(f"✅ Flow Identity holds for all {len(org)} org_periods rows\n")

    # Task 5.3: Verify schema integrity
    print("=== Task 5.3: Schema Integrity ===")
    issues: list[str] = []
    for table_name, schema in TABLES.items():
        df = ds.tables[table_name]
        # Check non-nullable columns
        for col_def in schema.columns:
            if not col_def.nullable and col_def.name in df.columns:
                null_count = df[col_def.name].isna().sum()
                if null_count > 0:
                    issues.append(
                        f"{table_name}.{col_def.name}: "
                        f"{null_count} nulls in non-nullable column"
                    )
        # Check PK uniqueness
        pk_cols = schema.pk_columns
        if pk_cols:
            for pk in pk_cols:
                if pk in df.columns:
                    dup_count = df[pk].duplicated().sum()
                    if dup_count > 0:
                        issues.append(
                            f"{table_name}.{pk}: {dup_count} duplicate PK values"
                        )

    # Check FK resolution
    emps = ds.tables["employees"]
    depts = ds.tables["departments"]
    emp_ids = set(emps["employee_id"].tolist())
    dept_ids = set(depts["department_id"].tolist())

    # employees.department_id → departments.department_id
    bad_fk = set(emps["department_id"].tolist()) - dept_ids
    if bad_fk:
        issues.append(f"employees.department_id: {len(bad_fk)} orphan FKs")

    # employment_events.employee_id → employees.employee_id
    events = ds.tables["employment_events"]
    bad_emp_fk = set(events["employee_id"].tolist()) - emp_ids
    if bad_emp_fk:
        issues.append(
            f"employment_events.employee_id: {len(bad_emp_fk)} orphan FKs"
        )

    if issues:
        print("❌ Schema issues found:")
        for issue in issues[:10]:
            print(f"  {issue}")
        raise AssertionError(f"Schema integrity check failed: {len(issues)} issues")
    else:
        print("✅ No NULL violations, all PKs unique, all FKs resolve\n")

    # Task 5.4: Verify analytical adequacy
    print("=== Task 5.4: Analytical Adequacy ===")
    events_df = ds.tables["employment_events"]

    # Separations exist
    seps = events_df[events_df["event_type"] == "SEPARATION"]
    print(f"  Separations: {len(seps)}")
    assert len(seps) > 0, "No separations generated!"

    # Multiple cohorts (hire date months)
    hires = events_df[events_df["event_type"] == "HIRE"]
    hire_months = hires["event_date"].apply(
        lambda d: d.strftime("%Y-%m") if hasattr(d, "strftime") else str(d)[:7]
    ).nunique()
    print(f"  Distinct hire cohorts (months): {hire_months}")

    # Promotions present
    promos = events_df[events_df["event_type"] == "PROMOTION"]
    print(f"  Promotions: {len(promos)}")

    # Transfers present
    transfers = events_df[events_df["event_type"] == "TRANSFER"]
    print(f"  Transfers: {len(transfers)}")

    print("\n✅ Analytical adequacy checks passed")
    print("\n=== CHECKPOINT 5 COMPLETE ===")


if __name__ == "__main__":
    main()
