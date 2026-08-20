# Requirements Document — Synthetic HR Data Generator

## Introduction

This specification defines the **Synthetic HR Data Generator**, the Week-1 foundation of `hr-analytics-lib`. The generator produces realistic, multi-table HR datasets — both clean and deliberately corrupted — that serve as ground-truth inputs for the 11 downstream workforce metrics (attrition rate, voluntary/involuntary separation, retention by cohort, tenure distribution, headcount flow, promotion velocity, span of control, compensation ratio, performance distribution, labour-cost allocation, and demand-supply gap).

The generator exists as a standalone, deterministic pipeline that:

1. Accepts a compact configuration describing organisational shape, temporal scope, and optional corruption parameters.
2. Produces a fixed-schema dataset of 7 interrelated tables plus metadata.
3. Optionally injects catalogued defects to test metric robustness.
4. Outputs an answer-key manifest so validators can programmatically verify defect detection.

All output is reproducible given an explicit seed, and the generator has **zero runtime dependencies** on the downstream metrics modules.

---

## Glossary

- **Generator**: The top-level module (`generator/`) responsible for synthesising HR datasets from a `GenerationConfig`.
- **Validator**: A module that checks a `GeneratedDataset` against the `Fixed_Schema` and structural-integrity invariants; returns a list of violations.
- **Injector**: A sub-module that applies deliberate defects to a clean `GeneratedDataset` according to configured `Corruption_Rate` values, recording every mutation in the `Defect_Manifest`.
- **Serializer**: A module that writes or reads a `GeneratedDataset` to/from disk (CSV canonical form, optional Parquet) or returns it as in-memory DataFrames.
- **GenerationConfig**: A validated, immutable configuration object specifying headcount, levels, departments, temporal range, seed, and optional corruption parameters.
- **Resolved_Seed**: A 128-bit integer derived either from an explicit user-supplied seed or from OS entropy; stored in `Run_Metadata` and sufficient to reproduce the full dataset.
- **GeneratedDataset**: The complete output artefact containing `Data_Tables`, `Defect_Manifest`, and `Run_Metadata`.
- **Data_Tables**: The collection of 7 pandas DataFrames conforming to the `Fixed_Schema`.
- **Fixed_Schema**: The authoritative column-name, dtype, nullability, and sort-key contract defined in `schema.py`.
- **Defect_Manifest**: A DataFrame listing every injected defect: table, row index, column, `Defect_Type`, original value, and mutated value.
- **Defect_Type**: One of exactly five catalogued mutation kinds: `NULL_INJECTION`, `DUPLICATE_KEY`, `ORPHAN_FK`, `DATE_CONTRADICTION`, `VALUE_OUT_OF_RANGE`.
- **Run_Metadata**: A dictionary capturing full provenance: library version, resolved seed, config hash, generation timestamp, table row counts, and per-`Defect_Type` injection counts.
- **Clean_Mode**: Generation with corruption disabled (`corruption_rate = 0.0`); output must pass the Validator with zero violations.
- **Corruption_Mode**: Generation with one or more `Defect_Type` rates > 0; output intentionally violates integrity constraints.
- **Eligible_Population**: The subset of records in a table that are valid candidates for a specific `Defect_Type` injection (e.g., only non-PK columns for `NULL_INJECTION`).
- **Corruption_Rate**: A float in (0.0, 1.0] specifying the fraction of the `Eligible_Population` to corrupt for a given `Defect_Type`.
- **Period**: A calendar month (`YYYY-MM`) representing the smallest temporal grain for headcount flow calculations.
- **Canonical_Form**: The deterministic CSV serialization rules (column order, sort key, date format, decimal precision, encoding, line endings) that guarantee byte-identical output for identical logical content.
- **Flow_Identity**: The accounting invariant: `opening + hires + transfers_in − separations − transfers_out = closing` for every grain and every `Period`.
- **Transfer**: An `employment_event` of type `TRANSFER` that simultaneously decrements one grain's headcount and increments another's within the same `Period`.

---

## Requirements

### Requirement 1: Reproducible Explicitly-Seeded Generation

**User Story:** As a data engineer, I want every generated dataset to be perfectly reproducible given the same seed, so that I can debug metrics against a stable fixture.

#### Acceptance Criteria

1. WHEN a `GenerationConfig` includes an explicit integer seed, THE Generator SHALL instantiate a `numpy.random.Generator` from `numpy.random.SeedSequence(seed)` as the sole source of randomness for the entire run.
2. WHEN the same `GenerationConfig` (including seed) is used on any OS/architecture, THE Generator SHALL produce byte-identical `Canonical_Form` CSV output.
3. WHEN no seed is provided in the `GenerationConfig`, THE Generator SHALL obtain a `Resolved_Seed` from OS entropy via `numpy.random.SeedSequence()` and record it in `Run_Metadata`.
4. THE Generator SHALL NOT read from or write to `numpy`'s global random state (`numpy.random.default_rng()` without explicit seed, `numpy.random.seed()`, or any legacy `RandomState`).
5. WHEN generation completes, THE Generator SHALL record the `Resolved_Seed` in `Run_Metadata` such that passing it back as the explicit seed reproduces the identical dataset.
6. THE Generator SHALL produce identical output regardless of Python dictionary insertion order by sorting all intermediate collections before sampling.
7. WHEN multiple tables are generated in sequence, THE Generator SHALL derive independent child `numpy.random.Generator` instances via `SeedSequence.spawn()` so that adding or removing a table does not alter randomness in unrelated tables.

---

### Requirement 2: Org Shape Parameters and Input Validation

**User Story:** As a data analyst, I want to configure the organisational shape (headcount, levels, departments, date range) via a simple config object, so that I can generate datasets matching my analysis scenarios.

#### Acceptance Criteria

1. THE GenerationConfig SHALL accept the following parameters: `headcount` (int), `n_levels` (int), `n_departments` (int), `start_date` (date), `end_date` (date), `annual_separation_rate` (float), `annual_hiring_rate` (float), `seed` (optional int), and `corruption_config` (optional dict mapping `Defect_Type` to `Corruption_Rate`).
2. IF `headcount` < 1, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "headcount must be ≥ 1".
3. IF `n_levels` < 1 or `n_levels` > 15, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "n_levels must be between 1 and 15".
4. IF `n_departments` < 1, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "n_departments must be ≥ 1".
5. IF `end_date` ≤ `start_date`, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "end_date must be after start_date".
6. IF `annual_separation_rate` < 0.0 or `annual_separation_rate` > 1.0, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "annual_separation_rate must be in [0.0, 1.0]".
7. IF `annual_hiring_rate` < 0.0 or `annual_hiring_rate` > 5.0, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "annual_hiring_rate must be in [0.0, 5.0]".
8. IF any `Corruption_Rate` value is ≤ 0.0 or > 1.0, THEN THE GenerationConfig SHALL raise a `ConfigError` with message containing "corruption_rate must be in (0.0, 1.0]".

---

### Requirement 3: Fixed Multi-Table Output Schema

**User Story:** As a metrics developer, I want the generator to produce a stable, well-defined schema across all tables, so that downstream code can rely on column names, types, and sort order.

#### Acceptance Criteria

1. THE Generator SHALL produce exactly 7 `Data_Tables`: `departments`, `employees`, `employment_events`, `assignments`, `compensation`, `performance_reviews`, and `org_periods`.
2. THE `departments` table SHALL contain columns: `department_id` (str, PK), `department_name` (str), `created_date` (date).
3. THE `employees` table SHALL contain columns: `employee_id` (str, PK), `hire_date` (date), `separation_date` (date, nullable), `separation_type` (str, nullable: "VOLUNTARY" | "INVOLUNTARY"), `level` (int), `department_id` (str, FK→departments).
4. THE `employment_events` table SHALL contain columns: `event_id` (str, PK), `employee_id` (str, FK→employees), `event_date` (date), `event_type` (str: "HIRE" | "SEPARATION" | "PROMOTION" | "TRANSFER"), `from_department_id` (str, nullable), `to_department_id` (str, nullable), `from_level` (int, nullable), `to_level` (int, nullable).
5. THE `assignments` table SHALL contain columns: `assignment_id` (str, PK), `employee_id` (str, FK→employees), `department_id` (str, FK→departments), `level` (int), `start_date` (date), `end_date` (date, nullable).
6. THE `compensation` table SHALL contain columns: `compensation_id` (str, PK), `employee_id` (str, FK→employees), `effective_date` (date), `annual_salary` (float), `currency` (str, always "USD").
7. THE `performance_reviews` table SHALL contain columns: `review_id` (str, PK), `employee_id` (str, FK→employees), `review_date` (date), `review_period_start` (date), `review_period_end` (date), `rating` (int, 1–5), `reviewer_employee_id` (str, nullable, FK→employees).
8. THE `org_periods` table SHALL contain columns: `period` (str, "YYYY-MM"), `grain_type` (str: "ORG" | "DEPARTMENT" | "LEVEL"), `grain_key` (str), `opening` (int), `hires` (int), `separations` (int), `transfers_in` (int), `transfers_out` (int), `closing` (int), `total_labor_cost` (float).
9. THE Generator SHALL store all monetary values (`annual_salary`, `total_labor_cost`) as floats rounded to 2 decimal places.
10. THE Generator SHALL sort each table by its designated sort key as defined in `schema.py` before output.

---

### Requirement 4: Clean-Mode Structural Integrity

**User Story:** As a test engineer, I want clean-mode output to satisfy all referential and temporal integrity constraints, so that I can use it as a ground-truth baseline.

#### Acceptance Criteria

1. WHILE in `Clean_Mode`, THE Generator SHALL produce unique values for every primary-key column across all rows in each table.
2. WHILE in `Clean_Mode`, THE Generator SHALL produce no NULL values in any non-nullable column as defined in the `Fixed_Schema`.
3. WHILE in `Clean_Mode`, THE Generator SHALL ensure every foreign-key value references an existing primary-key value in the target table.
4. WHILE in `Clean_Mode`, THE Generator SHALL produce exactly one `HIRE` event and at most one `SEPARATION` event per employee in `employment_events`.
5. WHILE in `Clean_Mode`, THE Generator SHALL ensure `assignments` intervals for the same employee are gap-free and non-overlapping (the `end_date` of one equals the `start_date` of the next).
6. WHILE in `Clean_Mode`, THE Generator SHALL ensure every employee's earliest `assignment.start_date` equals their `hire_date`.
7. WHILE in `Clean_Mode`, THE Generator SHALL ensure every employee's latest `assignment.end_date` IS NULL (still active) or equals their `separation_date`.
8. WHILE in `Clean_Mode`, THE Generator SHALL ensure `compensation.effective_date` ≥ the employee's `hire_date`.
9. WHILE in `Clean_Mode`, THE Generator SHALL ensure `performance_reviews.review_period_start` < `performance_reviews.review_period_end`.
10. WHILE in `Clean_Mode`, THE Generator SHALL ensure all `employment_events.event_date` values fall within `[start_date, end_date]` of the `GenerationConfig`.
11. WHEN the Validator is run against a `Clean_Mode` dataset, THE Validator SHALL return zero violations.

---

### Requirement 5: Clean-Mode Headcount Flow Identity

**User Story:** As a workforce planner, I want the generated data to satisfy the headcount flow accounting identity at every grain, so that I can validate my flow-based metrics.

#### Acceptance Criteria

1. WHILE in `Clean_Mode`, THE `org_periods` table SHALL satisfy the `Flow_Identity` (`opening + hires + transfers_in − separations − transfers_out = closing`) for every row.
2. WHILE in `Clean_Mode`, THE Generator SHALL compute `Flow_Identity` at three grains: `ORG` (whole organisation), `DEPARTMENT` (per department), and `LEVEL` (per level).
3. WHILE in `Clean_Mode`, THE Generator SHALL count a `Transfer` as both a `transfers_out` in the source grain and a `transfers_in` in the destination grain within the same `Period`.
4. WHILE in `Clean_Mode`, THE Generator SHALL ensure that for consecutive periods at the same grain, the `closing` of period *N* equals the `opening` of period *N+1* (period-chain continuity).
5. WHILE in `Clean_Mode`, THE Generator SHALL ensure that for each `Period`, the sum of `DEPARTMENT`-grain `closing` values equals the `ORG`-grain `closing` value (cross-grain consistency).
6. WHILE in `Clean_Mode`, THE `org_periods` table SHALL compute `total_labor_cost` as the sum of active `compensation.annual_salary / 12` for all employees in that grain during that `Period`.

---

### Requirement 6: Analytical Adequacy for 12-Metric Backlog

**User Story:** As a metrics developer, I want the synthetic data to contain sufficient variety and realistic distributions, so that all 12 planned metrics produce non-trivial, testable results.

#### Acceptance Criteria

1. THE Generator SHALL produce at least one `SEPARATION` event for every `Period` that has ≥ 10 active employees, ensuring attrition rate is always calculable.
2. THE Generator SHALL assign `separation_type` values with a configurable voluntary/involuntary split (default 70%/30%) so that vol/invol metrics are exercisable.
3. THE Generator SHALL ensure at least 3 distinct hire cohorts (employees sharing the same `hire_date` month) exist, enabling cohort-retention analysis.
4. THE Generator SHALL distribute employee tenure and levels such that no single level contains more than 60% of the total headcount at any `Period`.
5. THE Generator SHALL produce at least one `PROMOTION` event per 12-month window (when headcount ≥ 5 and `n_levels` ≥ 2), enabling promotion-velocity measurement.
6. THE Generator SHALL assign `annual_salary` values that increase monotonically with level within the same department at the same point in time (level *N+1* median ≥ level *N* median).
7. THE Generator SHALL produce `performance_reviews.rating` values with a distribution where no single rating accounts for more than 50% of reviews, enabling performance-distribution metrics.
8. THE Generator SHALL generate `HIRE` events distributed across periods so that at least two `Period` values have meaningfully different hiring volumes (≥ 2× difference), enabling demand-driver analysis.
9. THE Generator SHALL ensure that at least one employee spans the full date range from `start_date` to `end_date` without separation, providing a full-tenure cohort for retention analysis.

---

### Requirement 7: Deliberate Defect Injection

**User Story:** As a data-quality engineer, I want to inject known defects into generated datasets at controlled rates, so that I can verify my validation and cleaning pipelines detect them.

#### Acceptance Criteria

1. THE Injector SHALL support exactly 5 `Defect_Type` values: `NULL_INJECTION`, `DUPLICATE_KEY`, `ORPHAN_FK`, `DATE_CONTRADICTION`, `VALUE_OUT_OF_RANGE`.
2. WHEN `corruption_config` maps a `Defect_Type` to a `Corruption_Rate`, THE Injector SHALL inject defects into exactly `round(Corruption_Rate × |Eligible_Population|)` records for that type.
3. THE Injector SHALL define `Eligible_Population` per `Defect_Type`: `NULL_INJECTION` → non-PK, non-nullable columns; `DUPLICATE_KEY` → PK columns; `ORPHAN_FK` → FK columns; `DATE_CONTRADICTION` → date-pair columns where start < end; `VALUE_OUT_OF_RANGE` → numeric bounded columns.
4. IF `round(Corruption_Rate × |Eligible_Population|)` = 0 AND `|Eligible_Population|` > 0, THEN THE Injector SHALL inject exactly 1 defect (minimum-1 guarantee).
5. IF `|Eligible_Population|` = 0 for a given `Defect_Type`, THEN THE Injector SHALL skip that type and record zero injections in `Run_Metadata`.
6. THE Injector SHALL apply `Defect_Type` injections in a fixed, deterministic order: `NULL_INJECTION` → `DUPLICATE_KEY` → `ORPHAN_FK` → `DATE_CONTRADICTION` → `VALUE_OUT_OF_RANGE`.
7. THE Injector SHALL allow multiple defects to be applied to the same record (a record corrupted by `NULL_INJECTION` remains eligible for `DUPLICATE_KEY`).
8. WHEN selecting records from the `Eligible_Population`, THE Injector SHALL use skip-and-reselect if a candidate record has already been corrupted by the *same* `Defect_Type` in the *same* column, ensuring distinct corruption sites per type-column pair.
9. THE Injector SHALL implement each `Defect_Type` mutation as: `NULL_INJECTION` → set value to `None`/`NaN`; `DUPLICATE_KEY` → copy PK from another row; `ORPHAN_FK` → replace FK with a UUID not present in target table; `DATE_CONTRADICTION` → swap start/end dates; `VALUE_OUT_OF_RANGE` → multiply numeric value by 100.
10. THE Injector SHALL record every mutation in the `Defect_Manifest` with: table name, row index, column name, `Defect_Type`, original value, and mutated value.
11. WHEN injection is complete, THE Injector SHALL NOT alter the `Fixed_Schema` column set or dtypes (injected NULLs convert column dtype to nullable where needed, but no columns are added or removed).

---

### Requirement 8: Defect Manifest as Verification Answer Key

**User Story:** As a QA engineer, I want the defect manifest to serve as an exact answer key, so that I can assert my validator finds every injected defect and no false positives against it.

#### Acceptance Criteria

1. THE `Defect_Manifest` SHALL contain columns: `table` (str), `row_index` (int), `column` (str), `defect_type` (str), `original_value` (str), `mutated_value` (str).
2. WHEN a validator detects a violation at (`table`, `row_index`, `column`), THE Validator SHALL resolve it to a `Defect_Manifest` key of (`table`, `row_index`, `column`) for equality comparison.
3. WHEN comparing Validator output to the `Defect_Manifest`, THE comparison SHALL treat them as equal if and only if they contain the same set of (`table`, `row_index`, `column`, `defect_type`) tuples.
4. WHILE in `Clean_Mode`, THE Generator SHALL produce an empty `Defect_Manifest` (zero rows, correct schema).
5. THE `Run_Metadata` SHALL include a `defect_counts` dictionary mapping each `Defect_Type` to its injection count (0 in `Clean_Mode`).

---

### Requirement 9: Run Metadata

**User Story:** As a data engineer, I want each generated dataset to carry full provenance metadata, so that I can trace any output back to its exact generation parameters.

#### Acceptance Criteria

1. THE `Run_Metadata` SHALL include: `library_version` (str), `resolved_seed` (int), `config_hash` (str, SHA-256 of canonical JSON config), `generation_timestamp` (ISO-8601 UTC), `table_row_counts` (dict), and `defect_counts` (dict).
2. THE `Run_Metadata` SHALL be sufficient to reproduce the dataset: given `resolved_seed` and the same library version, re-generation SHALL produce byte-identical `Canonical_Form` output.
3. THE `Run_Metadata` SHALL NOT include the `Canonical_Form` output itself (no data duplication).
4. THE `generation_timestamp` SHALL be captured once at the start of generation and SHALL NOT affect any random draws or data content (determinism is seed-only).

---

### Requirement 10: In-Memory and File Output

**User Story:** As a developer, I want to access generated data both as in-memory DataFrames and as files on disk, so that I can use the generator in tests (in-memory) and in pipelines (file-based).

#### Acceptance Criteria

1. THE Serializer SHALL expose a `to_dataframes()` method returning a dictionary mapping table names to pandas DataFrames.
2. THE Serializer SHALL expose a `to_csv(directory: Path)` method that writes each table as a separate CSV file in `Canonical_Form` plus `metadata.json` and `defect_manifest.csv`.
3. WHERE Parquet support is enabled, THE Serializer SHALL expose a `to_parquet(directory: Path)` method writing each table as a `.parquet` file with matching schema.
4. WHEN a `GeneratedDataset` is serialized to CSV and then deserialized, THE resulting DataFrames SHALL be equal to the original in-memory DataFrames (round-trip fidelity).
5. IF the target directory already contains files from a previous run, THEN THE Serializer SHALL raise an `OutputExistsError` rather than overwriting.

---

### Requirement 11: Architectural Boundary and Determinism Constraints

**User Story:** As a library maintainer, I want strict module boundaries enforced automatically, so that the generator remains independently testable and the metrics layer has no hidden coupling.

#### Acceptance Criteria

1. THE Generator module (`generator/`) SHALL NOT import from the metrics module (`metrics/`) at any level.
2. THE only shared dependency between `generator/` and `metrics/` SHALL be `schema.py` located at the package root.
3. THE `schema.py` module SHALL export: table names, column definitions (name, dtype, nullable, sort_key), and the `Defect_Type` enum.
4. THE Generator codebase SHALL use type hints on all public function signatures and class attributes.
5. THE Generator codebase SHALL include module-level docstrings stating the invariants that module preserves.
6. THE repository SHALL include an automated boundary check (AST-based import analysis) that fails CI if `generator/` imports from `metrics/`.

---

### Requirement 12: Regression Stability

**User Story:** As a library consumer, I want stable output across library versions unless explicitly notified, so that my snapshot tests don't break on non-functional refactors.

#### Acceptance Criteria

1. WHEN the library is refactored without changing generation logic, THE Generator SHALL produce byte-identical `Canonical_Form` output for the same seed and config.
2. WHEN generation logic changes, THE library version SHALL be incremented and the changelog SHALL document the breaking seed contract.
3. WHILE in `Clean_Mode`, THE Validator guarantees from Requirement 4 SHALL remain satisfied across all versions.
4. THE Validator SHALL return zero violations on any `Clean_Mode` dataset generated by the same library version.
5. THE `schema.py` module SHALL expose `SCHEMA_VERSION` (str) and `DEFECT_TAXONOMY_VERSION` (str) for programmatic compatibility checks.

---

### Requirement 13: Property-Based Verification

**User Story:** As a test engineer, I want property-based tests that verify generator correctness across thousands of random configurations, so that edge-case bugs are caught before release.

#### Acceptance Criteria

1. THE test suite SHALL include a Hypothesis strategy that generates valid `GenerationConfig` instances with constrained ranges (headcount 1–500, levels 1–10, departments 1–20, date range 1–60 months).
2. FOR ALL valid `GenerationConfig` instances with an explicit seed, generating twice with the same config SHALL produce identical `Canonical_Form` output (Determinism property).
3. FOR ALL `GeneratedDataset` instances in `Clean_Mode`, serializing to CSV and deserializing SHALL produce DataFrames equal to the originals (Round-Trip property).
4. FOR ALL `GeneratedDataset` instances in `Clean_Mode`, THE Validator SHALL return zero violations (Clean-Mode property).
5. FOR ALL `GeneratedDataset` instances in `Clean_Mode`, THE `org_periods` SHALL satisfy `Flow_Identity` at every grain (model-based testing against the accounting equation).
6. FOR ALL `GeneratedDataset` instances in `Clean_Mode`, THE `org_periods` `Flow_Identity` SHALL hold at ORG, DEPARTMENT, and LEVEL grains simultaneously (Flow Identity property).
7. FOR ALL `GeneratedDataset` instances, running the Validator twice on the same dataset SHALL produce identical violation lists (Idempotence property).
8. FOR ALL valid `GenerationConfig` pairs where one has double the headcount, the generated dataset with larger headcount SHALL have more total rows in `employees` (Headcount Metamorphic property).
9. FOR ALL valid `GenerationConfig` instances in `Corruption_Mode`, THE number of Validator violations SHALL be ≥ the number of `Defect_Manifest` entries (Corruption Metamorphic property).
10. FOR ALL pairs of `GenerationConfig` instances differing only in seed, THE generated datasets SHALL differ in at least one data value (Seed Isolation property).
11. FOR ALL invalid `GenerationConfig` inputs (violating Requirement 2 bounds), construction SHALL raise `ConfigError` (Invalid Config Rejection property).
12. THE test suite SHALL include at least 3 example-based tests with fixed seeds that assert exact row counts and specific cell values, serving as regression anchors (Example-Based Adequacy).

---

## Open Questions

| ID | Question | Provisional Resolution |
|----|----------|----------------------|
| [P1] | Should the generator support custom department names or only auto-generated ones? | Auto-generated (`DEPT_001`, `DEPT_002`, …); custom names deferred to v2. |
| [P2] | What is the maximum headcount the generator must handle performantly? | 10,000 employees; performance target < 30 seconds on a single core. |
| [P3] | Should transfers be cross-department only, or also cross-level? | Cross-department only in v1; level changes are modelled as `PROMOTION` events. |
| [P4] | Should the `performance_reviews` table support multiple review cycles per year? | Yes, one review per employee per 6-month window (semi-annual). |
| [P5] | What currency assumptions apply to compensation? | Single-currency (USD) in v1; multi-currency deferred to v2. |
| [P6] | Should the Serializer support streaming/chunked output for large datasets? | No; full materialisation is acceptable for ≤ 10,000 headcount. |
| [P7] | How should the generator handle leap years and month-boundary edge cases? | Use `pandas.Timestamp` arithmetic; periods are always full calendar months. |
| [P8] | Should the defect injector support user-defined custom `Defect_Type` extensions? | No; the taxonomy is closed in v1. |
| [P9] | What is the minimum Python version? | Python 3.12+ only. |
| [P10] | Should `schema.py` include validation logic or only declarations? | Declarations only; validation lives in the Validator module. |
