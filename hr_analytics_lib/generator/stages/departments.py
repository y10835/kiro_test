"""Stage 0 — Department generation.

Generates the departments table with deterministic IDs and names.
All departments are created at the dataset start_date.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def generate_departments(
    n_departments: int,
    start_date: date,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate the departments table.

    Invariants:
    - Exactly n_departments rows produced.
    - All department_id values are unique.
    - created_date equals start_date for all rows.
    - Output is sorted by department_id (sort key position 0).
    """
    # Advance RNG state to maintain stream contract even though generation is deterministic.
    _ = rng.integers(0, 1)

    department_ids = [f"DEPT_{i:03d}" for i in range(1, n_departments + 1)]
    department_names = [f"Department {i}" for i in range(1, n_departments + 1)]
    created_dates = [start_date] * n_departments

    df = pd.DataFrame(
        {
            "department_id": department_ids,
            "department_name": department_names,
            "created_date": created_dates,
        }
    )

    # Sort by department_id ascending (sort key position 0 per schema).
    df = df.sort_values("department_id").reset_index(drop=True)

    return df
