"""
Timezone-Safe DateTime Utilities
=================================
All datetime operations in this app go through this module.

Key design decisions:
- ALL datetimes stored in Postgres are UTC (TIMESTAMPTZ).
- Facility operating hours are stored as local TIME values (not UTC) because
  they represent human-defined schedules that must survive DST transitions.
  e.g., "open at 8 AM" always means 8 AM local time, regardless of DST.
- Conversion to/from UTC happens here, using the facility's configured timezone.
- We use `zoneinfo` (Python 3.9+ stdlib) as the primary TZ library.
  It is DST-aware and handles "America/New_York" correctly across all transitions.

Usage:
    from utils.time_utils import utc_to_local, local_to_utc, generate_time_slots
"""

from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional

DEFAULT_TIMEZONE = "America/New_York"


# ── Timezone Helpers ─────────────────────────────────────────

def get_timezone(tz_name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    """
    Return a ZoneInfo object for the given IANA timezone name.
    Falls back to DEFAULT_TIMEZONE if the name is invalid.
    """
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_utc() -> datetime:
    """Current timestamp in UTC (timezone-aware)."""
    return datetime.now(ZoneInfo("UTC"))


def now_local(tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """Current timestamp in the given local timezone."""
    return datetime.now(get_timezone(tz_name))


def today_local(tz_name: str = DEFAULT_TIMEZONE) -> date:
    """Today's date in the given local timezone."""
    return now_local(tz_name).date()


# ── Conversion ───────────────────────────────────────────────

def utc_to_local(dt: datetime, tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """
    Convert a UTC datetime to a local timezone datetime.
    If dt is naive (no tzinfo), it is assumed to be UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(get_timezone(tz_name))


def local_to_utc(dt: datetime, tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """
    Convert a local datetime to UTC.
    If dt is naive, it is assumed to be in tz_name.
    Uses fold=0 (pre-DST transition) for ambiguous times.
    """
    tz = get_timezone(tz_name)
    if dt.tzinfo is None:
        # Attach the local timezone (fold=0 = pre-DST-transition for ambiguous times)
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(ZoneInfo("UTC"))


def combine_date_time_local(
    d: date,
    t: time,
    tz_name: str = DEFAULT_TIMEZONE,
) -> datetime:
    """
    Combine a date and a naive time into a timezone-aware local datetime.

    DST note: For ambiguous times (e.g., 1:30 AM during "fall back"),
    fold=0 is used, which picks the pre-transition (standard) time.
    This is the safe default for booking logic.
    """
    naive_dt = datetime.combine(d, t)
    tz = get_timezone(tz_name)
    return naive_dt.replace(tzinfo=tz)


def combine_date_time_utc(
    d: date,
    t: time,
    tz_name: str = DEFAULT_TIMEZONE,
) -> datetime:
    """
    Combine a local date + local time and return the result in UTC.
    Used when saving slot times to the database.
    """
    local_dt = combine_date_time_local(d, t, tz_name)
    return local_dt.astimezone(ZoneInfo("UTC"))


# ── Parsing ──────────────────────────────────────────────────

def parse_iso_datetime(iso_str: str) -> Optional[datetime]:
    """
    Parse an ISO 8601 string (as returned by Supabase/Postgres) into a
    timezone-aware datetime in UTC.

    Handles both:
    - "2024-06-15T18:00:00+00:00"  (standard ISO)
    - "2024-06-15T18:00:00Z"       (Zulu notation)
    """
    if not iso_str:
        return None
    try:
        normalized = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt
    except (ValueError, AttributeError):
        return None


def parse_time_str(time_str: str) -> Optional[time]:
    """
    Parse a time string in HH:MM or HH:MM:SS format.
    Returns None if parsing fails.
    """
    if not time_str:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None


# ── Formatting ───────────────────────────────────────────────

def format_datetime_local(
    dt: datetime,
    tz_name: str = DEFAULT_TIMEZONE,
    fmt: str = "%b %d, %Y %I:%M %p",
) -> str:
    """
    Format a UTC datetime as a human-readable string in the local timezone.
    Example output: "Jun 15, 2024 06:00 PM"
    """
    if dt is None:
        return "—"
    local_dt = utc_to_local(dt, tz_name)
    return local_dt.strftime(fmt)


def format_time(t: time) -> str:
    """
    Format a time object for display.
    Example: time(17, 0) → "5:00 PM"
    Uses strftime with zero-padded hour then strips leading zero.
    """
    if t is None:
        return "—"
    raw = datetime.combine(date.today(), t).strftime("%I:%M %p")
    return raw.lstrip("0")


def format_date(d: date, fmt: str = "%B %d, %Y") -> str:
    """Format a date for display. Example: "June 15, 2024" """
    if d is None:
        return "—"
    return d.strftime(fmt)


def format_duration(minutes: int) -> str:
    """
    Format a duration in minutes for display.
    Examples: 60 → "1 hour", 90 → "1.5 hours", 120 → "2 hours"
    """
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    if hours == int(hours):
        label = "hour" if hours == 1 else "hours"
        return f"{int(hours)} {label}"
    return f"{hours:.1f} hours"


# ── Slot Generation ──────────────────────────────────────────

def generate_time_slots(
    open_time: time,
    close_time: time,
    increment_minutes: int,
    duration_minutes: int,
) -> list[tuple[time, time]]:
    """
    Generate all valid (start_time, end_time) slot pairs for a day.

    A slot is valid when:
        start_time + duration_minutes <= close_time

    This ensures the last slot ends exactly at closing time (not after).

    Args:
        open_time: Facility open time (local)
        close_time: Facility close time (local)
        increment_minutes: How often slots start (e.g., 30 → every 30 min)
        duration_minutes: Duration of each booking (e.g., 60)

    Returns:
        List of (start_time, end_time) tuples in chronological order.

    Example:
        open=08:00, close=10:00, increment=30, duration=60
        → [(08:00, 09:00), (08:30, 09:30), (09:00, 10:00)]
        09:30 start is excluded because 09:30 + 60 min = 10:30 > 10:00
    """
    slots: list[tuple[time, time]] = []
    base_date = date.today()

    current = datetime.combine(base_date, open_time)
    close_dt = datetime.combine(base_date, close_time)
    duration_delta = timedelta(minutes=duration_minutes)
    increment_delta = timedelta(minutes=increment_minutes)

    while current + duration_delta <= close_dt:
        end = current + duration_delta
        slots.append((current.time(), end.time()))
        current += increment_delta

    return slots


# ── Cancellation / Refund ────────────────────────────────────

def hours_until_booking(start_time_utc: datetime) -> float:
    """
    Calculate how many hours remain until a booking starts.
    Returns a negative value if the booking is in the past.
    """
    if start_time_utc.tzinfo is None:
        start_time_utc = start_time_utc.replace(tzinfo=ZoneInfo("UTC"))
    delta = start_time_utc - now_utc()
    return delta.total_seconds() / 3600


def get_refund_policy_for_cancellation(
    hours_remaining: float,
    full_refund_hours: int = 24,
    partial_refund_hours: int = 12,
    partial_refund_pct: float = 0.50,
) -> dict:
    """
    Given hours remaining before booking start, return the applicable refund policy.

    Returns:
        {
            "refund_percent": float (0.0 to 1.0),
            "label": str (human-readable description),
            "eligible": bool,
        }
    """
    if hours_remaining > full_refund_hours:
        return {
            "refund_percent": 1.0,
            "label": f"Full refund (> {full_refund_hours}h before booking)",
            "eligible": True,
        }
    elif hours_remaining > partial_refund_hours:
        pct_display = int(partial_refund_pct * 100)
        return {
            "refund_percent": partial_refund_pct,
            "label": f"{pct_display}% refund ({partial_refund_hours}–{full_refund_hours}h before booking)",
            "eligible": True,
        }
    elif hours_remaining > 0:
        return {
            "refund_percent": 0.0,
            "label": f"No refund (< {partial_refund_hours}h before booking)",
            "eligible": False,
        }
    else:
        return {
            "refund_percent": 0.0,
            "label": "Booking has already started — no refund available.",
            "eligible": False,
        }


# ── Hold ─────────────────────────────────────────────────────

def hold_expiry_utc(expiry_minutes: int = 10) -> datetime:
    """Calculate UTC expiry time for a booking hold."""
    return now_utc() + timedelta(minutes=expiry_minutes)


def is_hold_expired(expires_at_str: str) -> bool:
    """
    Check if a hold has expired.
    expires_at_str is an ISO 8601 string from the database.
    """
    expires_at = parse_iso_datetime(expires_at_str)
    if not expires_at:
        return True
    return now_utc() > expires_at


# ── Day-of-Week ──────────────────────────────────────────────

def get_day_of_week_name(d: date) -> str:
    """Return lowercase day name for a date. e.g., date(2024,6,15) → 'saturday'"""
    return d.strftime("%A").lower()


def is_weekend(d: date) -> bool:
    """Return True if the date is Saturday or Sunday."""
    return d.weekday() >= 5
