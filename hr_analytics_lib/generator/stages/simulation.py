"""Stage 2 — Period-by-period workforce simulation.

Simulates employment events month by month over the configured date range,
producing separation, hire, transfer, and promotion events.

Invariants:
- At least 1 separation per period when >= 10 active employees (Req 6.1).
- Separations classified as VOLUNTARY/INVOLUNTARY per configured split (Req 6.2).
- At least 1 PROMOTION event per 12-month window when headcount >= 5 and n_levels >= 2 (Req 6.5).
- HIRE events distributed so that at least two periods differ by >= 2x volume (Req 6.8).
- At least one employee spans the full date range without separation (Req 6.9).
- All randomness flows from the provided numpy Generator (determinism).
- Event IDs are sequential, continuing from where initial events left off.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from hr_analytics_lib.generator.config import GenerationConfig


def _generate_periods(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """Generate a list of (period_start, period_end) tuples for monthly intervals.

    Each period covers one full calendar month. The first period starts at
    start_date (first of month) and the last period ends at end_date (last day
    of that month).

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
    # Use pandas date_range to generate month starts
    month_starts = pd.date_range(
        start=start_date.replace(day=1),
        end=end_date,
        freq="MS",  # Month Start
    )
    for ms in month_starts:
        period_start = ms.date()
        # End of month: go to next month, subtract 1 day
        if ms.month == 12:
            period_end = date(ms.year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(ms.year, ms.month + 1, 1) - timedelta(days=1)
        # Clamp period_end to end_date
        if period_end > end_date:
            period_end = end_date
        periods.append((period_start, period_end))
    return periods


def _random_date_in_range(
    start: date, end: date, rng: np.random.Generator
) -> date:
    """Pick a random date uniformly within [start, end].

    Parameters
    ----------
    start : date
        Earliest possible date (inclusive).
    end : date
        Latest possible date (inclusive).
    rng : np.random.Generator
        Random number generator.

    Returns
    -------
    date
        A randomly selected date in [start, end].
    """
    delta_days = (end - start).days
    if delta_days <= 0:
        return start
    offset = int(rng.integers(0, delta_days + 1))
    return start + timedelta(days=offset)


def simulate_periods(
    employees_df: pd.DataFrame,
    initial_events_df: pd.DataFrame,
    config: GenerationConfig,
    departments_df: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate employment events period-by-period.

    Produces separation, hire, transfer, and promotion events for each
    monthly period in [start_date, end_date].

    Parameters
    ----------
    employees_df : pd.DataFrame
        Initial employees (from Stage 1).
    initial_events_df : pd.DataFrame
        Initial HIRE events (from Stage 1).
    config : GenerationConfig
        The generation configuration.
    departments_df : pd.DataFrame
        The departments table.
    rng : np.random.Generator
        Random number generator for this stage.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (updated_employees_df, all_events_df)
        - updated_employees_df includes new hires and separation info
        - all_events_df includes initial HIRE events plus all new events

    Invariants:
    - At least 1 separation per period when >= 10 active employees (Req 6.1).
    - Separations classified as VOLUNTARY/INVOLUNTARY per configured split (Req 6.2).
    - At least 1 PROMOTION event per 12-month window when headcount >= 5 and n_levels >= 2 (Req 6.5).
    - HIRE events distributed so that at least two periods differ by >= 2x volume (Req 6.8).
    - At least one employee spans the full date range without separation (Req 6.9).
    """
    # Work with a mutable copy of employees
    employees = employees_df.copy()

    # Determine next sequential IDs
    # Events: EVT_NNNNNN continuing from initial events
    next_event_num = len(initial_events_df) + 1
    # Employees: EMP_NNNNNN continuing from initial population
    next_emp_num = len(employees) + 1

    # Department IDs for assignment
    dept_ids = sorted(departments_df["department_id"].tolist())

    # Generate monthly periods
    periods = _generate_periods(config.start_date, config.end_date)

    # Protect the first employee from ever separating (Req 6.9)
    protected_employee_id = sorted(employees["employee_id"].tolist())[0]

    # Track events generated per period
    all_new_events: list[dict] = []
    new_employees: list[dict] = []

    # Track hires per period for Req 6.8 enforcement
    hires_per_period: list[int] = []

    # Track promotions for Req 6.5 enforcement (rolling 12-month window)
    promotions_per_period: list[int] = []

    # Monthly rates derived from annual rates
    monthly_sep_prob = config.annual_separation_rate / 12.0
    monthly_transfer_prob = 0.02 / 12.0  # ~2% annual transfer rate
    monthly_promotion_prob = 0.05 / 12.0  # ~5% annual promotion rate

    # Voluntary/Involuntary split (default 70/30)
    voluntary_ratio = 0.70

    for period_idx, (period_start, period_end) in enumerate(periods):
        # --- Identify active employees ---
        # Active = hired on or before period_end AND (no separation OR separation_date > period_start)
        active_mask = employees["hire_date"].apply(
            lambda d: d <= period_end if isinstance(d, date) else pd.Timestamp(d).date() <= period_end
        )
        sep_mask = employees["separation_date"].apply(
            lambda d: d is None or (isinstance(d, date) and d >= period_start) or (
                d is not None and not isinstance(d, date) and pd.notna(d) and pd.Timestamp(d).date() >= period_start
            )
        )
        active_employees = employees[active_mask & sep_mask].copy()

        # More precise: active means not yet separated
        active_employees = active_employees[
            active_employees["separation_date"].isna()
            | active_employees["separation_date"].apply(
                lambda d: d is None
            )
        ]

        # Also ensure hire_date <= period_end
        active_employees = active_employees[
            active_employees["hire_date"].apply(
                lambda d: (d if isinstance(d, date) else pd.Timestamp(d).date()) <= period_end
            )
        ]

        active_ids = sorted(active_employees["employee_id"].tolist())
        n_active = len(active_ids)

        # =====================================================================
        # 1. SEPARATIONS
        # =====================================================================
        period_separations = 0
        if n_active > 0 and monthly_sep_prob > 0:
            # Draw separations for each active employee (excluding protected)
            eligible_for_sep = [eid for eid in active_ids if eid != protected_employee_id]

            if eligible_for_sep:
                sep_draws = rng.random(len(eligible_for_sep))
                separating_ids = [
                    eid for eid, draw in zip(eligible_for_sep, sep_draws)
                    if draw < monthly_sep_prob
                ]

                # Req 6.1: force at least 1 separation if >= 10 active and none drawn
                if n_active >= 10 and len(separating_ids) == 0 and len(eligible_for_sep) > 0:
                    forced_idx = int(rng.integers(0, len(eligible_for_sep)))
                    separating_ids = [eligible_for_sep[forced_idx]]

                for emp_id in separating_ids:
                    # Determine separation date: random day within period, but >= hire_date
                    emp_row = employees[employees["employee_id"] == emp_id].iloc[0]
                    emp_hire_date = emp_row["hire_date"]
                    if isinstance(emp_hire_date, pd.Timestamp):
                        emp_hire_date = emp_hire_date.date()

                    sep_start = max(period_start, emp_hire_date)
                    sep_date = _random_date_in_range(sep_start, period_end, rng)

                    # Classify as VOLUNTARY or INVOLUNTARY
                    is_voluntary = rng.random() < voluntary_ratio
                    sep_type = "VOLUNTARY" if is_voluntary else "INVOLUNTARY"

                    # Update employee record
                    emp_idx = employees[employees["employee_id"] == emp_id].index[0]
                    employees.at[emp_idx, "separation_date"] = sep_date
                    employees.at[emp_idx, "separation_type"] = sep_type

                    # Create SEPARATION event
                    event_id = f"EVT_{next_event_num:06d}"
                    next_event_num += 1
                    emp_dept = emp_row["department_id"]
                    emp_level = emp_row["level"]

                    all_new_events.append({
                        "event_id": event_id,
                        "employee_id": emp_id,
                        "event_date": sep_date,
                        "event_type": "SEPARATION",
                        "from_department_id": emp_dept,
                        "to_department_id": None,
                        "from_level": int(emp_level) if emp_level is not None else None,
                        "to_level": None,
                    })
                    period_separations += 1

        # =====================================================================
        # 2. HIRES
        # =====================================================================
        # Monthly hire count via Poisson
        hire_lambda = config.annual_hiring_rate / 12.0 * n_active if n_active > 0 else 0.0
        n_hires = int(rng.poisson(hire_lambda)) if hire_lambda > 0 else 0

        for _ in range(n_hires):
            emp_id = f"EMP_{next_emp_num:06d}"
            next_emp_num += 1

            hire_date = _random_date_in_range(period_start, period_end, rng)

            # Assign level (pyramid distribution)
            n_levels = config.n_levels
            weights = np.array(
                [n_levels - i + 1 for i in range(1, n_levels + 1)], dtype=float
            )
            weights /= weights.sum()
            level = int(rng.choice(np.arange(1, n_levels + 1), p=weights))

            # Assign department (uniform)
            dept_idx = int(rng.integers(0, len(dept_ids)))
            dept_id = dept_ids[dept_idx]

            # Add to employee records
            new_employees.append({
                "employee_id": emp_id,
                "hire_date": hire_date,
                "separation_date": None,
                "separation_type": None,
                "level": level,
                "department_id": dept_id,
            })

            # Create HIRE event
            event_id = f"EVT_{next_event_num:06d}"
            next_event_num += 1
            all_new_events.append({
                "event_id": event_id,
                "employee_id": emp_id,
                "event_date": hire_date,
                "event_type": "HIRE",
                "from_department_id": None,
                "to_department_id": dept_id,
                "from_level": None,
                "to_level": level,
            })

        hires_per_period.append(n_hires)

        # =====================================================================
        # 3. TRANSFERS (cross-department moves)
        # =====================================================================
        # Recalculate active employees after separations (but before new hires settle)
        remaining_active = [
            eid for eid in active_ids
            if employees[employees["employee_id"] == eid].iloc[0]["separation_date"] is None
            or (
                not isinstance(employees[employees["employee_id"] == eid].iloc[0]["separation_date"], date)
                and pd.isna(employees[employees["employee_id"] == eid].iloc[0]["separation_date"])
            )
        ]

        if len(remaining_active) > 0 and len(dept_ids) > 1:
            transfer_draws = rng.random(len(remaining_active))
            transferring_ids = [
                eid for eid, draw in zip(remaining_active, transfer_draws)
                if draw < monthly_transfer_prob
            ]

            for emp_id in transferring_ids:
                emp_row = employees[employees["employee_id"] == emp_id].iloc[0]
                current_dept = emp_row["department_id"]
                # Choose a different department
                other_depts = [d for d in dept_ids if d != current_dept]
                if not other_depts:
                    continue
                new_dept_idx = int(rng.integers(0, len(other_depts)))
                new_dept = other_depts[new_dept_idx]

                transfer_date = _random_date_in_range(period_start, period_end, rng)

                # Update employee's current department
                emp_idx = employees[employees["employee_id"] == emp_id].index[0]
                employees.at[emp_idx, "department_id"] = new_dept

                # Create TRANSFER event
                event_id = f"EVT_{next_event_num:06d}"
                next_event_num += 1
                all_new_events.append({
                    "event_id": event_id,
                    "employee_id": emp_id,
                    "event_date": transfer_date,
                    "event_type": "TRANSFER",
                    "from_department_id": current_dept,
                    "to_department_id": new_dept,
                    "from_level": None,
                    "to_level": None,
                })

        # =====================================================================
        # 4. PROMOTIONS
        # =====================================================================
        period_promotions = 0
        if config.n_levels >= 2:
            # Eligible for promotion: active, not separated, below max level
            promo_eligible = [
                eid for eid in remaining_active
                if int(employees[employees["employee_id"] == eid].iloc[0]["level"]) < config.n_levels
            ]

            if promo_eligible:
                promo_draws = rng.random(len(promo_eligible))
                promoting_ids = [
                    eid for eid, draw in zip(promo_eligible, promo_draws)
                    if draw < monthly_promotion_prob
                ]

                for emp_id in promoting_ids:
                    emp_row = employees[employees["employee_id"] == emp_id].iloc[0]
                    current_level = int(emp_row["level"])
                    new_level = current_level + 1

                    promo_date = _random_date_in_range(period_start, period_end, rng)

                    # Update employee's level
                    emp_idx = employees[employees["employee_id"] == emp_id].index[0]
                    employees.at[emp_idx, "level"] = new_level

                    # Create PROMOTION event
                    event_id = f"EVT_{next_event_num:06d}"
                    next_event_num += 1
                    all_new_events.append({
                        "event_id": event_id,
                        "employee_id": emp_id,
                        "event_date": promo_date,
                        "event_type": "PROMOTION",
                        "from_department_id": None,
                        "to_department_id": None,
                        "from_level": current_level,
                        "to_level": new_level,
                    })
                    period_promotions += 1

        promotions_per_period.append(period_promotions)

        # Append new hires to employees DataFrame for next period visibility
        if new_employees:
            # Only append employees hired in this period
            period_new_emps = new_employees[-(n_hires):] if n_hires > 0 else []
            if period_new_emps:
                new_emp_df = pd.DataFrame(period_new_emps)
                employees = pd.concat([employees, new_emp_df], ignore_index=True)

    # =========================================================================
    # Post-simulation enforcement of analytical adequacy constraints
    # =========================================================================

    # --- Req 6.5: Ensure at least 1 promotion per 12-month window ---
    if config.n_levels >= 2 and len(periods) >= 1:
        # Check each 12-month window
        window_size = min(12, len(periods))
        for window_start in range(0, len(periods) - window_size + 1):
            window_promos = sum(promotions_per_period[window_start:window_start + window_size])
            if window_promos == 0:
                # Force a promotion in the middle of this window
                force_period_idx = window_start + window_size // 2
                force_period_start, force_period_end = periods[force_period_idx]

                # Find eligible employees (active, below max level)
                eligible_for_promo = employees[
                    (employees["separation_date"].isna())
                    & (employees["level"].apply(lambda x: int(x) < config.n_levels))
                    & (employees["hire_date"].apply(
                        lambda d: (d if isinstance(d, date) else pd.Timestamp(d).date()) <= force_period_end
                    ))
                ]
                eligible_ids = sorted(eligible_for_promo["employee_id"].tolist())

                if eligible_ids:
                    chosen_idx = int(rng.integers(0, len(eligible_ids)))
                    emp_id = eligible_ids[chosen_idx]
                    emp_row = employees[employees["employee_id"] == emp_id].iloc[0]
                    current_level = int(emp_row["level"])
                    new_level = current_level + 1

                    promo_date = _random_date_in_range(force_period_start, force_period_end, rng)

                    # Update employee level
                    emp_idx = employees[employees["employee_id"] == emp_id].index[0]
                    employees.at[emp_idx, "level"] = new_level

                    # Create forced PROMOTION event
                    event_id = f"EVT_{next_event_num:06d}"
                    next_event_num += 1
                    all_new_events.append({
                        "event_id": event_id,
                        "employee_id": emp_id,
                        "event_date": promo_date,
                        "event_type": "PROMOTION",
                        "from_department_id": None,
                        "to_department_id": None,
                        "from_level": current_level,
                        "to_level": new_level,
                    })
                    promotions_per_period[force_period_idx] += 1

    # --- Req 6.8: Ensure at least two periods differ by >= 2x hiring volume ---
    if len(hires_per_period) >= 2:
        max_hires = max(hires_per_period)
        min_hires = min(hires_per_period)
        # Check if the constraint is already satisfied
        has_2x_diff = any(
            hires_per_period[i] >= 2 * hires_per_period[j]
            for i in range(len(hires_per_period))
            for j in range(len(hires_per_period))
            if i != j and hires_per_period[j] > 0
        )
        # Also satisfied if any period has 0 hires and another has >= 2
        if not has_2x_diff:
            has_2x_diff = (
                min_hires == 0 and max_hires >= 2
            )

        if not has_2x_diff and len(periods) >= 2:
            # Force a burst of hires in a random period to create 2x difference
            burst_period_idx = int(rng.integers(0, len(periods)))
            burst_start, burst_end = periods[burst_period_idx]
            # Add enough hires to guarantee 2x difference
            burst_count = max(2, (max_hires + 1) * 2) if max_hires > 0 else 3

            for _ in range(burst_count):
                emp_id = f"EMP_{next_emp_num:06d}"
                next_emp_num += 1

                hire_date = _random_date_in_range(burst_start, burst_end, rng)

                n_levels = config.n_levels
                weights = np.array(
                    [n_levels - i + 1 for i in range(1, n_levels + 1)], dtype=float
                )
                weights /= weights.sum()
                level = int(rng.choice(np.arange(1, n_levels + 1), p=weights))

                dept_idx = int(rng.integers(0, len(dept_ids)))
                dept_id = dept_ids[dept_idx]

                new_employees.append({
                    "employee_id": emp_id,
                    "hire_date": hire_date,
                    "separation_date": None,
                    "separation_type": None,
                    "level": level,
                    "department_id": dept_id,
                })

                event_id = f"EVT_{next_event_num:06d}"
                next_event_num += 1
                all_new_events.append({
                    "event_id": event_id,
                    "employee_id": emp_id,
                    "event_date": hire_date,
                    "event_type": "HIRE",
                    "from_department_id": None,
                    "to_department_id": dept_id,
                    "from_level": None,
                    "to_level": level,
                })

            # Add burst employees to the main DataFrame
            burst_emps = new_employees[-burst_count:]
            burst_df = pd.DataFrame(burst_emps)
            employees = pd.concat([employees, burst_df], ignore_index=True)

    # =========================================================================
    # Build final DataFrames
    # =========================================================================

    # Combine initial events with new events
    if all_new_events:
        new_events_df = pd.DataFrame(all_new_events)
        all_events_df = pd.concat(
            [initial_events_df, new_events_df], ignore_index=True
        )
    else:
        all_events_df = initial_events_df.copy()

    # Sort final events by (employee_id, event_date)
    all_events_df = all_events_df.sort_values(
        ["employee_id", "event_date"]
    ).reset_index(drop=True)

    # Sort employees by employee_id
    employees = employees.sort_values("employee_id").reset_index(drop=True)

    return employees, all_events_df
