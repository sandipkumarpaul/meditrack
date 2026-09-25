"""
Centralized timezone handling.

Dose/refill timestamps are stored in UTC (DoseLog.timestamp), but "what day
is it" and "what time of day is it" for reminders, daily resets, and
low-stock deduplication must be evaluated in the household's local timezone
(default Asia/Dhaka) -- otherwise a server running in UTC will reset doses
and fire "Morning" reminders at the wrong wall-clock time.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import current_app


def utcnow_naive():
    """Current UTC time as a naive datetime -- the storage convention for all
    DateTime columns. Replaces the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_app_timezone():
    tz_name = current_app.config.get('APP_TIMEZONE', 'Asia/Dhaka')
    return ZoneInfo(tz_name)


def now_local():
    """Current timezone-aware datetime in the app's configured timezone."""
    return datetime.now(get_app_timezone())


def today_local():
    """Current calendar date in the app's configured timezone."""
    return now_local().date()


def utc_to_local(naive_utc_dt):
    """Converts a naive UTC datetime (as stored on DoseLog) to a
    timezone-aware datetime in the app's configured timezone."""
    if naive_utc_dt is None:
        return None
    aware_utc = naive_utc_dt.replace(tzinfo=timezone.utc)
    return aware_utc.astimezone(get_app_timezone())


def local_midnight_utc_naive(local_date=None):
    """
    Returns the naive UTC datetime corresponding to local midnight on the
    given local date (defaults to today). Use this to build the lower bound
    when filtering DoseLog.timestamp (stored as naive UTC) by local calendar
    day, e.g. "doses taken today".
    """
    tz = get_app_timezone()
    d = local_date or today_local()
    local_midnight = datetime(d.year, d.month, d.day, tzinfo=tz)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
