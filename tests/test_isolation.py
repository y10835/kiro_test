"""Property 9: Seed Isolation — different seeds → different output."""
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hr_analytics_lib.generator import generate
from hr_analytics_lib.generator.config import GenerationConfig
from datetime import date

@given(
    seed1=st.integers(0, 2**32 - 1),
    seed2=st.integers(0, 2**32 - 1),
)
@settings(max_examples=20, deadline=60_000)
def test_seed_isolation(seed1, seed2):
    """Different seeds produce different datasets."""
    assume(seed1 != seed2)
    config1 = GenerationConfig(headcount=20, n_levels=3, n_departments=2, start_date=date(2022,1,1), end_date=date(2022,6,30), seed=seed1)
    config2 = GenerationConfig(headcount=20, n_levels=3, n_departments=2, start_date=date(2022,1,1), end_date=date(2022,6,30), seed=seed2)
    ds1 = generate(config1)
    ds2 = generate(config2)
    # At least one table should differ
    any_diff = False
    for name in ds1.tables:
        if not ds1.tables[name].equals(ds2.tables[name]):
            any_diff = True
            break
    assert any_diff, "Different seeds produced identical datasets"
