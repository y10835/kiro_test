"""Shared pytest fixtures and Hypothesis strategies."""
from datetime import date, timedelta
from hypothesis import strategies as st, settings
from hr_analytics_lib.generator.config import GenerationConfig
from hr_analytics_lib.schema import DefectType

@st.composite
def valid_generation_config(draw, clean_only=False):
    """Strategy producing valid GenerationConfig values.
    
    Bounded for PBT tractability:
    - headcount: 5–100
    - n_levels: 1–5
    - n_departments: 1–5
    - date range: 2–12 months
    - rates: sensible defaults
    """
    headcount = draw(st.integers(5, 100))
    n_levels = draw(st.integers(1, 5))
    n_departments = draw(st.integers(1, 5))
    start_year = draw(st.integers(2020, 2023))
    start_month = draw(st.integers(1, 12))
    start_date = date(start_year, start_month, 1)
    n_months = draw(st.integers(2, 12))
    # Compute end date
    end_month = start_month + n_months
    end_year = start_year + (end_month - 1) // 12
    end_month = ((end_month - 1) % 12) + 1
    end_date = date(end_year, end_month, 1) - timedelta(days=1)
    
    sep_rate = draw(st.floats(0.05, 0.3))
    hire_rate = draw(st.floats(0.05, 0.5))
    seed = draw(st.integers(0, 2**32 - 1))
    
    if clean_only:
        corruption = None
    else:
        corruption = draw(st.one_of(
            st.none(),
            st.fixed_dictionaries({
                dt: st.floats(0.01, 0.1) for dt in DefectType
            }),
        ))
    
    return GenerationConfig(
        headcount=headcount,
        n_levels=n_levels,
        n_departments=n_departments,
        start_date=start_date,
        end_date=end_date,
        annual_separation_rate=sep_rate,
        annual_hiring_rate=hire_rate,
        seed=seed,
        corruption_config=corruption,
    )

@st.composite
def invalid_generation_config(draw):
    """Strategy producing guaranteed-invalid GenerationConfig kwargs."""
    failure_mode = draw(st.sampled_from([
        "bad_headcount", "bad_levels_low", "bad_levels_high",
        "bad_departments", "inverted_dates", "bad_sep_rate", "bad_hire_rate",
    ]))
    
    kwargs = {
        "headcount": 50,
        "n_levels": 5,
        "n_departments": 3,
        "start_date": date(2022, 1, 1),
        "end_date": date(2023, 1, 1),
        "seed": 42,
    }
    
    if failure_mode == "bad_headcount":
        kwargs["headcount"] = draw(st.integers(-100, 0))
    elif failure_mode == "bad_levels_low":
        kwargs["n_levels"] = draw(st.integers(-10, 0))
    elif failure_mode == "bad_levels_high":
        kwargs["n_levels"] = draw(st.integers(16, 100))
    elif failure_mode == "bad_departments":
        kwargs["n_departments"] = draw(st.integers(-10, 0))
    elif failure_mode == "inverted_dates":
        kwargs["start_date"] = date(2023, 6, 1)
        kwargs["end_date"] = date(2022, 1, 1)
    elif failure_mode == "bad_sep_rate":
        kwargs["annual_separation_rate"] = draw(st.floats(1.01, 10.0))
    elif failure_mode == "bad_hire_rate":
        kwargs["annual_hiring_rate"] = draw(st.floats(5.01, 100.0))
    
    return kwargs
