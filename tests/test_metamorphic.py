"""Property 7 & 9: Metamorphic properties."""
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hr_analytics_lib.generator import generate
from hr_analytics_lib.generator.config import GenerationConfig
from tests.conftest import valid_generation_config
from datetime import date

@given(config=valid_generation_config(clean_only=True))
@settings(max_examples=10, deadline=60_000)
def test_headcount_metamorphic(config):
    """Property 7: Double headcount → more employees."""
    # Skip if doubling headcount would make it invalid
    assume(config.headcount * 2 <= 500)
    config2 = GenerationConfig(
        headcount=config.headcount * 2,
        n_levels=config.n_levels,
        n_departments=config.n_departments,
        start_date=config.start_date,
        end_date=config.end_date,
        annual_separation_rate=config.annual_separation_rate,
        annual_hiring_rate=config.annual_hiring_rate,
        seed=config.seed,
    )
    ds1 = generate(config)
    ds2 = generate(config2)
    assert len(ds2.tables["employees"]) > len(ds1.tables["employees"])
