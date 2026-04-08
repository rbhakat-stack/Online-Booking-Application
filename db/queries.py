"""
Common Database Queries
========================
Thin wrappers around Supabase table operations.
All methods return Python dicts/lists — no Supabase response objects leak
beyond this module.

Services import from here rather than calling supabase directly, so query
logic is centralised and testable in isolation.

Conventions:
- Functions that return a single row return Optional[dict]
- Functions that return multiple rows return list[dict]
- Functions that mutate return the affected row(s) as dict
- All exceptions propagate to the caller (service layer handles them)
"""

from typing import Optional
from supabase import Client


# ── Facilities ───────────────────────────────────────────────

def get_active_facilities(client: Client) -> list[dict]:
    """Return all active facilities (public — no auth required)."""
    response = (
        client.table("facilities")
        .select("id, name, slug, address, city, state, zip_code, timezone, phone, email")
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    return response.data or []


def get_facility_by_id(client: Client, facility_id: str) -> Optional[dict]:
    response = (
        client.table("facilities")
        .select("*")
        .eq("id", facility_id)
        .maybe_single()
        .execute()
    )
    return response.data


def get_facility_settings(client: Client, facility_id: str) -> Optional[dict]:
    response = (
        client.table("facility_settings")
        .select("*")
        .eq("facility_id", facility_id)
        .maybe_single()
        .execute()
    )
    return response.data


def get_facility_operating_hours(client: Client, facility_id: str) -> list[dict]:
    """Return operating hours ordered by day of week (Mon–Sun)."""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    response = (
        client.table("facility_operating_hours")
        .select("*")
        .eq("facility_id", facility_id)
        .execute()
    )
    rows = response.data or []
    # Sort by day order
    rows.sort(key=lambda r: day_order.index(r["day_of_week"]) if r["day_of_week"] in day_order else 99)
    return rows


def get_facility_closures(client: Client, facility_id: str) -> list[dict]:
    """Return all closure records for a facility."""
    response = (
        client.table("facility_closures")
        .select("*")
        .eq("facility_id", facility_id)
        .order("closure_date", desc=False)
        .execute()
    )
    return response.data or []


# ── Courts ───────────────────────────────────────────────────

def get_active_courts(client: Client, facility_id: str, sport_type: Optional[str] = None) -> list[dict]:
    """Return active courts for a facility, optionally filtered by sport."""
    query = (
        client.table("courts")
        .select("*")
        .eq("facility_id", facility_id)
        .eq("status", "active")
        .order("display_order")
    )
    if sport_type:
        query = query.eq("sport_type", sport_type)
    response = query.execute()
    return response.data or []


def get_court_by_id(client: Client, court_id: str) -> Optional[dict]:
    response = (
        client.table("courts")
        .select("*, facilities(name, timezone)")
        .eq("id", court_id)
        .maybe_single()
        .execute()
    )
    return response.data


def get_all_courts_for_facility(client: Client, facility_id: str) -> list[dict]:
    """Admin: return all courts regardless of status."""
    response = (
        client.table("courts")
        .select("*")
        .eq("facility_id", facility_id)
        .order("display_order")
        .execute()
    )
    return response.data or []


# ── Bookings ─────────────────────────────────────────────────

def get_bookings_for_court_on_date(
    client: Client,
    court_id: str,
    date_str: str,             # ISO date string: "YYYY-MM-DD"
    conflict_statuses: Optional[list] = None,
) -> list[dict]:
    """
    Return bookings for a court on a given date.
    Used by the availability engine to determine occupied slots.
    date_str is the local date (stored in booking_date column).
    """
    if conflict_statuses is None:
        conflict_statuses = ["hold", "pending_payment", "confirmed"]

    response = (
        client.table("bookings")
        .select("id, start_time_utc, end_time_utc, status, booking_type")
        .eq("court_id", court_id)
        .eq("booking_date", date_str)
        .in_("status", conflict_statuses)
        .execute()
    )
    return response.data or []


def get_user_bookings(
    client: Client,
    user_id: str,
    statuses: Optional[list] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return bookings for the current user, newest first."""
    query = (
        client.table("bookings")
        .select(
            "*, courts(name, sport_type, facility_id, facilities(name, timezone))"
        )
        .eq("user_id", user_id)
        .order("booking_date", desc=True)
        .order("start_time_utc", desc=True)
        .limit(limit)
        .offset(offset)
    )
    if statuses:
        query = query.in_("status", statuses)
    response = query.execute()
    return response.data or []


def get_booking_by_id(client: Client, booking_id: str) -> Optional[dict]:
    response = (
        client.table("bookings")
        .select("*, courts(*, facilities(name, timezone))")
        .eq("id", booking_id)
        .maybe_single()
        .execute()
    )
    return response.data


def get_booking_by_stripe_session(client: Client, session_id: str) -> Optional[dict]:
    """Used in payment verification flow."""
    response = (
        client.table("bookings")
        .select("*")
        .eq("stripe_checkout_session_id", session_id)
        .maybe_single()
        .execute()
    )
    return response.data


# ── Booking Holds ────────────────────────────────────────────

def get_active_holds_for_court(
    client: Client,
    court_id: str,
    date_str: str,
) -> list[dict]:
    """Return non-expired, non-converted holds for a court on a date."""
    from utils.time_utils import now_utc
    now_iso = now_utc().isoformat()

    response = (
        client.table("booking_holds")
        .select("id, start_time_utc, end_time_utc, expires_at")
        .eq("court_id", court_id)
        .eq("booking_date", date_str)
        .eq("is_converted", False)
        .gt("expires_at", now_iso)
        .execute()
    )
    return response.data or []


# ── Pricing Rules ────────────────────────────────────────────

def get_pricing_rules(client: Client, facility_id: str) -> list[dict]:
    """Return all active pricing rules for a facility, ordered by priority desc."""
    response = (
        client.table("pricing_rules")
        .select("*")
        .eq("facility_id", facility_id)
        .eq("is_active", True)
        .order("priority", desc=True)
        .execute()
    )
    return response.data or []


# ── Blackout Periods ─────────────────────────────────────────

def get_blackout_periods_for_date(
    client: Client,
    facility_id: str,
    date_str: str,
) -> list[dict]:
    """
    Return active blackout periods that overlap with the given date.
    We check if any blackout starts on or before the end of the date
    and ends on or after the start of the date.
    """
    # Use a simple date range check — server handles the overlap logic
    response = (
        client.table("blackout_periods")
        .select("*")
        .eq("facility_id", facility_id)
        .eq("is_active", True)
        .lte("start_time_utc", f"{date_str}T23:59:59+00:00")
        .gte("end_time_utc", f"{date_str}T00:00:00+00:00")
        .execute()
    )
    return response.data or []


# ── User Profiles ────────────────────────────────────────────

def get_user_profile(client: Client, user_id: str) -> Optional[dict]:
    response = (
        client.table("user_profiles")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return response.data


def upsert_user_profile(client: Client, profile_data: dict) -> Optional[dict]:
    """Insert or update a user profile. Returns the upserted row."""
    response = (
        client.table("user_profiles")
        .upsert(profile_data, on_conflict="id")
        .execute()
    )
    return response.data[0] if response.data else None


# ── Promo Codes ──────────────────────────────────────────────

def get_promo_code(client: Client, code: str) -> Optional[dict]:
    """Look up an active, valid promo code by its code string."""
    from utils.time_utils import now_utc
    now_iso = now_utc().isoformat()

    response = (
        client.table("promo_codes")
        .select("*")
        .eq("code", code.strip().upper())
        .eq("is_active", True)
        .or_(f"valid_until.is.null,valid_until.gt.{now_iso}")
        .maybe_single()
        .execute()
    )
    return response.data


# ── Payments ─────────────────────────────────────────────────

def get_payment_by_booking(client: Client, booking_id: str) -> Optional[dict]:
    response = (
        client.table("payments")
        .select("*")
        .eq("booking_id", booking_id)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return response.data


# ── Admin ────────────────────────────────────────────────────

def get_facility_admins(client: Client, facility_id: str) -> list[dict]:
    response = (
        client.table("facility_admins")
        .select("*, user_profiles(full_name, email, role)")
        .eq("facility_id", facility_id)
        .eq("is_active", True)
        .execute()
    )
    return response.data or []


def get_admin_facilities(client: Client, user_id: str) -> list[dict]:
    """Return facilities that a given user administers."""
    response = (
        client.table("facility_admins")
        .select("facilities(*)")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .execute()
    )
    rows = response.data or []
    return [r["facilities"] for r in rows if r.get("facilities")]
