"""Property 2: CSV Round-Trip — serialize then deserialize equals original."""
import tempfile
from pathlib import Path
from hypothesis import given, settings
from hr_analytics_lib.generator import generate, to_csv, from_csv
from tests.conftest import valid_generation_config

@given(config=valid_generation_config(clean_only=True))
@settings(max_examples=10, deadline=60_000)
def test_csv_roundtrip(config):
    """Write to CSV and read back produces equal row counts and structure."""
    ds = generate(config)
    with tempfile.TemporaryDirectory() as tmpdir:
        to_csv(ds, Path(tmpdir))
        ds2 = from_csv(Path(tmpdir))
        for name in ds.tables:
            assert len(ds.tables[name]) == len(ds2.tables[name]), f"{name} row count mismatch"
