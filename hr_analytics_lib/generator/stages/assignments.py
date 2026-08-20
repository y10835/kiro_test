"""Stage 3 — Build assignment history from employment events.

Constructs gap-free, non-overlapping assignment chains for every employee by
processing employment events (HIRE, TRANSFER, PROMOTION, SEPARATION) in
chronological order.

Invariants:
- First assignment per employee: start_date = hire_date.
- Assignments break at TRANSFER and PROMOTION event boundaries.
- No gaps: end_date of assignment N = start_date of assignment N+1.
- No overlaps: intervals are disjoint per employee.
- For separated employees: last assignment end_date = separation_date.
- For active employees: last assignment end_date = None.
- Output sorted by (employee_id, start_date).
- Assignment IDs are sequential: ASN_000001, ASN_000002, ...
- All randomness flows from the provided numpy Generator (determinism).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def build_assignments(
    employees_df: pd.DataFrame,
    events_df: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Build gap-free, non-overlapping assignment chains for every employee.

    Parameters
    ----------
    employees_df : pd.DataFrame
        The employees table with columns: employee_id, hire_date, separation_date,
        separation_type, level, department_id.
    events_df : pd.DataFrame
        The employment_events table with columns: event_id, employee_id, event_date,
        event_type, from_department_id, to_department_id, from_level, to_level.
    rng : np.random.Generator
        The random number generator for this stage (stream contract).

    Returns
    -------
    pd.DataFrame
        The assignments table with columns: assignment_id, employee_id,
        department_id, level, start_date, end_date.

    Invariants:
    - First assignment per employee: start_date = hire_date, reason implied by HIRE event.
    - Assignments break at TRANSFER and PROMOTION event boundaries.
    - No gaps: end_date of assignment N = start_date of assignment N+1.
    - No overlaps: intervals are disjoint per employee.
    - For separated employees: last assignment end_date = separation_date.
    - For active employees: last assignment end_date = None.
    - Output sorted by (employee_id, start_date).
    """
    # Advance RNG state to maintain stream contract even though
    # assignment logic is deterministic given events.
    _ = rng.integers(0, 1000)

    # Sort employees by employee_id for deterministic processing order.
    employee_ids = sorted(employees_df["employee_id"].tolist())

    # Build a lookup for employee data.
    emp_lookup: dict[str, dict] = {}
    for _, row in employees_df.iterrows():
        emp_id = row["employee_id"]
        hire_date = _to_date(row["hire_date"])
        sep_date = _to_date(row["separation_date"])
        emp_lookup[emp_id] = {
            "hire_date": hire_date,
            "separation_date": sep_date,
        }

    # Group events by employee_id, then sort by event_date within each group.
    events_by_employee: dict[str, list[dict]] = {}
    for _, row in events_df.iterrows():
        emp_id = row["employee_id"]
        if emp_id not in events_by_employee:
            events_by_employee[emp_id] = []
        events_by_employee[emp_id].append({
            "event_id": row["event_id"],
            "event_date": _to_date(row["event_date"]),
            "event_type": row["event_type"],
            "from_department_id": row.get("from_department_id"),
            "to_department_id": row.get("to_department_id"),
            "from_level": row.get("from_level"),
            "to_level": row.get("to_level"),
        })

    # Sort each employee's events by event_date.
    for emp_id in events_by_employee:
        events_by_employee[emp_id].sort(key=lambda e: e["event_date"])

    # Build assignment chains.
    assignment_rows: list[dict] = []
    assignment_counter = 0

    for emp_id in employee_ids:
        emp_data = emp_lookup[emp_id]
        hire_date = emp_data["hire_date"]
        separation_date = emp_data["separation_date"]

        events = events_by_employee.get(emp_id, [])

        # Find the HIRE event to determine initial department and level.
        hire_event = None
        for evt in events:
            if evt["event_type"] == "HIRE":
                hire_event = evt
                break

        if hire_event is None:
            # No HIRE event found — skip employee (should not happen in clean data).
            continue

        # Initial assignment state from HIRE event.
        current_department = _resolve_str(hire_event.get("to_department_id"))
        current_level = _resolve_int(hire_event.get("to_level"))

        # If the HIRE event doesn't have to_department_id / to_level,
        # fall back to the employee row values. In the simulation, HIRE events
        # typically populate to_department_id and to_level.
        if current_department is None:
            # Fallback: use the initial department from the employees table
            # (We need to look at the employee row for initial dept.)
            # Since employees table may have been updated by simulation,
            # use the first event's context.
            emp_row = employees_df[employees_df["employee_id"] == emp_id].iloc[0]
            current_department = emp_row["department_id"]
        if current_level is None:
            emp_row = employees_df[employees_df["employee_id"] == emp_id].iloc[0]
            current_level = int(emp_row["level"])

        # Start the first assignment at hire_date.
        current_start = hire_date

        # Process subsequent events that break assignment boundaries.
        # Only TRANSFER and PROMOTION events create new assignments.
        boundary_events = [
            evt for evt in events
            if evt["event_type"] in ("TRANSFER", "PROMOTION")
            and evt["event_date"] >= hire_date
        ]

        # Sort boundary events by date (already sorted, but be explicit).
        boundary_events.sort(key=lambda e: e["event_date"])

        for evt in boundary_events:
            # Close the current assignment.
            end_date = evt["event_date"]

            assignment_counter += 1
            assignment_id = f"ASN_{assignment_counter:06d}"
            assignment_rows.append({
                "assignment_id": assignment_id,
                "employee_id": emp_id,
                "department_id": current_department,
                "level": current_level,
                "start_date": current_start,
                "end_date": end_date,
            })

            # Start a new assignment.
            current_start = end_date

            if evt["event_type"] == "TRANSFER":
                # Transfer: new department, same level.
                new_dept = _resolve_str(evt.get("to_department_id"))
                if new_dept is not None:
                    current_department = new_dept
            elif evt["event_type"] == "PROMOTION":
                # Promotion: same department, new level.
                new_level = _resolve_int(evt.get("to_level"))
                if new_level is not None:
                    current_level = new_level

        # Close the last (or only) assignment.
        if separation_date is not None:
            final_end_date = separation_date
        else:
            final_end_date = None

        assignment_counter += 1
        assignment_id = f"ASN_{assignment_counter:06d}"
        assignment_rows.append({
            "assignment_id": assignment_id,
            "employee_id": emp_id,
            "department_id": current_department,
            "level": current_level,
            "start_date": current_start,
            "end_date": final_end_date,
        })

    # Build the DataFrame.
    if assignment_rows:
        assignments_df = pd.DataFrame(assignment_rows)
    else:
        assignments_df = pd.DataFrame(
            columns=[
                "assignment_id", "employee_id", "department_id",
                "level", "start_date", "end_date",
            ]
        )

    # Ensure correct dtypes.
    if not assignments_df.empty:
        assignments_df["level"] = assignments_df["level"].astype("int64")

    # Sort by (employee_id, start_date) — schema sort keys at positions 0, 1.
    assignments_df = assignments_df.sort_values(
        ["employee_id", "start_date"]
    ).reset_index(drop=True)

    return assignments_df


def _to_date(value) -> date | None:
    """Convert a value to a Python date, handling None/NaT/Timestamp."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()
    # Handle numpy datetime64
    if hasattr(value, "item"):
        return pd.Timestamp(value).date()
    # Handle NaN/NaT
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    # Last resort: try pandas conversion
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.date()
    except (ValueError, TypeError):
        return None


def _resolve_str(value) -> str | None:
    """Resolve a potentially null/NaN string value to str or None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _resolve_int(value) -> int | None:
    """Resolve a potentially null/NaN integer value to int or None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
