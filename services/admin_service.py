"""
Admin Service
==============
All admin operations use the service-role client (bypasses RLS).
Only call these functions from pages that have already passed require_admin().

Responsibilities:
  - Dashboard statistics
  - Cross-user booking search and management
  - Facility configuration (settings, hours, closures, courts, pricing)
  - Revenue and occupancy aggregation for metrics

Design:
  - All DB I/O uses get_admin_client() exclusively
  - Python-side aggregation for metrics (avoids custom RPC dependencies)
  - Return plain dicts/lists — no Supabase response objects
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from db.supabase_client import get_admin_client
from utils.time_utils import now_utc, today_local, parse_iso_datetime, hours_until_booking
from utils.constants import BookingStatus

logger = logging.getLogger(__name__)


# ── Internal Helpers ─────────────────────────────────────────

def _enrich_with_user_profiles(
    bookings: list[dict],
    fields: str = "id, full_name, email",
) -> list[dict]:
    """
    Fetch user_profiles for every user_id in *bookings* and attach the profile
    dict under the key ``"user_profiles"`` on each booking row.

    Why this exists:
        ``bookings.user_id`` is a FK to ``auth.users(id)``, **not** to
        ``public.user_profiles(id)``.  PostgREST's embedded-resource syntax
        (``user_profiles(full_name, email)`` in the SELECT string) only works
        when a direct FK exists in the public schema.  Without it PostgREST
        raises PGRST200 "Could not find a relationship".

        Solution: fetch bookings without the join, collect unique user_ids,
        query user_profiles separately, then merge in Python.

    Args:
        bookings: list of booking dicts (must each have a ``user_id`` key).
        fields:   comma-separated column names to fetch from user_profiles.

    Returns:
        The same list, mutated in-place, with ``booking["user_profiles"]``
        set to the matching profile dict (or ``{}`` if no profile found).
    """
    if not bookings:
        return bookings

    user_ids = list({b["user_id"] for b in bookings if b.get("user_id")})
    if not user_ids:
        return bookings

    admin = get_admin_client()
    resp = (
        admin.table("user_profiles")
        .select(fields)
        .in_("id", user_ids)
        .execute()
    )
    profiles: dict[str, dict] = {p["id"]: p for p in (resp.data or [])}

    for booking in bookings:
        uid = booking.get("user_id", "")
        booking["user_profiles"] = profiles.get(uid, {})

    return bookings


# ── Dashboard ─────────────────────────────────────────────────

def get_dashboard_stats(facility_id: str, timezone: str = "America/New_York") -> dict:
    """
    Today's KPIs for the admin dashboard.

    Returns:
        today_bookings: int
        today_revenue:  float (confirmed only)
        monthly_revenue: float (this calendar month, confirmed)
        active_courts:  int
        occupancy_pct:  float (0–100, rough estimate)
        pending_count:  int (pending_payment bookings)
        cancelled_today: int
    """
    admin = get_admin_client()
    today = today_local(timezone).isoformat()
    first_of_month = date.today().replace(day=1).isoformat()

    # Today's bookings
    today_resp = admin.table("bookings").select("id, total_amount, status, duration_minutes") \
        .eq("facility_id", facility_id) \
        .eq("booking_date", today) \
        .execute()
    today_bookings = today_resp.data or []

    confirmed_today = [b for b in today_bookings if b["status"] == BookingStatus.CONFIRMED]
    pending_today   = [b for b in today_bookings if b["status"] == BookingStatus.PENDING_PAYMENT]
    cancelled_today = [b for b in today_bookings if b["status"] == BookingStatus.CANCELLED]

    today_revenue = sum(float(b.get("total_amount", 0)) for b in confirmed_today)
    booked_minutes = sum(int(b.get("duration_minutes", 0)) for b in confirmed_today)

    # Monthly revenue
    month_resp = admin.table("bookings").select("total_amount") \
        .eq("facility_id", facility_id) \
        .eq("status", BookingStatus.CONFIRMED) \
        .gte("booking_date", first_of_month) \
        .execute()
    monthly_revenue = sum(float(b.get("total_amount", 0)) for b in (month_resp.data or []))

    # Active courts
    courts_resp = admin.table("courts").select("id") \
        .eq("facility_id", facility_id).eq("status", "active").execute()
    active_courts = len(courts_resp.data or [])

    # Rough occupancy: booked minutes / (courts × 14 operating hours in minutes)
    max_minutes = active_courts * 14 * 60 if active_courts > 0 else 1
    occupancy_pct = min(round((booked_minutes / max_minutes) * 100, 1), 100.0)

    return {
        "today_booking_count": len(confirmed_today) + len(pending_today),
        "today_revenue":       today_revenue,
        "monthly_revenue":     monthly_revenue,
        "active_courts":       active_courts,
        "occupancy_pct":       occupancy_pct,
        "pending_count":       len(pending_today),
        "cancelled_today":     len(cancelled_today),
    }


def get_todays_bookings(facility_id: str, timezone: str = "America/New_York") -> list[dict]:
    """All bookings for today ordered by start time, with user and court info."""
    admin = get_admin_client()
    today = today_local(timezone).isoformat()

    resp = admin.table("bookings") \
        .select("id, start_time_utc, end_time_utc, duration_minutes, status, total_amount, "
                "notes, court_id, user_id, "
                "courts(name, sport_type)") \
        .eq("facility_id", facility_id) \
        .eq("booking_date", today) \
        .in_("status", [BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT]) \
        .order("start_time_utc") \
        .execute()
    return _enrich_with_user_profiles(resp.data or [], fields="id, full_name, email")


def get_recent_activity(facility_id: str, limit: int = 12) -> list[dict]:
    """Most recent booking events (all statuses) with user and court info."""
    admin = get_admin_client()

    resp = admin.table("bookings") \
        .select("id, booking_date, status, total_amount, created_at, user_id, "
                "courts(name, sport_type)") \
        .eq("facility_id", facility_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return _enrich_with_user_profiles(resp.data or [], fields="id, full_name, email")


# ── Booking Management ────────────────────────────────────────

def search_bookings(
    facility_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status_filter: Optional[list] = None,
    sport_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Paginated booking search for the admin booking management page.
    Python-side sport_type filtering since it's a nested field.
    """
    admin = get_admin_client()

    # Full column set — may include optional columns not in every deployment.
    # Falls back to core-only columns if the production schema is missing them.
    _FULL_COLS = (
        "id, booking_date, start_time_utc, end_time_utc, duration_minutes, "
        "status, total_amount, base_amount, discount_amount, notes, "
        "admin_notes, stripe_payment_intent_id, created_at, user_id, "
        "courts(name, sport_type, indoor)"
    )
    _CORE_COLS = (
        "id, booking_date, start_time_utc, end_time_utc, duration_minutes, "
        "status, total_amount, notes, stripe_payment_intent_id, created_at, user_id, "
        "courts(name, sport_type, indoor)"
    )

    def _build_query(cols: str):
        q = (
            admin.table("bookings")
            .select(cols)
            .eq("facility_id", facility_id)
            .order("booking_date", desc=True)
            .order("start_time_utc", desc=True)
            .limit(limit)
            .offset(offset)
        )
        if date_from:
            q = q.gte("booking_date", date_from)
        if date_to:
            q = q.lte("booking_date", date_to)
        if status_filter:
            q = q.in_("status", status_filter)
        return q

    try:
        resp = _build_query(_FULL_COLS).execute()
        rows = resp.data or []
    except Exception:
        # Retry with core columns only (handles missing optional schema columns)
        try:
            resp = _build_query(_CORE_COLS).execute()
            rows = resp.data or []
        except Exception as e:
            logger.error(f"search_bookings fallback query also failed: {e}")
            rows = []

    if sport_type:
        rows = [r for r in rows if (r.get("courts") or {}).get("sport_type") == sport_type]

    return _enrich_with_user_profiles(rows, fields="id, full_name, email, phone")


def admin_cancel_booking(
    booking_id: str,
    reason: str,
    issue_refund: bool = False,
    refund_amount_dollars: float = 0.0,
) -> dict:
    """
    Admin-force cancel a booking and optionally issue a Stripe refund.
    Uses admin client — bypasses ownership checks.

    Returns:
        {"success": bool, "message": str, "refund": dict | None}
    """
    admin = get_admin_client()

    # Fetch booking
    resp = admin.table("bookings").select("*").eq("id", booking_id).maybe_single().execute()
    booking = resp.data if resp is not None else None
    if not booking:
        return {"success": False, "message": "Booking not found.", "refund": None}

    status = booking.get("status")
    if status in (BookingStatus.CANCELLED, BookingStatus.REFUNDED):
        return {"success": False, "message": f"Booking is already {status}.", "refund": None}

    # Cancel in DB
    admin.table("bookings").update({
        "status": BookingStatus.CANCELLED,
        "admin_notes": f"Admin cancelled. Reason: {reason}",
    }).eq("id", booking_id).execute()

    refund_result = None
    if issue_refund and booking.get("stripe_payment_intent_id"):
        from services.payment_service import issue_refund as stripe_refund
        refund_result = stripe_refund(
            stripe_payment_intent_id=booking["stripe_payment_intent_id"],
            amount_dollars=refund_amount_dollars,
            reason="requested_by_customer",
        )

    return {
        "success": True,
        "message": (
            f"Booking cancelled. "
            + (
                f"Refund of ${refund_result.get('amount_dollars', 0):.2f} initiated."
                if refund_result and refund_result.get("success")
                else ("Refund failed — process manually." if refund_result else "No refund issued.")
            )
        ),
        "refund": refund_result,
    }


def add_admin_note(booking_id: str, note: str) -> bool:
    """Append a note to a booking's admin_notes field."""
    try:
        admin = get_admin_client()
        admin.table("bookings").update({"admin_notes": note}).eq("id", booking_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update admin note for booking {booking_id}: {e}")
        return False


# ── Facility Configuration ────────────────────────────────────

def create_facility(data: dict) -> dict:
    """
    Insert a new facility record.  Super-admin only — caller must enforce that.

    ``data`` should contain at minimum ``name`` and ``timezone``.
    All other fields (address, city, state, zip_code, phone, email) are optional.

    A URL-safe slug is auto-generated from the name.  If the slug already exists
    (UNIQUE constraint violation), a numeric suffix is appended automatically.

    Returns the inserted facility row.
    """
    import re
    admin = get_admin_client()

    insert_data = {k: v for k, v in data.items() if v not in (None, "")}
    insert_data.setdefault("is_active", True)

    # Generate slug: lowercase, collapse non-alphanumeric runs to hyphens
    raw = re.sub(r"[^a-z0-9]+", "-", insert_data.get("name", "facility").lower()).strip("-")

    # Ensure uniqueness by checking existing slugs that start with this root
    existing = (
        admin.table("facilities")
        .select("slug")
        .like("slug", f"{raw}%")
        .execute()
    )
    used_slugs = {r["slug"] for r in (existing.data or [])}
    slug = raw
    suffix = 2
    while slug in used_slugs:
        slug = f"{raw}-{suffix}"
        suffix += 1
    insert_data["slug"] = slug

    resp = admin.table("facilities").insert(insert_data).execute()
    if not resp.data:
        raise RuntimeError("Facility insert returned no data.")

    facility = resp.data[0]
    fac_id = facility["id"]
    logger.info(f"New facility created: {fac_id} — {insert_data.get('name')}")

    # ── Seed facility_settings with safe defaults ──────────────
    try:
        admin.table("facility_settings").insert({
            "facility_id":                    fac_id,
            "min_booking_minutes":            60,
            "booking_increment_minutes":      30,
            "max_booking_hours":              4,
            "hold_expiry_minutes":            10,
            "booking_window_days":            30,
            "buffer_minutes_between_bookings": 0,
            "cancellation_window_hours":      24,
            "partial_refund_window_hours":    12,
            "partial_refund_percentage":      50,
            "allow_same_day_booking":         True,
            "require_membership":             False,
        }).execute()
        logger.info(f"Default facility_settings seeded for {fac_id}")
    except Exception as e:
        logger.warning(f"Could not seed facility_settings for {fac_id}: {e}")

    # ── Seed facility_operating_hours (Mon–Sun, 8 AM – 10 PM) ─
    from utils.constants import DAYS_OF_WEEK
    try:
        hours_records = [
            {
                "facility_id": fac_id,
                "day_of_week": day,
                "is_open":     True,
                "open_time":   "08:00:00",
                "close_time":  "22:00:00",
            }
            for day in DAYS_OF_WEEK
        ]
        admin.table("facility_operating_hours").insert(hours_records).execute()
        logger.info(f"Default operating hours seeded for {fac_id}")
    except Exception as e:
        logger.warning(f"Could not seed facility_operating_hours for {fac_id}: {e}")

    return facility


def get_full_facility(facility_id: str) -> Optional[dict]:
    """Fetch full facility record for editing."""
    admin = get_admin_client()
    resp = admin.table("facilities").select("*").eq("id", facility_id).maybe_single().execute()
    if resp is None:
        return None
    return resp.data


def update_facility_info(facility_id: str, data: dict) -> dict:
    """Update top-level facility fields (name, email, phone, address, etc.)."""
    admin = get_admin_client()
    resp = admin.table("facilities").update(data).eq("id", facility_id).execute()
    if not resp.data:
        raise RuntimeError("Facility update returned no data.")
    return resp.data[0]


def upsert_facility_settings(facility_id: str, settings: dict) -> dict:
    """Create or update facility settings."""
    admin = get_admin_client()
    settings["facility_id"] = facility_id
    resp = admin.table("facility_settings") \
        .upsert(settings, on_conflict="facility_id") \
        .execute()
    if not resp.data:
        raise RuntimeError("Settings upsert returned no data.")
    return resp.data[0]


def upsert_operating_hours(facility_id: str, hours_list: list[dict]) -> list[dict]:
    """
    Replace operating hours for a facility.
    hours_list: list of {day_of_week, is_open, open_time, close_time}
    """
    admin = get_admin_client()
    records = [
        {**h, "facility_id": facility_id}
        for h in hours_list
    ]
    resp = admin.table("facility_operating_hours") \
        .upsert(records, on_conflict="facility_id,day_of_week") \
        .execute()
    return resp.data or []


def add_closure(facility_id: str, closure_data: dict) -> dict:
    """Insert a new closure date."""
    admin = get_admin_client()
    closure_data["facility_id"] = facility_id
    resp = admin.table("facility_closures").insert(closure_data).execute()
    if not resp.data:
        raise RuntimeError("Closure insert returned no data.")
    return resp.data[0]


def remove_closure(closure_id: str) -> bool:
    """Delete a closure record."""
    try:
        admin = get_admin_client()
        admin.table("facility_closures").delete().eq("id", closure_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to delete closure {closure_id}: {e}")
        return False


def get_all_courts(facility_id: str) -> list[dict]:
    """All courts for a facility (all statuses)."""
    admin = get_admin_client()
    resp = admin.table("courts").select("*") \
        .eq("facility_id", facility_id) \
        .order("display_order") \
        .execute()
    return resp.data or []


def upsert_court(facility_id: str, court_data: dict) -> dict:
    """Create or update a court record."""
    admin = get_admin_client()
    court_data["facility_id"] = facility_id
    if "id" in court_data and court_data["id"]:
        resp = admin.table("courts").update(court_data).eq("id", court_data["id"]).execute()
    else:
        court_data.pop("id", None)
        resp = admin.table("courts").insert(court_data).execute()
    if not resp.data:
        raise RuntimeError("Court upsert returned no data.")
    return resp.data[0]


def set_court_status(court_id: str, status: str) -> bool:
    """Quick toggle of a court's status (active / inactive / maintenance)."""
    try:
        admin = get_admin_client()
        admin.table("courts").update({"status": status}).eq("id", court_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to set court {court_id} status: {e}")
        return False


def get_all_pricing_rules(facility_id: str) -> list[dict]:
    """All pricing rules including inactive ones."""
    admin = get_admin_client()
    resp = admin.table("pricing_rules").select("*") \
        .eq("facility_id", facility_id) \
        .order("priority", desc=True) \
        .execute()
    return resp.data or []


def upsert_pricing_rule(facility_id: str, rule_data: dict) -> dict:
    """Create or update a pricing rule."""
    admin = get_admin_client()
    rule_data["facility_id"] = facility_id
    if "id" in rule_data and rule_data["id"]:
        resp = admin.table("pricing_rules").update(rule_data).eq("id", rule_data["id"]).execute()
    else:
        rule_data.pop("id", None)
        resp = admin.table("pricing_rules").insert(rule_data).execute()
    if not resp.data:
        raise RuntimeError("Pricing rule upsert returned no data.")
    return resp.data[0]


def toggle_pricing_rule(rule_id: str, is_active: bool) -> bool:
    """Activate or deactivate a pricing rule."""
    try:
        admin = get_admin_client()
        admin.table("pricing_rules").update({"is_active": is_active}).eq("id", rule_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to toggle pricing rule {rule_id}: {e}")
        return False


# ── Metrics & Analytics ───────────────────────────────────────

def get_summary_metrics(
    facility_id: str,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Aggregate metrics for a date range.
    Returns:
        total_revenue, booking_count, avg_booking_value,
        cancellation_count, cancellation_rate, total_hours_booked
    """
    admin = get_admin_client()
    resp = admin.table("bookings") \
        .select("id, status, total_amount, duration_minutes") \
        .eq("facility_id", facility_id) \
        .gte("booking_date", start_date) \
        .lte("booking_date", end_date) \
        .execute()

    bookings = resp.data or []
    confirmed = [b for b in bookings if b["status"] == BookingStatus.CONFIRMED]
    cancelled = [b for b in bookings if b["status"] == BookingStatus.CANCELLED]

    total_revenue = sum(float(b.get("total_amount", 0)) for b in confirmed)
    booking_count = len(confirmed)
    cancellation_count = len(cancelled)
    total_records = len(bookings)
    total_hours = sum(int(b.get("duration_minutes", 0)) for b in confirmed) / 60

    return {
        "total_revenue":      total_revenue,
        "booking_count":      booking_count,
        "avg_booking_value":  total_revenue / booking_count if booking_count else 0,
        "cancellation_count": cancellation_count,
        "cancellation_rate":  round((cancellation_count / total_records * 100) if total_records else 0, 1),
        "total_hours_booked": round(total_hours, 1),
    }


def get_revenue_by_day(
    facility_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Daily revenue for a date range.
    Returns list of {"date": "YYYY-MM-DD", "revenue": float, "bookings": int}
    sorted ascending by date.
    """
    admin = get_admin_client()
    resp = admin.table("bookings") \
        .select("booking_date, total_amount") \
        .eq("facility_id", facility_id) \
        .eq("status", BookingStatus.CONFIRMED) \
        .gte("booking_date", start_date) \
        .lte("booking_date", end_date) \
        .execute()

    # Aggregate in Python
    daily: dict[str, dict] = {}
    for b in (resp.data or []):
        d = b["booking_date"]
        if d not in daily:
            daily[d] = {"date": d, "revenue": 0.0, "bookings": 0}
        daily[d]["revenue"] += float(b.get("total_amount", 0))
        daily[d]["bookings"] += 1

    # Fill zero-revenue dates in range
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    result = []
    while current <= end:
        key = current.isoformat()
        result.append(daily.get(key, {"date": key, "revenue": 0.0, "bookings": 0}))
        current += timedelta(days=1)

    return result


def get_booking_stats_by_sport(
    facility_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Booking count and revenue grouped by sport type.
    Returns list of {"sport_type": str, "bookings": int, "revenue": float}
    """
    admin = get_admin_client()
    resp = admin.table("bookings") \
        .select("total_amount, courts(sport_type)") \
        .eq("facility_id", facility_id) \
        .eq("status", BookingStatus.CONFIRMED) \
        .gte("booking_date", start_date) \
        .lte("booking_date", end_date) \
        .execute()

    by_sport: dict[str, dict] = {}
    for b in (resp.data or []):
        sport = (b.get("courts") or {}).get("sport_type", "unknown")
        if sport not in by_sport:
            by_sport[sport] = {"sport_type": sport, "bookings": 0, "revenue": 0.0}
        by_sport[sport]["bookings"] += 1
        by_sport[sport]["revenue"] += float(b.get("total_amount", 0))

    return sorted(by_sport.values(), key=lambda x: x["bookings"], reverse=True)


def get_hourly_occupancy(
    facility_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Booking counts by hour-of-day and day-of-week for the heatmap.
    Returns list of {"day": 0-6 (Mon=0), "hour": 0-23, "count": int}
    """
    admin = get_admin_client()
    resp = admin.table("bookings") \
        .select("start_time_utc, end_time_utc, duration_minutes") \
        .eq("facility_id", facility_id) \
        .eq("status", BookingStatus.CONFIRMED) \
        .gte("booking_date", start_date) \
        .lte("booking_date", end_date) \
        .execute()

    # Aggregate: for each booking, mark each hour it covers
    grid: dict[tuple, int] = {}

    for b in (resp.data or []):
        start = parse_iso_datetime(str(b.get("start_time_utc", "")))
        duration_min = int(b.get("duration_minutes", 60))
        if not start:
            continue
        # Enumerate hours covered by this booking
        for i in range(0, duration_min, 60):
            slot = start + timedelta(minutes=i)
            key = (slot.weekday(), slot.hour)
            grid[key] = grid.get(key, 0) + 1

    result = []
    for day in range(7):
        for hour in range(6, 23):    # 6 AM – 10 PM
            result.append({
                "day": day,
                "hour": hour,
                "count": grid.get((day, hour), 0),
            })
    return result
