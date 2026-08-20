"""Generation pipeline orchestrator.

Invariants:
- All randomness flows from a single SeedSequence, spawned into 8 independent child streams.
- Stream assignment is by FIXED POSITIONAL INDEX, not by dict key order (Req 1.7).
- No module-level or global random state is accessed (Req 1.4).
- Adding/removing a pipeline stage does not alter randomness in other stages (Req 1.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from numpy.random import SeedSequence

from hr_analytics_lib.generator.config import GenerationConfig
from hr_analytics_lib.schema import DefectType, SCHEMA_VERSION


# Fixed stage order — positions are permanent; new stages append only.
_STAGE_NAMES: tuple[str, ...] = (
    "departments",
    "employees",
    "events",
    "assignments",
    "compensation",
    "reviews",
    "org_periods",
    "injector",
)


def _create_generators(resolved_seed: int) -> dict[str, np.random.Generator]:
    """Spawn 8 independent RNG streams from a single resolved seed.

    Each pipeline stage gets its own child Generator so that:
    - Stages are independent: draws in one stage don't affect another.
    - Order is fixed by position, not by dict insertion order.
    - The resolved_seed fully determines all outputs.

    Parameters
    ----------
    resolved_seed : int
        The resolved seed (either user-supplied or drawn from OS entropy).

    Returns
    -------
    dict[str, np.random.Generator]
        Mapping of stage name → independent Generator instance.
    """
    root_seq = SeedSequence(resolved_seed)
    child_seqs = root_seq.spawn(len(_STAGE_NAMES))
    return {
        name: np.random.default_rng(seq)
        for name, seq in zip(_STAGE_NAMES, child_seqs)
    }



@dataclass(frozen=True)
class RunMetadata:
    """Provenance metadata for a generation run.

    Invariants:
    - resolved_seed + library_version is sufficient to reproduce the dataset.
    - generation_timestamp does not affect data content (determinism is seed-only).
    """

    library_version: str
    resolved_seed: int
    config_hash: str
    generation_timestamp: str  # ISO-8601 UTC
    table_row_counts: dict[str, int]
    defect_counts: dict[str, int]


@dataclass(frozen=True)
class GeneratedDataset:
    """Complete result of a generation run.

    Contains 7 Data_Tables, the Defect_Manifest, and Run_Metadata.
    """

    tables: dict[str, pd.DataFrame]
    defect_manifest: pd.DataFrame
    metadata: RunMetadata


def generate(config: GenerationConfig) -> GeneratedDataset:
    """Generate a complete synthetic HR dataset.

    This is the public entry point. It orchestrates all pipeline stages:
    1. Resolve seed
    2. Create RNG streams
    3. Run stages 0–6 (clean generation)
    4. Inject defects if corruption mode
    5. Build metadata
    6. Return GeneratedDataset

    Parameters
    ----------
    config : GenerationConfig
        Validated, immutable configuration.

    Returns
    -------
    GeneratedDataset
        The complete dataset with all tables, manifest, and metadata.

    Invariants:
    - Deterministic: same config (including seed) → same output.
    - Seed-isolated: unaffected by process-global random state.
    - Clean-mode guarantee: when all corruption rates are zero,
      the Validator reports zero violations.

    Raises
    ------
    ConfigError
        If config is invalid (but since GenerationConfig validates on construction,
        this should only happen if called with an unvalidated config object).
    """
    # Capture timestamp BEFORE any computation (does not affect randomness per Req 9.4)
    generation_timestamp = datetime.now(timezone.utc).isoformat()

    # 1. Resolve seed
    resolved_seed = config.resolved_seed

    # 2. Create independent RNG streams
    rngs = _create_generators(resolved_seed)

    # 3. Stage 0: Departments
    from hr_analytics_lib.generator.stages.departments import generate_departments

    departments_df = generate_departments(
        config.n_departments, config.start_date, rngs["departments"]
    )

    # 4. Stage 1: Initial Population
    from hr_analytics_lib.generator.stages.population import generate_initial_population

    employees_df, initial_events_df = generate_initial_population(
        config.headcount, config.n_levels, departments_df,
        config.start_date, rngs["employees"]
    )

    # 5. Stage 2: Period Simulation
    from hr_analytics_lib.generator.stages.simulation import simulate_periods

    employees_df, events_df = simulate_periods(
        employees_df, initial_events_df, config, departments_df, rngs["events"]
    )

    # 6. Stage 3: Assignments
    from hr_analytics_lib.generator.stages.assignments import build_assignments

    assignments_df = build_assignments(employees_df, events_df, rngs["assignments"])

    # 7. Stage 4: Compensation
    from hr_analytics_lib.generator.stages.compensation import build_compensation

    compensation_df = build_compensation(
        employees_df, events_df, assignments_df, rngs["compensation"]
    )

    # 8. Stage 5: Performance Reviews
    from hr_analytics_lib.generator.stages.reviews import generate_reviews

    reviews_df = generate_reviews(employees_df, config, rngs["reviews"])

    # 9. Stage 6: Org Periods
    from hr_analytics_lib.generator.stages.org_periods import aggregate_org_periods

    org_periods_df = aggregate_org_periods(
        employees_df, events_df, compensation_df, config, rngs["org_periods"]
    )

    # 10. Build tables dict
    tables = {
        "departments": departments_df,
        "employees": employees_df,
        "employment_events": events_df,
        "assignments": assignments_df,
        "compensation": compensation_df,
        "performance_reviews": reviews_df,
        "org_periods": org_periods_df,
    }

    # 11. Defect injection (if corruption mode)
    defect_manifest = pd.DataFrame(
        columns=["table", "row_index", "column", "defect_type", "original_value", "mutated_value"]
    )
    defect_counts: dict[str, int] = {dt.value: 0 for dt in DefectType}

    # TODO: Task 6 will implement injection here
    # if config.corruption_config:
    #     tables, defect_manifest = inject_defects(tables, config, rngs["injector"])

    # 12. Build metadata
    table_row_counts = {name: len(df) for name, df in tables.items()}

    metadata = RunMetadata(
        library_version="0.1.0",
        resolved_seed=resolved_seed,
        config_hash=config.config_hash,
        generation_timestamp=generation_timestamp,
        table_row_counts=table_row_counts,
        defect_counts=defect_counts,
    )

    return GeneratedDataset(
        tables=tables,
        defect_manifest=defect_manifest,
        metadata=metadata,
    )
