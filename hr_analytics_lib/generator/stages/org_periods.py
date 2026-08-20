"""Stage 6 — Aggregate headcount flows and labor cost into org_periods.

Computes the org_periods table by aggregating employment events and compensation
data into headcount flow metrics at three grains: ORG, DEPARTMENT, and LEVEL.

Invariants:
- Flow_Identity holds for every row: opening + hires + transfers_in - separations - transfers_out = closing.
- Computed at three grains: ORG, DEPARTMENT, LEVEL.
- Period-chain continuity: closing[N] = opening[N+1] at same grain.
- Cross-grain consistency: sum of DEPARTMENT closing = ORG closing for each period.
- total_labor_cost = sum(active employee annual_salary / 12) for that grain/period.
- Output sorted by (period, grain_type, grain_key).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from hr_analytics_lib.generator.config import GenerationConfig


def _generate_periods(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """Generate monthly (period_start, period_end) tuples.

    Each period covers one full calendar month. Uses pandas date_range
    for month-start generation.

    Parameters
    ----------
    start_date : date
        Simulation start date.
    end_date : date
        Simulation end date.

    Returns
    -------
    list[tuple[date, date]]
        Monthly periods as (first_day_of_month, last_day_of_month) tuples.
    """
    periods: list[tuple[date, date]] = []
    month_starts = pd.date_range(
        start=start_date.replace(day=1),
        end=end_date,
        freq="MS",
    )
    for ms in month_starts:
        period_start = ms.date()
        if ms.month == 12:
            period_end = date(ms.year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(ms.year, ms.month + 1, 1) - timedelta(days=1)
        if period_end > end_date:
            period_end = end_date
        periods.append((period_start, period_end))
    return periods


def _period_label(d: date) -> str:
    """Return the 'YYYY-MM' string for a date."""
    return f"{d.year:04d}-{d.month:02d}"


def _to_date(val) -> date | None:
    """Convert a value to a Python date, or None if NaT/None."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, pd.Timestamp):
        return val
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.date()
    if pd.isna(val):
        return None
    return pd.Timestamp(val).date()


def aggregate_org_periods(
    employees_df: pd.DataFrame,
    events_df: pd.DataFrame,
    compensation_df: pd.DataFrame,
    config: GenerationConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Aggregate headcount flows and labor cost into org_periods table.

    Invariants:
    - Flow_Identity holds for every row: opening + hires + transfers_in - separations - transfers_out = closing.
    - Computed at three grains: ORG, DEPARTMENT, LEVEL.
    - Period-chain continuity: closing[N] = opening[N+1] at same grain.
    - Cross-grain consistency: sum of DEPARTMENT closing = ORG closing for each period.
    - total_labor_cost = sum(active employee annual_salary / 12) for that grain/period.
    - Output sorted by (period, grain_type, grain_key).
    """
    # Advance RNG state for stream contract (aggregation is deterministic given inputs)
    rng.random()

    periods = _generate_periods(config.start_date, config.end_date)

    # Pre-process employees: extract hire_date, separation_date, initial dept/level
    emp_records: list[dict] = []
    for _, row in employees_df.iterrows():
        emp_records.append({
            "employee_id": row["employee_id"],
            "hire_date": _to_date(row["hire_date"]),
            "separation_date": _to_date(row.get("separation_date")),
            "department_id": row["department_id"],
            "level": int(row["level"]),
        })

    # Pre-process events by type for quick lookup
    hire_events: list[dict] = []
    separation_events: list[dict] = []
    transfer_events: list[dict] = []
    promotion_events: list[dict] = []

    for _, row in events_df.iterrows():
        event_date = _to_date(row["event_date"])
        event_type = row["event_type"]
        emp_id = row["employee_id"]

        if event_type == "HIRE":
            hire_events.append({
                "employee_id": emp_id,
                "event_date": event_date,
                "to_department_id": row.get("to_department_id"),
                "to_level": int(row["to_level"]) if row.get("to_level") is not None and not pd.isna(row.get("to_level", float("nan"))) else None,
            })
        elif event_type == "SEPARATION":
            separation_events.append({
                "employee_id": emp_id,
                "event_date": event_date,
                "from_department_id": row.get("from_department_id"),
                "from_level": int(row["from_level"]) if row.get("from_level") is not None and not pd.isna(row.get("from_level", float("nan"))) else None,
            })
        elif event_type == "TRANSFER":
            transfer_events.append({
                "employee_id": emp_id,
                "event_date": event_date,
                "from_department_id": row.get("from_department_id"),
                "to_department_id": row.get("to_department_id"),
            })
        elif event_type == "PROMOTION":
            promotion_events.append({
                "employee_id": emp_id,
                "event_date": event_date,
                "from_level": int(row["from_level"]) if row.get("from_level") is not None and not pd.isna(row.get("from_level", float("nan"))) else None,
                "to_level": int(row["to_level"]) if row.get("to_level") is not None and not pd.isna(row.get("to_level", float("nan"))) else None,
            })

    # Pre-process compensation: sorted by employee_id, effective_date for quick lookup
    comp_records: list[dict] = []
    for _, row in compensation_df.iterrows():
        comp_records.append({
            "employee_id": row["employee_id"],
            "effective_date": _to_date(row["effective_date"]),
            "annual_salary": float(row["annual_salary"]),
        })
    # Sort by (employee_id, effective_date) for binary search
    comp_records.sort(key=lambda r: (r["employee_id"], r["effective_date"]))

    # Build a mapping: employee_id -> list of compensation records (ordered by date)
    comp_by_emp: dict[str, list[dict]] = {}
    for rec in comp_records:
        emp_id = rec["employee_id"]
        if emp_id not in comp_by_emp:
            comp_by_emp[emp_id] = []
        comp_by_emp[emp_id].append(rec)

    # Gather all department IDs and levels for grain enumeration
    all_dept_ids = sorted(employees_df["department_id"].unique().tolist())
    # Add any departments from events that might not be in initial employees
    for evt in transfer_events:
        if evt["from_department_id"] and evt["from_department_id"] not in all_dept_ids:
            all_dept_ids.append(evt["from_department_id"])
        if evt["to_department_id"] and evt["to_department_id"] not in all_dept_ids:
            all_dept_ids.append(evt["to_department_id"])
    all_dept_ids = sorted(set(all_dept_ids))

    all_levels: set[int] = set()
    for rec in emp_records:
        all_levels.add(rec["level"])
    for evt in hire_events:
        if evt["to_level"] is not None:
            all_levels.add(evt["to_level"])
    for evt in promotion_events:
        if evt["from_level"] is not None:
            all_levels.add(evt["from_level"])
        if evt["to_level"] is not None:
            all_levels.add(evt["to_level"])
    all_levels_sorted = sorted(all_levels)

    # Helper: get effective salary for an employee at a given date
    def _get_salary_at_date(emp_id: str, target_date: date) -> float:
        """Return the active annual_salary for an employee at target_date.

        Uses the most recent compensation record with effective_date <= target_date.
        Returns 0.0 if no compensation record applies.
        """
        records = comp_by_emp.get(emp_id, [])
        if not records:
            return 0.0
        # Find the latest record where effective_date <= target_date
        salary = 0.0
        for rec in records:
            if rec["effective_date"] <= target_date:
                salary = rec["annual_salary"]
            else:
                break
        return salary

    # Helper: determine active employees at a point in time
    def _is_active(emp: dict, period_start: date, period_end: date) -> bool:
        """Check if an employee is active during the period.

        Active means: hire_date <= period_end AND (separation_date is None OR separation_date >= period_start)
        """
        if emp["hire_date"] is None:
            return False
        if emp["hire_date"] > period_end:
            return False
        if emp["separation_date"] is not None and emp["separation_date"] < period_start:
            return False
        return True

    # We need to track the department and level of each employee over time.
    # Build state tracking: for each employee, track current department and level over time.
    # We reconstruct state by replaying events in chronological order.
    emp_state: dict[str, dict] = {}
    for rec in emp_records:
        emp_state[rec["employee_id"]] = {
            "department_id": rec["department_id"],
            "level": rec["level"],
            "hire_date": rec["hire_date"],
            "separation_date": rec["separation_date"],
        }

    # For HIRE events of employees not in initial population, add their state
    for evt in hire_events:
        emp_id = evt["employee_id"]
        if emp_id not in emp_state:
            # Find in emp_records
            matching = [r for r in emp_records if r["employee_id"] == emp_id]
            if matching:
                rec = matching[0]
                emp_state[emp_id] = {
                    "department_id": rec["department_id"],
                    "level": rec["level"],
                    "hire_date": rec["hire_date"],
                    "separation_date": rec["separation_date"],
                }

    # Sort all events by date for sequential state tracking
    all_events_chrono: list[dict] = []
    for evt in transfer_events:
        all_events_chrono.append({"type": "TRANSFER", **evt})
    for evt in promotion_events:
        all_events_chrono.append({"type": "PROMOTION", **evt})
    all_events_chrono.sort(key=lambda e: e["event_date"])

    # For each period, we need to know each employee's department and level.
    # Strategy: for each period, compute state at period_end by replaying events.
    # We'll track state mutations and compute per-period snapshots.

    # Build event timeline per employee for state reconstruction
    emp_timeline: dict[str, list[dict]] = {}
    for evt in all_events_chrono:
        emp_id = evt["employee_id"]
        if emp_id not in emp_timeline:
            emp_timeline[emp_id] = []
        emp_timeline[emp_id].append(evt)

    def _get_emp_state_at_date(emp_id: str, target_date: date) -> tuple[str, int]:
        """Get (department_id, level) for an employee at a given date.

        Replays events up to target_date to determine current state.
        """
        state = emp_state.get(emp_id)
        if state is None:
            return ("UNKNOWN", 0)
        dept = state["department_id"]
        level = state["level"]

        timeline = emp_timeline.get(emp_id, [])
        for evt in timeline:
            if evt["event_date"] > target_date:
                break
            if evt["type"] == "TRANSFER":
                if evt.get("to_department_id"):
                    dept = evt["to_department_id"]
            elif evt["type"] == "PROMOTION":
                if evt.get("to_level") is not None:
                    level = evt["to_level"]
        return (dept, level)

    # Now compute org_periods rows
    rows: list[dict] = []

    # Track closing values for period-chain continuity
    # Key: (grain_type, grain_key) -> closing value from previous period
    prev_closing: dict[tuple[str, str], int] = {}

    for period_idx, (period_start, period_end) in enumerate(periods):
        period_label = _period_label(period_start)

        # Determine which employees are active during this period
        # An employee is "in headcount" at period start if:
        #   hire_date <= period_start AND (separation_date is None OR separation_date >= period_start)
        # For the first period, opening = count of employees hired on or before period_start
        # For subsequent periods, opening = previous closing (period-chain continuity)

        # Identify active employees at period_start (for opening count)
        active_at_start: list[str] = []
        for emp_id, state in emp_state.items():
            hire_d = state["hire_date"]
            sep_d = state["separation_date"]
            if hire_d is None or hire_d > period_start:
                continue
            if sep_d is not None and sep_d < period_start:
                continue
            active_at_start.append(emp_id)
        active_at_start.sort()

        # Identify active employees at period_end (for labor cost computation)
        active_at_end: list[str] = []
        for emp_id, state in emp_state.items():
            hire_d = state["hire_date"]
            sep_d = state["separation_date"]
            if hire_d is None or hire_d > period_end:
                continue
            if sep_d is not None and sep_d < period_start:
                continue
            active_at_end.append(emp_id)
        active_at_end.sort()

        # Events in this period
        period_hires = [
            e for e in hire_events
            if e["event_date"] is not None
            and period_start <= e["event_date"] <= period_end
        ]
        period_separations = [
            e for e in separation_events
            if e["event_date"] is not None
            and period_start <= e["event_date"] <= period_end
        ]
        period_transfers = [
            e for e in transfer_events
            if e["event_date"] is not None
            and period_start <= e["event_date"] <= period_end
        ]
        period_promotions = [
            e for e in promotion_events
            if e["event_date"] is not None
            and period_start <= e["event_date"] <= period_end
        ]

        # =====================================================================
        # ORG grain
        # =====================================================================
        org_key = ("ORG", "ALL")

        if period_idx == 0:
            org_opening = len(active_at_start)
        else:
            org_opening = prev_closing.get(org_key, len(active_at_start))

        org_hires = len(period_hires)
        org_separations = len(period_separations)
        # For ORG grain: transfers_in = transfers_out = 0 (transfers are internal)
        org_transfers_in = 0
        org_transfers_out = 0
        org_closing = org_opening + org_hires + org_transfers_in - org_separations - org_transfers_out

        # Labor cost: sum of salary/12 for all active employees in this period
        org_labor_cost = 0.0
        for emp_id in active_at_end:
            salary = _get_salary_at_date(emp_id, period_end)
            org_labor_cost += salary / 12.0
        org_labor_cost = round(org_labor_cost, 2)

        rows.append({
            "period": period_label,
            "grain_type": "ORG",
            "grain_key": "ALL",
            "opening": org_opening,
            "hires": org_hires,
            "separations": org_separations,
            "transfers_in": org_transfers_in,
            "transfers_out": org_transfers_out,
            "closing": org_closing,
            "total_labor_cost": org_labor_cost,
        })
        prev_closing[org_key] = org_closing

        # =====================================================================
        # DEPARTMENT grain
        # =====================================================================
        for dept_id in all_dept_ids:
            dept_key = ("DEPARTMENT", dept_id)

            # Opening: count of active employees in this department at period_start
            if period_idx == 0:
                dept_opening = sum(
                    1 for emp_id in active_at_start
                    if _get_emp_state_at_date(emp_id, period_start)[0] == dept_id
                )
            else:
                dept_opening = prev_closing.get(dept_key, 0)

            # Hires into this department
            dept_hires = sum(
                1 for e in period_hires
                if e.get("to_department_id") == dept_id
            )

            # Separations from this department
            dept_separations = sum(
                1 for e in period_separations
                if e.get("from_department_id") == dept_id
            )

            # Transfers in: transfers where to_department_id == dept_id
            dept_transfers_in = sum(
                1 for e in period_transfers
                if e.get("to_department_id") == dept_id
            )

            # Transfers out: transfers where from_department_id == dept_id
            dept_transfers_out = sum(
                1 for e in period_transfers
                if e.get("from_department_id") == dept_id
            )

            dept_closing = dept_opening + dept_hires + dept_transfers_in - dept_separations - dept_transfers_out

            # Labor cost for this department
            dept_labor_cost = 0.0
            for emp_id in active_at_end:
                emp_dept, _ = _get_emp_state_at_date(emp_id, period_end)
                if emp_dept == dept_id:
                    salary = _get_salary_at_date(emp_id, period_end)
                    dept_labor_cost += salary / 12.0
            dept_labor_cost = round(dept_labor_cost, 2)

            rows.append({
                "period": period_label,
                "grain_type": "DEPARTMENT",
                "grain_key": dept_id,
                "opening": dept_opening,
                "hires": dept_hires,
                "separations": dept_separations,
                "transfers_in": dept_transfers_in,
                "transfers_out": dept_transfers_out,
                "closing": dept_closing,
                "total_labor_cost": dept_labor_cost,
            })
            prev_closing[dept_key] = dept_closing

        # =====================================================================
        # LEVEL grain
        # =====================================================================
        for level in all_levels_sorted:
            level_key = ("LEVEL", str(level))

            # Opening: count of active employees at this level at period_start
            if period_idx == 0:
                level_opening = sum(
                    1 for emp_id in active_at_start
                    if _get_emp_state_at_date(emp_id, period_start)[1] == level
                )
            else:
                level_opening = prev_closing.get(level_key, 0)

            # Hires at this level
            level_hires = sum(
                1 for e in period_hires
                if e.get("to_level") == level
            )

            # Separations at this level
            level_separations = sum(
                1 for e in period_separations
                if e.get("from_level") == level
            )

            # For LEVEL grain: PROMOTION events count as transfers
            # transfers_out from old level, transfers_in to new level
            level_transfers_in = sum(
                1 for e in period_promotions
                if e.get("to_level") == level
            )
            level_transfers_out = sum(
                1 for e in period_promotions
                if e.get("from_level") == level
            )

            level_closing = level_opening + level_hires + level_transfers_in - level_separations - level_transfers_out

            # Labor cost for this level
            level_labor_cost = 0.0
            for emp_id in active_at_end:
                _, emp_level = _get_emp_state_at_date(emp_id, period_end)
                if emp_level == level:
                    salary = _get_salary_at_date(emp_id, period_end)
                    level_labor_cost += salary / 12.0
            level_labor_cost = round(level_labor_cost, 2)

            rows.append({
                "period": period_label,
                "grain_type": "LEVEL",
                "grain_key": str(level),
                "opening": level_opening,
                "hires": level_hires,
                "separations": level_separations,
                "transfers_in": level_transfers_in,
                "transfers_out": level_transfers_out,
                "closing": level_closing,
                "total_labor_cost": level_labor_cost,
            })
            prev_closing[level_key] = level_closing

    # Build DataFrame
    if rows:
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(columns=[
            "period", "grain_type", "grain_key", "opening", "hires",
            "separations", "transfers_in", "transfers_out", "closing",
            "total_labor_cost",
        ])

    # Ensure correct dtypes
    int_cols = ["opening", "hires", "separations", "transfers_in", "transfers_out", "closing"]
    for col in int_cols:
        if col in df.columns:
            df[col] = df[col].astype("int64")
    if "total_labor_cost" in df.columns:
        df["total_labor_cost"] = df["total_labor_cost"].astype("float64")

    # Sort by (period, grain_type, grain_key)
    df = df.sort_values(["period", "grain_type", "grain_key"]).reset_index(drop=True)

    return df
