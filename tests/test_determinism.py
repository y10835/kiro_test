"""Property 1: Determinism — same config+seed → identical output."""
from hypothesis import given, settings
from hr_analytics_lib.generator import generate
from tests.conftest import valid_generation_config

@given(config=valid_generation_config(clean_only=True))
@settings(max_examples=20, deadline=60_000)
def test_determinism(config):
    """Same config produces identical tables on two runs."""
    ds1 = generate(config)
    ds2 = generate(config)
    for name in ds1.tables:
        assert ds1.tables[name].equals(ds2.tables[name]), f"Table {name} differs between runs"
