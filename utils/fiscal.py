"""Fiscal year calculation utilities."""

from datetime import date
from typing import Union
import pandas as pd


def get_fiscal_year(dt: Union[date, str, pd.Timestamp]) -> int:
    """
    Get the 2-digit fiscal year number for a given date.

    Fiscal year runs July 1 - June 30. The fiscal year number is the
    2-digit year of the latter half (the calendar year in which the FY ends).

    Examples:
        June 15, 2026 -> 26 (FY26 ends June 30, 2026)
        July 3, 2026 -> 27 (FY27 ends June 30, 2027)
        January 10, 2027 -> 27 (FY27 ends June 30, 2027)
    """
    if isinstance(dt, str):
        dt = pd.to_datetime(dt).date()
    elif isinstance(dt, pd.Timestamp):
        dt = dt.date()

    if dt.month >= 7:
        return (dt.year + 1) % 100
    else:
        return dt.year % 100


def get_campaign(dt: Union[date, str, pd.Timestamp]) -> str:
    """
    Get the campaign code for a given date.

    Format: FY## where ## is the 2-digit fiscal year.
    """
    fy = get_fiscal_year(dt)
    return f"FY{fy:02d}"


def get_appeal(dt: Union[date, str, pd.Timestamp]) -> str:
    """
    Get the appeal code for a given date.

    Format: ##WORK where ## is the 2-digit fiscal year.
    """
    fy = get_fiscal_year(dt)
    return f"{fy:02d}WORK"
