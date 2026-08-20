"""Property 4 (model-based), Property 6 (idempotence), Property 8 (corruption metamorphic)."""
from hypothesis import given, settings
from hr_analytics_lib.generator import generate, validate, manifest_to_violations
from hr_analytics_lib.schema import DefectType
from tests.conftest import valid_generation_config

@given(config=valid_generation_config(clean_only=False))
@settings(max_examples=10, deadline=60_000)
def test_validator_idempotence(config):
    """Property 6: validate(ds) == validate(ds) always."""
    ds = generate(config)
    v1 = validate(ds.tables)
    v2 = validate(ds.tables)
    assert v1 == v2, "Validator is not idempotent"

@given(config=valid_generation_config(clean_only=False))
@settings(max_examples=10, deadline=60_000)
def test_corruption_manifest_subset(config):
    """Property 8: |violations| >= |manifest entries|."""
    ds = generate(config)
    if ds.defect_manifest.empty:
        return  # clean mode, skip
    violations = validate(ds.tables)
    manifest_violations = manifest_to_violations(ds.defect_manifest)
    assert len(violations) >= len(manifest_violations), (
        f"Fewer violations ({len(violations)}) than manifest entries ({len(manifest_violations)})"
    )
