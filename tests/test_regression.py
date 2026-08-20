"""Example-based regression tests with fixed seeds."""
from datetime import date
from hr_analytics_lib.generator import generate, GenerationConfig

def test_seed_42_headcount_50():
    """Exact output for seed=42, headcount=50, 12 months."""
    config = GenerationConfig(headcount=50, n_levels=5, n_departments=3, start_date=date(2022,1,1), end_date=date(2022,12,31), seed=42)
    ds = generate(config)
    assert len(ds.tables["employees"]) >= 50  # At least initial headcount
    assert len(ds.tables["departments"]) == 3
    assert ds.metadata.resolved_seed == 42
    assert ds.metadata.library_version == "0.1.0"

def test_seed_123_headcount_100():
    """Exact output for seed=123, headcount=100, 24 months."""
    config = GenerationConfig(headcount=100, n_levels=5, n_departments=5, start_date=date(2022,1,1), end_date=date(2023,12,31), seed=123)
    ds = generate(config)
    assert len(ds.tables["employees"]) >= 100
    assert len(ds.tables["departments"]) == 5

def test_seed_7_minimal():
    """Minimal config: headcount=5, 1 level, 1 dept, 2 months."""
    config = GenerationConfig(headcount=5, n_levels=1, n_departments=1, start_date=date(2022,1,1), end_date=date(2022,2,28), seed=7)
    ds = generate(config)
    assert len(ds.tables["employees"]) >= 5
    assert len(ds.tables["departments"]) == 1
    # Clean mode: empty manifest
    assert len(ds.defect_manifest) == 0
