"""Stage 5 — Generate performance reviews.

Produces semi-annual performance review records for employees who are active
during each review window.

Invariants:
- One review per employee per 6-month window (per [P4]).
- Only active employees (not separated before review period end) receive reviews.
- Rating distribution: 1–5 scale, no single rating > 50% (Req 6.7).
- review_period_start < review_period_end always.
- reviewer_employee_id: random active employee at higher level, or None if no
  higher level exists.
- Output sorted by (employee_id, review_date).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from hr_analytics_lib.generator.config import GenerationConfig


def _generate_review_windows(
    start_date: date, end_date: date
) -> list[tuple[date, date]]:
    """Generate semi-annual review windows within the date range.

    Windows are aligned to calendar half-years:
    - H1: Jan 1 – Jun 30
    - H2: Jul 1 – Dec 31

    The first window starts at the beginning of the half that contains start_date,
    clamped to start_date. The last window ends at end_date or the natural half-year
    boundary, whichever is earlier.

    Parameters
    ----------
    start_date : date
        Dataset start date.
    end_date : date
        Dataset end date.

    Returns
    -------
    list[tuple[date, date]]
        List of (window_start, window_end) tuples.
    """
    windows: list[tuple[date, date]] = []

    # Determine the first half-year boundary at or after start_date
    current_year = start_date.year
    # Determine which half start_date falls in
    if start_date.month <= 6:
        window_start = date(current_year, 1, 1)
        window_end = date(current_year, 6, 30)
    else:
        window_start = date(current_year, 7, 1)
        window_end = date(current_year, 12, 31)

    # Clamp window_start to start_date if start_date is after the natural boundary
    if window_start < start_date:
        window_start = start_date

    while window_start <= end_date:
        # Clamp window_end to end_date
        actual_end = min(window_end, end_date)

        # Only include the window if it has positive duration
        if actual_end > window_start:
            windows.append((window_start, actual_end))

        # Move to next half-year
        if window_end.month == 6:
            # Next is H2 of same year
            window_start = date(window_end.year, 7, 1)
            window_end = date(window_end.year, 12, 31)
        else:
            # Next is H1 of next year
            window_start = date(window_end.year + 1, 1, 1)
            window_end = date(window_end.year + 1, 6, 30)

    return windows


def generate_reviews(
    employees_df: pd.DataFrame,
    config: GenerationConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate semi-annual performance reviews for active employees.

    Parameters
    ----------
    employees_df : pd.DataFrame
        The employees table with columns: employee_id, hire_date,
        separation_date, separation_type, level, department_id.
    config : GenerationConfig
        The generation configuration (provides start_date and end_date).
    rng : np.random.Generator
        Random number generator for this stage.

    Returns
    -------
    pd.DataFrame
        Performance reviews table with columns: review_id, employee_id,
        review_date, review_period_start, review_period_end, rating,
        reviewer_employee_id.

    Invariants:
    - One review per employee per 6-month window (per [P4]).
    - Only active employees (not separated before review period end) receive reviews.
    - Rating distribution: 1–5 scale, no single rating > 50% (Req 6.7).
    - review_period_start < review_period_end always.
    - reviewer_employee_id: random active employee at higher level, or None if no higher level exists.
    - Output sorted by (employee_id, review_date).
    """
    windows = _generate_review_windows(config.start_date, config.end_date)

    if not windows:
        # Return empty DataFrame with correct columns
        return pd.DataFrame(
            columns=[
                "review_id",
                "employee_id",
                "review_date",
                "review_period_start",
                "review_period_end",
                "rating",
                "reviewer_employee_id",
            ]
        )

    # Rating distribution: no single rating > 50% (Req 6.7)
    # Use a reasonable approximation: [0.10, 0.20, 0.35, 0.25, 0.10]
    rating_probs = [0.10, 0.20, 0.35, 0.25, 0.10]
    rating_values = [1, 2, 3, 4, 5]

    reviews: list[dict] = []
    review_counter = 0

    for window_start, window_end in windows:
        # Identify active employees for this window:
        # - hire_date < window_end (hired before the window ends)
        # - separation_date is None OR separation_date >= window_end
        #   (not separated before the review period ends)
        active_mask = employees_df["hire_date"].apply(
            lambda d: (d if isinstance(d, date) else pd.Timestamp(d).date()) < window_end
        )

        sep_mask = employees_df["separation_date"].apply(
            lambda d: d is None or (pd.isna(d) if not isinstance(d, date) else False)
            or (isinstance(d, date) and d >= window_end)
            or (d is not None and not isinstance(d, date) and pd.notna(d)
                and pd.Timestamp(d).date() >= window_end)
        )

        active_employees = employees_df[active_mask & sep_mask].copy()

        if active_employees.empty:
            continue

        # Sort active employees for determinism
        active_employees = active_employees.sort_values("employee_id").reset_index(drop=True)

        n_active = len(active_employees)

        # Generate ratings for all active employees in this window
        ratings = rng.choice(rating_values, size=n_active, p=rating_probs)

        # For each active employee, find a reviewer (higher level, active employee)
        # Pre-compute level groups for reviewer assignment
        active_ids = active_employees["employee_id"].tolist()
        active_levels = active_employees["level"].apply(
            lambda x: int(x) if x is not None else 1
        ).tolist()

        # Build mapping of level -> list of employee_ids at that level
        level_to_employees: dict[int, list[str]] = {}
        for emp_id, emp_level in zip(active_ids, active_levels):
            level_to_employees.setdefault(emp_level, []).append(emp_id)

        max_level = max(active_levels) if active_levels else 1

        for i, (_, emp_row) in enumerate(active_employees.iterrows()):
            review_counter += 1
            review_id = f"REV_{review_counter:06d}"
            emp_id = emp_row["employee_id"]
            emp_level = int(emp_row["level"]) if emp_row["level"] is not None else 1

            # Reviewer: random active employee at a higher level, or None
            reviewer_id = None
            if emp_level < max_level:
                # Collect all employees at levels strictly above this one
                higher_level_employees: list[str] = []
                for lvl in range(emp_level + 1, max_level + 1):
                    if lvl in level_to_employees:
                        higher_level_employees.extend(level_to_employees[lvl])

                # Exclude the employee themselves (shouldn't be there anyway, but safe)
                higher_level_employees = [
                    eid for eid in higher_level_employees if eid != emp_id
                ]

                if higher_level_employees:
                    # Sort for determinism then pick random
                    higher_level_employees.sort()
                    chosen_idx = int(rng.integers(0, len(higher_level_employees)))
                    reviewer_id = higher_level_employees[chosen_idx]

            reviews.append({
                "review_id": review_id,
                "employee_id": emp_id,
                "review_date": window_end,
                "review_period_start": window_start,
                "review_period_end": window_end,
                "rating": int(ratings[i]),
                "reviewer_employee_id": reviewer_id,
            })

    # Build DataFrame
    if not reviews:
        return pd.DataFrame(
            columns=[
                "review_id",
                "employee_id",
                "review_date",
                "review_period_start",
                "review_period_end",
                "rating",
                "reviewer_employee_id",
            ]
        )

    reviews_df = pd.DataFrame(reviews)

    # Sort by (employee_id, review_date) ascending (sort key positions 0, 1 per schema)
    reviews_df = reviews_df.sort_values(
        ["employee_id", "review_date"]
    ).reset_index(drop=True)

    return reviews_df
