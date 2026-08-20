"""Unit tests for GenerationConfig validation.

Validates: Requirements 2.2–2.8

These tests verify that GenerationConfig raises ConfigError with the correct
message for each invalid parameter, and that valid configurations construct
without error.
"""

from __future__ import annotations

from datetime import date

import pytest

from hr_analytics_lib.exceptions import ConfigError
from hr_analytics_lib.generator.config import GenerationConfig
from hr_analytics_lib.schema import DefectType


# ---------------------------------------------------------------------------
# Fixture: valid base config kwargs
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_config_kwargs() -> dict:
    """Provide valid base configuration kwargs for parameterization."""
    return {
        "headcount": 50,
        "n_levels": 5,
        "n_departments": 3,
        "start_date": date(2023, 1, 1),
        "end_date": date(2024, 1, 1),
        "annual_separation_rate": 0.12,
        "annual_hiring_rate": 0.15,
        "seed": 42,
        "corruption_config": None,
    }


# ---------------------------------------------------------------------------
# Validation error tests (8 cases)
# ---------------------------------------------------------------------------


class TestValidationErrors:
    """Test all 8 validation error cases raise ConfigError with exact message."""

    def test_headcount_less_than_1(self, valid_config_kwargs: dict) -> None:
        """ConfigError when headcount < 1."""
        valid_config_kwargs["headcount"] = 0
        with pytest.raises(ConfigError, match="headcount must be ≥ 1"):
            GenerationConfig(**valid_config_kwargs)

    def test_n_levels_less_than_1(self, valid_config_kwargs: dict) -> None:
        """ConfigError when n_levels < 1."""
        valid_config_kwargs["n_levels"] = 0
        with pytest.raises(ConfigError, match="n_levels must be between 1 and 15"):
            GenerationConfig(**valid_config_kwargs)

    def test_n_levels_greater_than_15(self, valid_config_kwargs: dict) -> None:
        """ConfigError when n_levels > 15."""
        valid_config_kwargs["n_levels"] = 16
        with pytest.raises(ConfigError, match="n_levels must be between 1 and 15"):
            GenerationConfig(**valid_config_kwargs)

    def test_n_departments_less_than_1(self, valid_config_kwargs: dict) -> None:
        """ConfigError when n_departments < 1."""
        valid_config_kwargs["n_departments"] = 0
        with pytest.raises(ConfigError, match="n_departments must be ≥ 1"):
            GenerationConfig(**valid_config_kwargs)

    def test_end_date_not_after_start_date(self, valid_config_kwargs: dict) -> None:
        """ConfigError when end_date <= start_date."""
        valid_config_kwargs["end_date"] = valid_config_kwargs["start_date"]
        with pytest.raises(ConfigError, match="end_date must be after start_date"):
            GenerationConfig(**valid_config_kwargs)

    def test_annual_separation_rate_out_of_bounds(self, valid_config_kwargs: dict) -> None:
        """ConfigError when annual_separation_rate is outside [0.0, 1.0]."""
        valid_config_kwargs["annual_separation_rate"] = 1.5
        with pytest.raises(ConfigError, match=r"annual_separation_rate must be in \[0\.0, 1\.0\]"):
            GenerationConfig(**valid_config_kwargs)

    def test_annual_hiring_rate_out_of_bounds(self, valid_config_kwargs: dict) -> None:
        """ConfigError when annual_hiring_rate is outside [0.0, 5.0]."""
        valid_config_kwargs["annual_hiring_rate"] = -0.1
        with pytest.raises(ConfigError, match=r"annual_hiring_rate must be in \[0\.0, 5\.0\]"):
            GenerationConfig(**valid_config_kwargs)

    def test_corruption_rate_out_of_bounds(self, valid_config_kwargs: dict) -> None:
        """ConfigError when corruption_rate is outside (0.0, 1.0]."""
        valid_config_kwargs["corruption_config"] = {DefectType.NULL_INJECTION: 0.0}
        with pytest.raises(ConfigError, match=r"corruption_rate must be in \(0\.0, 1\.0\]"):
            GenerationConfig(**valid_config_kwargs)


# ---------------------------------------------------------------------------
# Additional positive tests
# ---------------------------------------------------------------------------


class TestValidConfig:
    """Test valid configurations and properties."""

    def test_valid_config_no_error(self, valid_config_kwargs: dict) -> None:
        """A valid config raises no error on construction."""
        config = GenerationConfig(**valid_config_kwargs)
        assert config.headcount == 50
        assert config.n_levels == 5
        assert config.n_departments == 3

    def test_config_hash_deterministic(self, valid_config_kwargs: dict) -> None:
        """Same params produce the same config_hash."""
        config1 = GenerationConfig(**valid_config_kwargs)
        config2 = GenerationConfig(**valid_config_kwargs)
        assert config1.config_hash == config2.config_hash
        assert len(config1.config_hash) == 64  # SHA-256 hex digest

    def test_resolved_seed_with_explicit_seed(self, valid_config_kwargs: dict) -> None:
        """resolved_seed returns the explicit seed when one is provided."""
        valid_config_kwargs["seed"] = 12345
        config = GenerationConfig(**valid_config_kwargs)
        assert config.resolved_seed == 12345

    def test_resolved_seed_without_seed_is_int(self, valid_config_kwargs: dict) -> None:
        """resolved_seed returns an int when no explicit seed is provided."""
        valid_config_kwargs["seed"] = None
        config = GenerationConfig(**valid_config_kwargs)
        result = config.resolved_seed
        assert isinstance(result, int)
        assert result >= 0
