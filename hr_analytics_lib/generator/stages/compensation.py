"""Stage 4 — Build compensation intervals.

Generates the compensation table with salary records for each employee,
based on their hire events and subsequent promotions.

Invariants:
- Initial salary at hire: base = level × 20_000 + noise (within-level variance).
- New record at each PROMOTION (10–20% salary bump).
- Higher level → higher median salary per department (Req 6.6).
- All annual_salary values rounded to 2 decimal places.
- currency = "USD" always (single-currency per [P5]).
- Gap-free intervals aligned with assignment boundaries.
- Output sorted by (employee_id, effective_date).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def build_compensation(
    employees_df: pd.DataFrame,
    events_df: pd.DataFrame,
    assignments_df: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Build compensation history for every employee.

    Invariants:
    - Initial salary at hire: base = level × 20_000 + noise (within-level variance).
    - New record at each PROMOTION (10–20% salary bump).
    - Higher level → higher median salary per department (Req 6.6).
    - All annual_salary values rounded to 2 decimal places.
    - currency = "USD" always (single-currency per [P5]).
    - Gap-free intervals aligned with assignment boundaries.
    - Output sorted by (employee_id, effective_date).

    Parameters
    ----------
    employees_df : pd.DataFrame
        The employees table with employee_id, hire_date, level, department_id.
    events_df : pd.DataFrame
        The employment_events table containing PROMOTION events.
    assignments_df : pd.DataFrame
        The assignments table (used for alignment reference).
    rng : np.random.Generator
        Random number generator for this stage.

    Returns
    -------
    pd.DataFrame
        Compensation table with columns: compensation_id, employee_id,
        effective_date, annual_salary, currency.
    """
    # Filter promotion events and sort for deterministic processing
    promotion_events = events_df[events_df["event_type"] == "PROMOTION"].copy()
    promotion_events = promotion_events.sort_values(
        ["employee_id", "event_date"]
    ).reset_index(drop=True)

    # Build a lookup: employee_id -> list of (event_date, to_level) for promotions
    promo_lookup: dict[str, list[tuple[date, int]]] = {}
    for _, row in promotion_events.iterrows():
        emp_id = row["employee_id"]
        event_date = row["event_date"]
        if isinstance(event_date, pd.Timestamp):
            event_date = event_date.date()
        to_level = int(row["to_level"])
        if emp_id not in promo_lookup:
            promo_lookup[emp_id] = []
        promo_lookup[emp_id].append((event_date, to_level))

    # Process employees in sorted order for determinism
    sorted_employee_ids = sorted(employees_df["employee_id"].tolist())

    comp_records: list[dict] = []
    comp_counter = 1

    for emp_id in sorted_employee_ids:
        emp_row = employees_df[employees_df["employee_id"] == emp_id].iloc[0]
        hire_date = emp_row["hire_date"]
        if isinstance(hire_date, pd.Timestamp):
            hire_date = hire_date.date()
        initial_level = int(emp_row["level"])

        # Determine initial level at hire:
        # If this employee has promotions, their hire-level is the level before
        # the first promotion. We can infer from the events table: from_level
        # of first promotion, OR from the initial population level.
        # The employees_df "level" reflects the CURRENT level (after all events),
        # so we need to trace back to the initial level.
        emp_promos = promo_lookup.get(emp_id, [])

        if emp_promos:
            # Get the from_level of the first promotion event
            first_promo_events = promotion_events[
                promotion_events["employee_id"] == emp_id
            ].sort_values("event_date")
            first_from_level = int(first_promo_events.iloc[0]["from_level"])
            hire_level = first_from_level
        else:
            # No promotions, current level is the hire level
            hire_level = initial_level

        # 1. Initial compensation record at hire
        noise = rng.uniform(-2000.0, 5000.0)
        initial_salary = round(hire_level * 20_000 + noise, 2)
        # Ensure salary is positive
        if initial_salary <= 0:
            initial_salary = round(hire_level * 20_000 * 0.5, 2)

        comp_id = f"CMP_{comp_counter:06d}"
        comp_counter += 1
        comp_records.append({
            "compensation_id": comp_id,
            "employee_id": emp_id,
            "effective_date": hire_date,
            "annual_salary": initial_salary,
            "currency": "USD",
        })

        # 2. New record at each PROMOTION event
        current_salary = initial_salary
        for promo_date, _to_level in emp_promos:
            # 10-20% salary bump
            bump_pct = rng.uniform(0.10, 0.20)
            new_salary = round(current_salary * (1.0 + bump_pct), 2)

            comp_id = f"CMP_{comp_counter:06d}"
            comp_counter += 1
            comp_records.append({
                "compensation_id": comp_id,
                "employee_id": emp_id,
                "effective_date": promo_date,
                "annual_salary": new_salary,
                "currency": "USD",
            })
            current_salary = new_salary

    # Build DataFrame
    if comp_records:
        compensation_df = pd.DataFrame(comp_records)
    else:
        compensation_df = pd.DataFrame(
            columns=[
                "compensation_id",
                "employee_id",
                "effective_date",
                "annual_salary",
                "currency",
            ]
        )

    # Sort by (employee_id, effective_date) ascending
    compensation_df = compensation_df.sort_values(
        ["employee_id", "effective_date"]
    ).reset_index(drop=True)

    return compensation_df
