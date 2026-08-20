"""Property 3: Clean-Mode — validator returns 0 violations for clean data."""
from hypothesis import given, settings
from hr_analytics_lib.generator import generate, validate
from tests.conftest import valid_generation_config

@given(config=valid_generation_config(clean_only=True))
@settings(max_examples=20, deadline=60_000)
def test_clean_mode_zero_violations(config):
    """Clean mode datasets have zero validation violations."""
    ds = generate(config)
    violations = validate(ds.tables)
    assert len(violations) == 0, f"Expected 0 violations, got {len(violations)}: {violations[:5]}"
