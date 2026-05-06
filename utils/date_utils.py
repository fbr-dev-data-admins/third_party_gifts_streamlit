"""Date formatting and business day utilities."""

from datetime import date, datetime, timedelta
from typing import Union
import pandas as pd
import holidays
import pytz


def format_date(dt: Union[str, date, datetime, pd.Timestamp], output_format: str = "%m/%d/%y") -> str:
    """
    Format a date value to the specified output format.

    Args:
        dt: Date value in various formats
        output_format: strftime format string (default: MM/DD/YY)

    Returns:
        Formatted date string
    """
    if pd.isna(dt):
        return ""

    if isinstance(dt, str):
        dt = pd.to_datetime(dt)

    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()

    if isinstance(dt, datetime):
        return dt.strftime(output_format)
    elif isinstance(dt, date):
        return dt.strftime(output_format)

    return ""


def get_previous_business_day(from_date: Union[date, None] = None) -> date:
    """
    Get the previous business day from the given date (or today if not specified).

    Business days exclude weekends and US federal holidays.

    Args:
        from_date: Starting date (defaults to today)

    Returns:
        Previous business day as a date object
    """
    if from_date is None:
        from_date = date.today()

    us_holidays = holidays.US(years=[from_date.year, from_date.year - 1])

    check_date = from_date - timedelta(days=1)

    while True:
        if check_date.weekday() < 5 and check_date not in us_holidays:
            return check_date
        check_date -= timedelta(days=1)


def format_gl_post_date() -> str:
    """
    Get the GL Post Date formatted as MM/DD/YY.
    This is the previous business day based on current date in Denver (MT),
    persisting for the full calendar day until midnight Denver time.
    """
    denver_tz = pytz.timezone("America/Denver")
    denver_today = datetime.now(denver_tz).date()
    return format_date(get_previous_business_day(from_date=denver_today))
