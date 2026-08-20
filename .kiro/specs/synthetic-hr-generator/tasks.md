# Implementation Tasks — Synthetic HR Data Generator

## Task 1: Project Structure + schema.py

- [ ] 1.1 Create package layout: `hr_analytics_lib/`, `hr_analytics_lib/generator/`, `hr_analytics_lib/generator/stages/`, `hr_analytics_lib/metrics/` (empty), `tests/`
- [ ] 1.2 Create `pyproject.toml` with dependencies: `pandas>=2.1`, `numpy>=1.26`, `pytest>=7.4`, `hypothesis>=6.90`, `pyarrow>=14.0` (optional)
- [ ] 1.3 Implement `schema.py` at package root: `SCHEMA_VERSION`, `DEFECT_TAXONOMY_VERSION`, `DefectType` enum (5 values), `TableSchema` dataclass, `TABLES` dict with all 7 table definitions (columns, dtypes, nullable flags, sort keys)
- [ ] 1.4 Implement `defect_manifest` schema in `schema.py` (6 columns: table, row_index, column, defect_type, original_value, mutated_value)
- [ ] 1.5 Add `ConfigError` and `OutputExistsError` exception classes in `hr_analytics_lib/exceptions.py`

## Task 2: GenerationConfig + Validation

- [ ] 2.1 Implement `GenerationConfig` dataclass in `generator/config.py` with all parameters (headcount, n_levels, n_departments, start_date, end_date, annual_separation_rate, annual_hiring_rate, seed, corruption_config)
- [ ] 2.2 Implement `__post_init__` validation: headcount ≥ 1, n_levels ∈ [1,15], n_departments ≥ 1, end_date > start_date, rates in bounds, corruption_rate in (0.0, 1.0]
- [ ] 2.3 Implement `config_hash` property (SHA-256 of canonical JSON representation)
- [ ] 2.4 Implement `resolved_seed` property (explicit seed or OS entropy via SeedSequence)
- [ ] 2.5 Write unit tests for all 8 validation error cases (Req 2.2–2.8)

## Task 3: Checkpoint — Schema + Config

- [ ] 3.1 Verify `schema.py` imports cleanly from both `generator/` and `metrics/` packages
- [ ] 3.2 Verify all `ConfigError` messages match requirement text exactly
- [ ] 3.3 Run `pytest tests/test_config.py` — all pass

## Task 4: Generation Pipeline

- [ ] 4.1 Implement `_create_generators(resolved_seed)` in `generator/pipeline.py` — SeedSequence.spawn(8) creating named RNG streams
- [ ] 4.2 Implement Stage 0: `stages/departments.py` — generate DEPT_001..DEPT_N, created_date = start_date
- [ ] 4.3 Implement Stage 1: `stages/population.py` — generate initial employees, distribute across departments/levels (pyramid), assign UUIDs
- [ ] 4.4 Implement Stage 2: `stages/simulation.py` — period-by-period event generation (separations, hires, transfers, promotions) with analytical adequacy constraints (Req 6)
- [ ] 4.5 Implement Stage 3: `stages/assignments.py` — gap-free assignment chains from events, enforce start/end alignment with hire/separation dates
- [ ] 4.6 Implement Stage 4: `stages/compensation.py` — initial salary by level, promotion bumps, merit increases, monotonic ordering, 2-decimal rounding
- [ ] 4.7 Implement Stage 5: `stages/reviews.py` — semi-annual reviews, 1–5 rating distribution (no single rating >50%), reviewer assignment
- [ ] 4.8 Implement Stage 6: `stages/org_periods.py` — compute flow identity at ORG/DEPARTMENT/LEVEL grains, period-chain continuity, cross-grain consistency, total_labor_cost
- [ ] 4.9 Implement orchestrator `generate()` in `generator/pipeline.py` — wire all stages, build GeneratedDataset, attach metadata
- [ ] 4.10 Implement `Run_Metadata` construction: library_version, resolved_seed, config_hash, generation_timestamp, table_row_counts, defect_counts

## Task 5: Checkpoint — Pipeline Clean-Mode

- [ ] 5.1 Generate dataset with seed=42, headcount=50, 12 months — verify all 7 tables populated
- [ ] 5.2 Verify flow identity holds on all org_periods rows
- [ ] 5.3 Verify no NULL in non-nullable columns, all FKs resolve, PK unique
- [ ] 5.4 Verify analytical adequacy: separations exist, multiple cohorts, promotions present

## Task 6: Defect Injector

- [ ] 6.1 Implement `compute_eligible_population(dataset, defect_type)` for all 5 types
- [ ] 6.2 Implement `sample_with_skip_reselect(eligible, count, rng, defect_type)` — skip same-type same-column duplicates
- [ ] 6.3 Implement mutation functions: NULL_INJECTION (→None), DUPLICATE_KEY (copy PK), ORPHAN_FK (random UUID), DATE_CONTRADICTION (swap dates), VALUE_OUT_OF_RANGE (×100)
- [ ] 6.4 Implement fixed-order injection loop in `inject_defects()` — iterate DefectType enum order
- [ ] 6.5 Implement min-1 guarantee (`max(1, round(rate × eligible))`) and empty-eligible skip
- [ ] 6.6 Implement manifest DataFrame construction from mutation records
- [ ] 6.7 Write unit tests: verify exact injection counts, manifest completeness, schema preservation

## Task 7: Validator

- [ ] 7.1 Implement schema compliance check: column names, dtypes, nullability per schema.py
- [ ] 7.2 Implement PK uniqueness check across all tables
- [ ] 7.3 Implement FK referential integrity check
- [ ] 7.4 Implement temporal ordering checks (date pairs, assignment gaps, event date bounds)
- [ ] 7.5 Implement business-rule checks (single HIRE/SEPARATION, flow identity, boundary values)
- [ ] 7.6 Implement `Violation` dataclass and normalization to `(table, row_index, column, violation_type)`
- [ ] 7.7 Implement manifest comparison utility (set equality of violation tuples vs manifest tuples)
- [ ] 7.8 Write unit tests: clean dataset → 0 violations, corrupted dataset → violations match manifest

## Task 8: Serializer

- [ ] 8.1 Implement `to_dataframes(dataset)` → `dict[str, pd.DataFrame]`
- [ ] 8.2 Implement `to_csv(dataset, directory)` with Canonical_Form (10 rules: column order, sort, date format, float precision, NULL as empty, RFC 4180 quoting, UTF-8, LF, header, trailing newline)
- [ ] 8.3 Implement `from_csv(directory)` → `GeneratedDataset` (deserialization with schema-aware dtype parsing)
- [ ] 8.4 Implement `OutputExistsError` guard (raise if directory non-empty)
- [ ] 8.5 Implement `to_parquet(dataset, directory)` (optional, pyarrow-backed)
- [ ] 8.6 Write unit tests: round-trip CSV equality, OutputExistsError on non-empty dir

## Task 9: Checkpoint — Full Pipeline with Injection

- [ ] 9.1 Generate corrupted dataset (seed=42, all 5 defect types at 5% rate)
- [ ] 9.2 Verify manifest row count matches expected injection counts
- [ ] 9.3 Verify validator violations ⊇ manifest entries
- [ ] 9.4 Verify CSV round-trip on corrupted dataset preserves all data including NULLs

## Task 10: Public API + Property Tests (Core Properties)

- [ ] 10.1 Implement public `__init__.py` API: `generate()`, `validate()`, `GenerationConfig`, `GeneratedDataset`, `to_csv()`, `to_dataframes()`
- [ ] 10.2 Write Property 1 test (Determinism): same config+seed → byte-identical CSV (Hypothesis, `valid_generation_config` strategy)
- [ ] 10.3 Write Property 3 test (Clean-Mode): ∀ valid config → validator returns 0 violations
- [ ] 10.4 Write Property 5 test (Flow Identity): ∀ clean dataset → flow identity holds at all grains
- [ ] 10.5 Write Property 7 test (Headcount Metamorphic): double headcount → more employee rows
- [ ] 10.6 Write Property 9 test (Seed Isolation): different seeds → different outputs

## Task 11: Checkpoint — Property Tests Green

- [ ] 11.1 Run `pytest tests/test_determinism.py tests/test_clean_mode.py tests/test_metamorphic.py tests/test_isolation.py` — all pass
- [ ] 11.2 Verify Hypothesis found no counterexamples across 200+ examples per property
- [ ] 11.3 Address any shrunk failing cases

## Task 12: Hypothesis Strategies + Example-Based + Boundary Tests

- [ ] 12.1 Implement `conftest.py` with shared `valid_generation_config` and `invalid_generation_config` Hypothesis strategies
- [ ] 12.2 Write Property 2 test (Round-Trip): serialize CSV → deserialize → DataFrame equality
- [ ] 12.3 Write Property 4 test (Model-Based): org_periods satisfies accounting equation row-by-row
- [ ] 12.4 Write Property 6 test (Idempotence): validate(dataset) == validate(dataset) (two calls identical)
- [ ] 12.5 Write Property 8 test (Corruption Metamorphic): |violations| ≥ |manifest entries|
- [ ] 12.6 Write Property 10 test (Invalid Config Rejection): invalid params → ConfigError
- [ ] 12.7 Write 3 example-based regression tests with fixed seeds (seed=42/50emp, seed=123/100emp, seed=7/minimal)
- [ ] 12.8 Implement `tools/check_boundaries.py` — AST-based import analysis
- [ ] 12.9 Write `test_boundary.py` that invokes the boundary checker and asserts exit code 0
- [ ] 12.10 Add boundary check to `pyproject.toml` scripts and CI configuration

## Task 13: Final Checkpoint

- [ ] 13.1 Run full test suite: `pytest tests/ --run` — all green
- [ ] 13.2 Verify schema.py exposes SCHEMA_VERSION and DEFECT_TAXONOMY_VERSION
- [ ] 13.3 Verify `generator/` has zero imports from `metrics/` (boundary check passes)
- [ ] 13.4 Verify all public functions have type hints and modules have invariant docstrings
- [ ] 13.5 Generate final reference dataset (seed=42, headcount=100, 24 months, clean mode) and store as regression fixture

---

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "Foundation: project structure, schema, exceptions"
    },
    {
      "wave": 2,
      "tasks": ["2"],
      "description": "Configuration with validation",
      "depends_on": ["1"]
    },
    {
      "wave": 3,
      "tasks": ["3"],
      "description": "Checkpoint: schema + config verified",
      "depends_on": ["2"]
    },
    {
      "wave": 4,
      "tasks": ["4"],
      "description": "Generation pipeline (all 7 stages + orchestrator)",
      "depends_on": ["3"]
    },
    {
      "wave": 5,
      "tasks": ["5"],
      "description": "Checkpoint: pipeline clean-mode verified",
      "depends_on": ["4"]
    },
    {
      "wave": 6,
      "tasks": ["6", "7", "8"],
      "description": "Injector, Validator, Serializer (parallelizable)",
      "depends_on": ["5"]
    },
    {
      "wave": 7,
      "tasks": ["9"],
      "description": "Checkpoint: full pipeline with injection verified",
      "depends_on": ["6", "7", "8"]
    },
    {
      "wave": 8,
      "tasks": ["10"],
      "description": "Public API + core property tests",
      "depends_on": ["9"]
    },
    {
      "wave": 9,
      "tasks": ["11"],
      "description": "Checkpoint: property tests green",
      "depends_on": ["10"]
    },
    {
      "wave": 10,
      "tasks": ["12"],
      "description": "Remaining tests: strategies, examples, boundary",
      "depends_on": ["11"]
    },
    {
      "wave": 11,
      "tasks": ["13"],
      "description": "Final checkpoint: full suite green, all constraints met",
      "depends_on": ["12"]
    }
  ]
}
```

---

## Notes

- **Python 3.12+** — use modern type syntax (`type` statements, `X | Y` unions) throughout
- **Dependencies**: pandas ≥ 2.1, numpy ≥ 1.26, hypothesis ≥ 6.90, pytest ≥ 7.4, pyarrow ≥ 14.0 (optional)
- **Boundary rule**: `generator/` must NEVER import from `metrics/`. Only `schema.py` is shared.
- **Determinism priority**: All randomness flows from SeedSequence.spawn(8). No global state. Sort before sample.
- **Checkpoints** (Tasks 3, 5, 9, 11, 13) are verification gates — do not proceed past a checkpoint with failures.
- **Property tests** use Hypothesis with `@settings(max_examples=200)` for CI, `@settings(max_examples=50)` for local dev.
- **Canonical_Form** CSV rules must be followed exactly — byte-identical output is the determinism contract.
