"""Property 5: Flow Identity at all grains."""
from hypothesis import given, settings
from hr_analytics_lib.generator import generate
from tests.conftest import valid_generation_config

@given(config=valid_generation_config(clean_only=True))
@settings(max_examples=20, deadline=60_000)
def test_flow_identity(config):
    """Flow_Identity holds for every org_periods row."""
    ds = generate(config)
    org = ds.tables["org_periods"]
    for idx, row in org.iterrows():
        closing = row["opening"] + row["hires"] + row["transfers_in"] - row["separations"] - row["transfers_out"]
        assert closing == row["closing"], (
            f"Flow identity violated at row {idx}: "
            f"{row['opening']}+{row['hires']}+{row['transfers_in']}"
            f"-{row['separations']}-{row['transfers_out']}={closing} != {row['closing']}"
        )
    # ORG grain should have transfers_in = transfers_out = 0
    org_rows = org[org["grain_type"] == "ORG"]
    assert (org_rows["transfers_in"] == 0).all(), "ORG grain should have transfers_in=0"
    assert (org_rows["transfers_out"] == 0).all(), "ORG grain should have transfers_out=0"
