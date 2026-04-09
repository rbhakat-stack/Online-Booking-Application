"""
Availability Service
=====================
Generates available time slots for a given facility, date, and duration.

Architecture:
  This service is pure computation — it takes pre-fetched data (operating
  hours, existing bookings, closures, blackout periods) and returns a slot
  availability map. Database I/O is separated (done in the page or booking_service)
  to keep this module testable without a live DB connection.

Slot Availability Pipeline:
  1. Get operating hours for the requested day of week
  2. Check for full-day closures → return empty if closed
  3. Check for partial closures → trim operating window
  4. Generate all possible (start, end) slot pairs within the window
  5. For each slot: check against existing bookings + active holds + blackout periods
  6. Apply buffer time (if configured) around existing bookings
  7. Return per-court availability map

Overlap Check Logic (matching DB EXCLUDE constraint):
  Two ranges [A_start, A_end) and [B_start, B_end) overlap if:
    A_start < B_end  AND  A_end > B_start

  This is the canonical "half-open interval" overlap test.
  The same logic is enforced at the DB level via EXCLUDE USING GIST on tstzrange.
"""

from datetime import date, time, timedelta, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from utils.time_utils import (
    get_day_of_week_name,
    generate_time_slots,
    combine_date_time_utc,
    combine_date_time_local,
    parse_iso_datetime,
    parse_time_str,
    now_utc,
    format_time,
)


# ── Types ─────────────────────────────────────────────────────

SlotInfo = dict        # {"start_time": time, "end_time": time, "start_utc": datetime, "end_utc": datetime, "available": bool, "reason": str}
CourtAvailability = dict   # {court_id: {"court": dict, "slots": list[SlotInfo]}}


# ── Public API ────────────────────────────────────────────────

def get_facility_availability(
    requested_date: date,
    duration_minutes: int,
    courts: list[dict],
    operating_hours_list: list[dict],
    facility_settings: dict,
    existing_bookings: list[dict],   # All bookings for this date across all courts
    active_holds: list[dict],        # All active holds for this date across all courts
    closures: list[dict],            # All closures for this facility
    blackout_periods: list[dict],    # All blackout periods overlapping this date
    timezone: str = "America/New_York",
    target_court_id: Optional[str] = None,  # Filter to a single court
) -> CourtAvailability:
    """
    Generate availability for all active courts (or a specific court) on a given date.

    Returns a dict keyed by court_id. Each value contains:
        {
            "court": dict,               # Full court record
            "is_blacked_out": bool,      # True if the whole court is in a blackout
            "slots": [                   # Ordered list of slots
                {
                    "start_time":    time,
                    "end_time":      time,
                    "start_utc":     datetime,
                    "end_utc":       datetime,
                    "available":     bool,
                    "reason":        str | None,   # Why unavailable (for debugging)
                }
            ]
        }
    """
    day_name = get_day_of_week_name(requested_date)

    # Find operating hours for this day
    hours_for_day = _get_hours_for_day(operating_hours_list, day_name)
    if not hours_for_day or not hours_for_day.get("is_open"):
        # Facility closed on this day → all courts unavailable
        return _build_closed_day_result(courts, "Facility is closed on this day.")

    open_time = parse_time_str(str(hours_for_day["open_time"]))
    close_time = parse_time_str(str(hours_for_day["close_time"]))
    if not open_time or not close_time:
        return _build_closed_day_result(courts, "Operating hours not configured.")

    # Check full-day closures
    full_day_closure = _get_full_day_closure(closures, requested_date, day_name)
    if full_day_closure:
        reason = f"Closed: {full_day_closure.get('reason', 'Special closure')}"
        return _build_closed_day_result(courts, reason)

    # Apply partial closures to narrow the operating window
    open_time, close_time = _apply_partial_closures(
        closures, requested_date, day_name, open_time, close_time
    )

    # Generate all candidate slots for the day
    increment = int(facility_settings.get("booking_increment_minutes", 30))
    buffer = int(facility_settings.get("buffer_minutes_between_bookings", 0))

    all_slots = generate_time_slots(open_time, close_time, increment, duration_minutes)
    if not all_slots:
        return _build_closed_day_result(courts, "No slots fit within operating hours for the selected duration.")

    # Build result per court
    result: CourtAvailability = {}

    # Group existing data by court_id for efficient lookup
    bookings_by_court = _group_by_court(existing_bookings)
    holds_by_court = _group_by_court(active_holds, id_field="court_id")

    # Blackout periods affecting ALL courts (court_id IS NULL)
    facility_wide_blackouts = [b for b in blackout_periods if not b.get("court_id")]

    for court in courts:
        court_id = str(court["id"])

        if target_court_id and court_id != target_court_id:
            continue

        # Check if this specific court is blacked out for the whole date
        court_specific_blackouts = [
            b for b in blackout_periods if b.get("court_id") and str(b["court_id"]) == court_id
        ]
        all_court_blackouts = facility_wide_blackouts + court_specific_blackouts

        # Check full-day blackout for this court
        full_day_blackout = _check_full_day_blackout(
            all_court_blackouts, requested_date, open_time, close_time, timezone
        )

        court_bookings = bookings_by_court.get(court_id, [])
        court_holds = holds_by_court.get(court_id, [])

        now = now_utc()   # Computed once per court to keep comparisons consistent

        slots: list[SlotInfo] = []
        for start, end in all_slots:
            slot_start_utc = combine_date_time_utc(requested_date, start, timezone)
            slot_end_utc = combine_date_time_utc(requested_date, end, timezone)

            # ── Past-slot guard ──────────────────────────────────
            # Slots whose start time has already passed are immediately
            # marked unavailable and grayed out in the UI.  We use a strict
            # less-than so a slot starting exactly now is still blocked
            # (the user would not have time to complete the booking flow).
            if slot_start_utc <= now:
                available = False
                reason = "Slot is in the past"
            elif full_day_blackout:
                available = False
                reason = full_day_blackout
            else:
                available, reason = _is_slot_available(
                    slot_start_utc=slot_start_utc,
                    slot_end_utc=slot_end_utc,
                    court_bookings=court_bookings,
                    court_holds=court_holds,
                    blackout_periods=all_court_blackouts,
                    buffer_minutes=buffer,
                )

            slots.append({
                "start_time":  start,
                "end_time":    end,
                "start_utc":   slot_start_utc,
                "end_utc":     slot_end_utc,
                "available":   available,
                "reason":      reason,
                "label":       f"{format_time(start)} – {format_time(end)}",
            })

        result[court_id] = {
            "court": court,
            "is_blacked_out": bool(full_day_blackout),
            "slots": slots,
            "available_count": sum(1 for s in slots if s["available"]),
        }

    return result


def get_combined_availability(
    court_availability: CourtAvailability,
) -> list[dict]:
    """
    Flatten per-court availability into a combined time-first view.

    For each possible start time, returns how many courts are available.
    Used for the "auto-assign" UI where users pick a time, not a court.

    Returns:
        [
            {
                "start_time":      time,
                "end_time":        time,
                "start_utc":       datetime,
                "end_utc":         datetime,
                "label":           str,
                "available_courts": int,
                "total_courts":    int,
                "available":       bool,
                "court_ids":       list[str],  # IDs of available courts for this slot
            }
        ]
    """
    if not court_availability:
        return []

    # Collect all unique start times from any court
    all_start_times: dict[time, dict] = {}

    for court_id, court_data in court_availability.items():
        for slot in court_data["slots"]:
            st_key = slot["start_time"]
            if st_key not in all_start_times:
                all_start_times[st_key] = {
                    "start_time":       slot["start_time"],
                    "end_time":         slot["end_time"],
                    "start_utc":        slot["start_utc"],
                    "end_utc":          slot["end_utc"],
                    "label":            slot["label"],
                    "available_courts": 0,
                    "total_courts":     0,
                    "court_ids":        [],
                }
            all_start_times[st_key]["total_courts"] += 1
            if slot["available"]:
                all_start_times[st_key]["available_courts"] += 1
                all_start_times[st_key]["court_ids"].append(court_id)

    combined = sorted(all_start_times.values(), key=lambda x: x["start_time"])
    for slot in combined:
        slot["available"] = slot["available_courts"] > 0

    return combined


def pick_best_court(
    court_availability: CourtAvailability,
    start_time_utc: datetime,
    sport_type: Optional[str] = None,
) -> Optional[str]:
    """
    Auto-assign: pick the best available court for a given UTC start time.

    Preference order:
    1. Courts matching the requested sport_type
    2. Courts with the smallest display_order (admin-defined preference)
    3. Any available court as fallback

    Returns court_id or None if no court is available.
    """
    candidates = []
    for court_id, data in court_availability.items():
        court = data["court"]
        for slot in data["slots"]:
            if slot["start_utc"] == start_time_utc and slot["available"]:
                candidates.append(court)
                break

    if not candidates:
        return None

    # Sort: sport match first, then display_order
    def sort_key(c):
        sport_match = 0 if (sport_type and c.get("sport_type") == sport_type) else 1
        return (sport_match, c.get("display_order", 99))

    candidates.sort(key=sort_key)
    return str(candidates[0]["id"])


# ── Private Helpers ───────────────────────────────────────────

def _get_hours_for_day(hours_list: list[dict], day_name: str) -> Optional[dict]:
    for h in hours_list:
        if h.get("day_of_week") == day_name:
            return h
    return None


def _get_full_day_closure(
    closures: list[dict],
    requested_date: date,
    day_name: str,
) -> Optional[dict]:
    """
    Return the closure record if the entire day is closed.
    A full-day closure has no start_time / end_time set.
    """
    for closure in closures:
        ctype = closure.get("closure_type", "one_time")
        start_t = closure.get("start_time")
        end_t = closure.get("end_time")

        # Skip partial closures (they have times set)
        if start_t or end_t:
            continue

        if ctype == "one_time":
            closure_date_raw = closure.get("closure_date")
            if closure_date_raw:
                closure_date = _parse_date(closure_date_raw)
                if closure_date == requested_date:
                    return closure

        elif ctype == "recurring":
            recur_day = closure.get("recur_day_of_week")
            if recur_day != day_name:
                continue
            if not _in_recurrence_window(closure, requested_date):
                continue
            # Full-day recurring closure (no recur_start_time / recur_end_time)
            if not closure.get("recur_start_time") and not closure.get("recur_end_time"):
                return closure

    return None


def _apply_partial_closures(
    closures: list[dict],
    requested_date: date,
    day_name: str,
    open_time: time,
    close_time: time,
) -> tuple[time, time]:
    """
    Narrow the operating window based on partial closures.

    If a partial closure covers the START of the day, push open_time later.
    If it covers the END of the day, push close_time earlier.
    Mid-day partial closures are handled as slot-level blocks in _is_slot_available.

    This is a simplification — complex partial closures (e.g., 10–11 AM)
    are handled at the slot level, not by trimming the window.
    """
    for closure in closures:
        ctype = closure.get("closure_type", "one_time")
        start_t_raw = closure.get("start_time") or closure.get("recur_start_time")
        end_t_raw = closure.get("end_time") or closure.get("recur_end_time")

        if not start_t_raw or not end_t_raw:
            continue     # Full-day closures already handled above

        is_applicable = False
        if ctype == "one_time":
            closure_date = _parse_date(closure.get("closure_date"))
            is_applicable = (closure_date == requested_date)
        elif ctype == "recurring":
            if closure.get("recur_day_of_week") == day_name:
                is_applicable = _in_recurrence_window(closure, requested_date)

        if not is_applicable:
            continue

        closure_start = parse_time_str(str(start_t_raw))
        closure_end = parse_time_str(str(end_t_raw))
        if not closure_start or not closure_end:
            continue

        # If closure covers the opening → push open_time to closure_end
        if closure_start <= open_time < closure_end:
            open_time = closure_end
        # If closure covers the closing → pull close_time to closure_start
        elif closure_start < close_time <= closure_end:
            close_time = closure_start

    return open_time, close_time


def _is_slot_available(
    slot_start_utc: datetime,
    slot_end_utc: datetime,
    court_bookings: list[dict],
    court_holds: list[dict],
    blackout_periods: list[dict],
    buffer_minutes: int = 0,
) -> tuple[bool, Optional[str]]:
    """
    Check if a slot is free from conflicts.

    Conflict sources:
    1. Existing bookings (status: hold/pending_payment/confirmed)
    2. Active booking holds (not expired, not converted)
    3. Blackout periods (partial — full-day is handled upstream)

    Buffer: if buffer_minutes > 0, existing bookings effectively extend by
    buffer_minutes. We check against (booking_end + buffer) for the slot start.

    Returns (available: bool, reason: str | None)
    """
    buffer_delta = timedelta(minutes=buffer_minutes)

    # Check existing bookings
    for booking in court_bookings:
        b_start = parse_iso_datetime(str(booking.get("start_time_utc", "")))
        b_end = parse_iso_datetime(str(booking.get("end_time_utc", "")))
        if not b_start or not b_end:
            continue
        # Extend effective end by buffer
        b_end_buffered = b_end + buffer_delta
        if _ranges_overlap(slot_start_utc, slot_end_utc, b_start, b_end_buffered):
            return False, "Already booked"

    # Check active holds (expired holds are filtered in the query, but double-check)
    now = now_utc()
    for hold in court_holds:
        expires = parse_iso_datetime(str(hold.get("expires_at", "")))
        if expires and now > expires:
            continue   # Expired hold — skip
        if hold.get("is_converted"):
            continue   # Already became a booking — skip

        h_start = parse_iso_datetime(str(hold.get("start_time_utc", "")))
        h_end = parse_iso_datetime(str(hold.get("end_time_utc", "")))
        if not h_start or not h_end:
            continue
        if _ranges_overlap(slot_start_utc, slot_end_utc, h_start, h_end):
            return False, "Slot is on hold"

    # Check blackout periods
    for blackout in blackout_periods:
        if not blackout.get("is_active", True):
            continue
        bk_start = parse_iso_datetime(str(blackout.get("start_time_utc", "")))
        bk_end = parse_iso_datetime(str(blackout.get("end_time_utc", "")))
        if not bk_start or not bk_end:
            continue
        if _ranges_overlap(slot_start_utc, slot_end_utc, bk_start, bk_end):
            return False, f"Court unavailable: {blackout.get('name', 'Blocked')}"

    return True, None


def _check_full_day_blackout(
    blackout_periods: list[dict],
    requested_date: date,
    open_time: time,
    close_time: time,
    timezone: str,
) -> Optional[str]:
    """
    Return a reason string if a blackout covers the entire operating day,
    None otherwise.
    """
    day_start_utc = combine_date_time_utc(requested_date, open_time, timezone)
    day_end_utc = combine_date_time_utc(requested_date, close_time, timezone)

    for blackout in blackout_periods:
        if not blackout.get("is_active", True):
            continue
        bk_start = parse_iso_datetime(str(blackout.get("start_time_utc", "")))
        bk_end = parse_iso_datetime(str(blackout.get("end_time_utc", "")))
        if bk_start and bk_end:
            # Blackout covers entire operating window
            if bk_start <= day_start_utc and bk_end >= day_end_utc:
                return f"Court unavailable: {blackout.get('name', 'Blocked')}"
    return None


def _ranges_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    """
    Half-open interval overlap test.
    [A_start, A_end) overlaps [B_start, B_end) iff A_start < B_end AND A_end > B_start.
    This matches the DB EXCLUDE USING GIST (tstzrange(..., '[)')) constraint.
    """
    return a_start < b_end and a_end > b_start


def _group_by_court(records: list[dict], id_field: str = "court_id") -> dict:
    """Group a list of dicts by their court_id value."""
    grouped: dict[str, list] = {}
    for record in records:
        cid = str(record.get(id_field, ""))
        if cid:
            grouped.setdefault(cid, []).append(record)
    return grouped


def _parse_date(raw) -> Optional[date]:
    """Parse a date from a string or date object."""
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _in_recurrence_window(closure: dict, requested_date: date) -> bool:
    """Check if requested_date falls within a recurring closure's date range."""
    start_raw = closure.get("recur_start_date")
    end_raw = closure.get("recur_end_date")

    if start_raw:
        start_d = _parse_date(start_raw)
        if start_d and requested_date < start_d:
            return False
    if end_raw:
        end_d = _parse_date(end_raw)
        if end_d and requested_date > end_d:
            return False
    return True


def _build_closed_day_result(courts: list[dict], reason: str) -> CourtAvailability:
    """Return a CourtAvailability where every court has no available slots."""
    return {
        str(court["id"]): {
            "court": court,
            "is_blacked_out": True,
            "slots": [],
            "available_count": 0,
            "closed_reason": reason,
        }
        for court in courts
    }
