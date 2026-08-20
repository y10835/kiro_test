"""Stage 1 — Initial population generation.

Generates the initial set of employees who are active at the dataset start_date,
along with their corresponding HIRE employment events.

Invariants:
- Exactly `headcount` employees are produced.
- All employee_id values are unique (sequential format EMP_NNNNNN).
- Every employee has exactly one HIRE event.
- Levels are distributed as a pyramid (more employees at lower levels).
- Departments are distributed approximately evenly with RNG jitter.
- All employees have hire_date = start_date and no separation.
- Output is sorted by employee_id ascending.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def generate_initial_population(
    headcount: int,
    n_levels: int,
    departments_df: pd.DataFrame,
    start_date: date,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate initial employees and their HIRE events.

    Parameters
    ----------
    headcount : int
        Number of employees to generate.
    n_levels : int
        Number of organisational levels (1-indexed).
    departments_df : pd.DataFrame
        The departments table with department_id column.
    start_date : date
        The dataset start date; all employees are hired on this date.
    rng : np.random.Generator
        The random number generator for this stage.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (employees_df, hire_events_df)

    Invariants:
    - Exactly `headcount` employees produced.
    - All employee_ids are unique.
    - Every employee has exactly one HIRE event.
    - Levels are distributed as a pyramid (more at lower levels).
    - Departments are distributed approximately evenly.
    """
    # --- Employee IDs (sequential for determinism) ---
    employee_ids = [f"EMP_{i:06d}" for i in range(1, headcount + 1)]

    # --- Level assignment (pyramid distribution) ---
    # Level i gets weight (n_levels - i + 1), so level 1 is most populated.
    # Levels are 1-indexed: 1, 2, ..., n_levels.
    weights = np.array([n_levels - i + 1 for i in range(1, n_levels + 1)], dtype=float)
    weights /= weights.sum()

    # Use rng to assign levels based on pyramid probabilities.
    levels = rng.choice(
        np.arange(1, n_levels + 1),
        size=headcount,
        p=weights,
    )

    # --- Department assignment (approximately even with RNG jitter) ---
    department_ids_list = sorted(departments_df["department_id"].tolist())
    n_departments = len(department_ids_list)

    # Assign departments using uniform random selection across available departments.
    dept_indices = rng.integers(0, n_departments, size=headcount)
    departments = [department_ids_list[i] for i in dept_indices]

    # --- Build employees DataFrame ---
    employees_df = pd.DataFrame(
        {
            "employee_id": employee_ids,
            "hire_date": [start_date] * headcount,
            "separation_date": [None] * headcount,
            "separation_type": [None] * headcount,
            "level": levels,
            "department_id": departments,
        }
    )

    # Sort by employee_id ascending (sort key position 0 per schema).
    employees_df = employees_df.sort_values("employee_id").reset_index(drop=True)

    # --- Generate HIRE events ---
    event_ids = [f"EVT_{i:06d}" for i in range(1, headcount + 1)]

    hire_events_df = pd.DataFrame(
        {
            "event_id": event_ids,
            "employee_id": employees_df["employee_id"].tolist(),
            "event_date": [start_date] * headcount,
            "event_type": ["HIRE"] * headcount,
            "from_department_id": [None] * headcount,
            "to_department_id": employees_df["department_id"].tolist(),
            "from_level": [None] * headcount,
            "to_level": employees_df["level"].tolist(),
        }
    )

    # Sort by (employee_id, event_date) ascending (sort key positions 0, 1).
    hire_events_df = hire_events_df.sort_values(
        ["employee_id", "event_date"]
    ).reset_index(drop=True)

    return employees_df, hire_events_df
