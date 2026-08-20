"""GenerationConfig — immutable configuration for a generation run.

Invariants:
- All fields are validated on construction (__post_init__).
- Validation raises ConfigError for the FIRST invalid parameter found (deterministic order).
- Once constructed, the config is immutable (frozen dataclass).
- resolved_seed provides a deterministic seed whether user-supplied or OS-entropy-derived.
- config_hash produces a stable SHA-256 fingerprint for metadata recording.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from hr_analytics_lib.exceptions import ConfigError
from hr_analytics_lib.schema import DefectType


@dataclass(frozen=True)
class GenerationConfig:
    """Validated, immutable configuration for a single generation run.

    Parameters
    ----------
    headcount : int
        Initial number of employees to generate. Must be ≥ 1.
    n_levels : int
        Number of organisational levels. Must be in [1, 15].
    n_departments : int
        Number of departments to generate. Must be ≥ 1.
    start_date : date
        First day of the simulation period. Must be before end_date.
    end_date : date
        Last day of the simulation period. Must be after start_date.
    annual_separation_rate : float
        Fraction of employees separating per year. Must be in [0.0, 1.0].
    annual_hiring_rate : float
        Fraction of current headcount hired per year. Must be in [0.0, 5.0].
    seed : int | None
        Explicit seed for reproducibility. None draws from OS entropy.
    corruption_config : dict[DefectType, float] | None
        Mapping of defect types to corruption rates. None means clean mode.
        Each rate must be in (0.0, 1.0].
    """

    headcount: int
    n_levels: int
    n_departments: int
    start_date: date
    end_date: date
    annual_separation_rate: float = 0.12
    annual_hiring_rate: float = 0.15
    seed: int | None = None
    corruption_config: dict[DefectType, float] | None = None

    def __post_init__(self) -> None:
        """Validate all parameters in fixed declaration order.

        Raises ConfigError on the FIRST invalid parameter encountered.
        Validation order:
          1. headcount ≥ 1
          2. n_levels ∈ [1, 15]
          3. n_departments ≥ 1
          4. end_date > start_date
          5. annual_separation_rate ∈ [0.0, 1.0]
          6. annual_hiring_rate ∈ [0.0, 5.0]
          7. corruption_config values ∈ (0.0, 1.0]
        """
        if self.headcount < 1:
            raise ConfigError("headcount must be ≥ 1")

        if self.n_levels < 1 or self.n_levels > 15:
            raise ConfigError("n_levels must be between 1 and 15")

        if self.n_departments < 1:
            raise ConfigError("n_departments must be ≥ 1")

        if self.end_date <= self.start_date:
            raise ConfigError("end_date must be after start_date")

        if self.annual_separation_rate < 0.0 or self.annual_separation_rate > 1.0:
            raise ConfigError("annual_separation_rate must be in [0.0, 1.0]")

        if self.annual_hiring_rate < 0.0 or self.annual_hiring_rate > 5.0:
            raise ConfigError("annual_hiring_rate must be in [0.0, 5.0]")

        if self.corruption_config is not None:
            for defect_type, rate in self.corruption_config.items():
                if not isinstance(defect_type, DefectType):
                    raise ConfigError(f"Unknown defect type: {defect_type}")
                if rate <= 0.0 or rate > 1.0:
                    raise ConfigError("corruption_rate must be in (0.0, 1.0]")

    @property
    def resolved_seed(self) -> int:
        """Return the explicit seed or generate one from OS entropy.

        If a seed was provided at construction, returns that seed.
        If no seed was provided, draws 128 bits from OS entropy.

        Note: For OS-entropy seeds, this property returns a different value
        each time it is called. The caller should invoke it once and store
        the result in Run_Metadata for reproducibility.
        """
        if self.seed is not None:
            return self.seed
        return secrets.randbits(128)

    @property
    def config_hash(self) -> str:
        """SHA-256 hash of the canonical JSON representation of this config.

        The hash captures all user-facing parameters in a deterministic order.
        It does NOT include resolved_seed (since that may be non-deterministic
        when seed is None). The hash is recorded in Run_Metadata for provenance.

        Returns
        -------
        str
            64-character lowercase hex SHA-256 digest.
        """
        canonical = json.dumps(
            {
                "headcount": self.headcount,
                "n_levels": self.n_levels,
                "n_departments": self.n_departments,
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "annual_separation_rate": self.annual_separation_rate,
                "annual_hiring_rate": self.annual_hiring_rate,
                "seed": self.seed,
                "corruption_config": (
                    {
                        k.value: v
                        for k, v in sorted(
                            self.corruption_config.items(),
                            key=lambda x: x[0].value,
                        )
                    }
                    if self.corruption_config
                    else None
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
