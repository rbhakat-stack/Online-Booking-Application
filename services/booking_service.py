"""
Booking Service
================
Manages the lifecycle of booking holds and confirmed bookings.

Booking Hold Lifecycle:
  created → [Stripe checkout] → converted (→ becomes a booking)
            OR expires after hold_expiry_minutes

Booking Lifecycle:
  pending_payment → confirmed (after Stripe verification)
                 → cancelled (user cancels, payment fails)
                 → expired   (hold expired without payment)

Conflict prevention strategy (belt-and-suspenders):
  Layer 1 — Application:
    Check bookings + holds tables before inserting a hold.
    Fast path, gives immediate user feedback.

  Layer 2 — Database:
    EXCLUDE USING GIST constraint on the bookings table prevents
    overlapping bookings at the Postgres level, regardless of timing.
    If two requests slip through layer 1 simultaneously, only one
    INSERT will succeed; the other raises an exclusion violation
    which we catch and surface as "slot just became unavailable".

  Holds table does NOT have the GIST constraint (no btree_gist on
  TSTZRANGE in the holds table to keep schema simpler). Instead:
    - Application layer checks (layer 1 above)
    - Holds expire quickly (10 min) limiting the collision window
    - Only one hold converts to a booking (layer 2 DB constraint)

Idempotency:
  Each hold attempt uses an idempotency_key (UUID) stored in session_state.
  If the same key is submitted twice (e.g., double-click or refresh),
  the existing hold is returned rather than creating a duplicate.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from db.supabase_client import get_client, get_admin_client
from db.queries import get_booking_by_id, get_booking_by_stripe_session
from utils.time_utils import hold_expiry_utc, now_utc, hours_until_booking, get_refund_policy_for_cancellation
from utils.constants import BookingStatus, BookingType

logger = logging.getLogger(__name__)


class BookingError(Exception):
    """Raised when a booking operation fails with a user-safe message."""


class BookingConflictError(BookingError):
    """Raised specifically when the requested slot is no longer available."""


# ── Hold Management ───────────────────────────────────────────

def create_hold(
    access_token: str,
    refresh_token: str,
    facility_id: str,
    court_id: str,
    user_id: str,
    booking_date: str,          # ISO date string: "YYYY-MM-DD"
    start_time_utc: datetime,
    end_time_utc: datetime,
    duration_minutes: int,
    estimated_amount: float,
    idempotency_key: str,       # Client-generated UUID; prevents double-holds
    promo_code_id: Optional[str] = None,
    hold_expiry_minutes: int = 10,
) -> dict:
    """
    Create a booking hold for the requested slot.

    Steps:
    1. Check idempotency: if this key already has a non-expired hold, return it
    2. Check for slot conflicts (application layer)
    3. Insert the hold record
    4. Return the hold dict

    Raises:
        BookingConflictError: if the slot is already taken
        BookingError: for other failures
    """
    client = get_client(access_token, refresh_token)

    # 1. Idempotency check — return existing hold if key matches
    existing = _get_hold_by_idempotency_key(client, idempotency_key)
    if existing:
        logger.info(f"Returning existing hold {existing['id']} for idempotency key {idempotency_key}")
        return existing

    # 2. Application-level conflict check
    _check_slot_conflicts(
        client=client,
        court_id=court_id,
        booking_date=booking_date,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
    )

    # 3. Insert hold
    expires_at = hold_expiry_utc(hold_expiry_minutes)

    hold_data = {
        "facility_id":       facility_id,
        "court_id":          court_id,
        "user_id":           user_id,
        "booking_date":      booking_date,
        "start_time_utc":    start_time_utc.isoformat(),
        "end_time_utc":      end_time_utc.isoformat(),
        "duration_minutes":  duration_minutes,
        "estimated_amount":  estimated_amount,
        "idempotency_key":   idempotency_key,
        "expires_at":        expires_at.isoformat(),
        "is_converted":      False,
    }
    if promo_code_id:
        hold_data["promo_code_id"] = promo_code_id

    try:
        response = client.table("booking_holds").insert(hold_data).execute()
        if not response.data:
            raise BookingError("Failed to create booking hold. Please try again.")
        return response.data[0]

    except BookingConflictError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "unique" in err_str or "duplicate" in err_str:
            # Idempotency key collision — return existing
            existing = _get_hold_by_idempotency_key(client, idempotency_key)
            if existing:
                return existing
        logger.error(f"Hold creation failed: {e}")
        raise BookingError("Could not reserve your slot. Please try again.")


def release_hold(
    access_token: str,
    refresh_token: str,
    hold_id: str,
    user_id: str,
) -> bool:
    """
    Mark a hold as expired (user cancelled before paying).
    Returns True if successful.
    """
    try:
        client = get_client(access_token, refresh_token)
        client.table("booking_holds").update({
            "expires_at": now_utc().isoformat(),  # Expire immediately
        }).eq("id", hold_id).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to release hold {hold_id}: {e}")
        return False


# ── Booking Confirmation ──────────────────────────────────────

def confirm_booking_from_hold(
    hold_id: str,
    stripe_checkout_session_id: str,
    stripe_payment_intent_id: str,
    pricing_result: dict,
    notes: str = "",
) -> dict:
    """
    Convert a hold into a confirmed booking after Stripe payment verification.

    Called ONLY from payment_service.py AFTER server-side Stripe verification.
    Uses the admin client to bypass RLS (this is a trusted server-side operation).

    Steps:
    1. Fetch hold record
    2. Verify hold is not expired and not already converted
    3. Create booking record (status: confirmed)
    4. Mark hold as converted
    5. Create payment record
    6. Return booking

    Raises:
        BookingError: if hold is expired, already converted, or DB write fails
    """
    admin_client = get_admin_client()

    # Fetch the hold
    hold_response = admin_client.table("booking_holds").select("*").eq("id", hold_id).maybe_single().execute()
    hold = hold_response.data
    if not hold:
        raise BookingError(f"Booking hold {hold_id} not found.")

    # Guard: already converted
    if hold.get("is_converted"):
        # Idempotent — return the existing booking
        existing = _get_booking_by_hold_id(admin_client, hold_id)
        if existing:
            logger.info(f"Hold {hold_id} already converted to booking {existing['id']}")
            return existing
        raise BookingError("Hold already converted but no booking found.")

    # Guard: expired
    expires_dt = hold.get("expires_at")
    if expires_dt:
        from utils.time_utils import parse_iso_datetime
        exp = parse_iso_datetime(str(expires_dt))
        if exp and now_utc() > exp:
            raise BookingError(
                "Your payment session expired before we could confirm the booking. "
                "The slot has been released. Please try booking again."
            )

    # Create booking record
    booking_data = {
        "facility_id":                  hold["facility_id"],
        "court_id":                     hold["court_id"],
        "user_id":                      hold["user_id"],
        "hold_id":                      hold_id,
        "booking_date":                 hold["booking_date"],
        "start_time_utc":               hold["start_time_utc"],
        "end_time_utc":                 hold["end_time_utc"],
        "duration_minutes":             hold["duration_minutes"],
        "booking_type":                 BookingType.STANDARD,
        "status":                       BookingStatus.CONFIRMED,
        "base_amount":                  pricing_result.get("base_amount", 0),
        "discount_amount":              pricing_result.get("discount_amount", 0),
        "tax_amount":                   0.00,   # Placeholder — Phase 8
        "fee_amount":                   0.00,   # Placeholder — Phase 8
        "total_amount":                 pricing_result.get("total_amount", 0),
        "currency":                     "usd",
        "stripe_checkout_session_id":   stripe_checkout_session_id,
        "stripe_payment_intent_id":     stripe_payment_intent_id,
        "notes":                        notes or "",
        "waiver_accepted":              True,   # Checked before hold was created
        "waiver_accepted_at":           now_utc().isoformat(),
    }
    if hold.get("promo_code_id"):
        booking_data["promo_code_id"] = hold["promo_code_id"]

    try:
        booking_resp = admin_client.table("bookings").insert(booking_data).execute()
        if not booking_resp.data:
            raise BookingError("Failed to create booking record.")
        booking = booking_resp.data[0]

    except Exception as e:
        err_str = str(e).lower()
        if "exclusion" in err_str or "overlap" in err_str or "conflicts" in err_str:
            # DB-level conflict — extremely rare but possible
            raise BookingConflictError(
                "Another booking was confirmed for this slot moments before yours. "
                "Your payment will be refunded automatically. Please choose a different slot."
            )
        logger.error(f"Booking insert failed for hold {hold_id}: {e}")
        raise BookingError("Failed to confirm booking. Please contact support.")

    # Mark hold as converted
    try:
        admin_client.table("booking_holds").update({
            "is_converted": True,
            "stripe_session_id": stripe_checkout_session_id,
        }).eq("id", hold_id).execute()
    except Exception as e:
        logger.error(f"Failed to mark hold {hold_id} as converted: {e}")
        # Non-critical — booking was created; hold cleanup can happen lazily

    # Create payment record
    _create_payment_record(admin_client, booking, stripe_checkout_session_id, stripe_payment_intent_id)

    return booking


# ── Booking Retrieval ─────────────────────────────────────────

def get_user_bookings(
    access_token: str,
    refresh_token: str,
    user_id: str,
    statuses: Optional[list] = None,
    upcoming_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Fetch bookings for the current user.

    Args:
        upcoming_only: If True, only return bookings with start_time_utc >= now
    """
    client = get_client(access_token, refresh_token)

    query = (
        client.table("bookings")
        .select("*, courts(name, sport_type, indoor, facilities(name, timezone))")
        .eq("user_id", user_id)
        .order("booking_date", desc=not upcoming_only)
        .order("start_time_utc", desc=not upcoming_only)
        .limit(limit)
        .offset(offset)
    )

    if statuses:
        query = query.in_("status", statuses)

    if upcoming_only:
        query = query.gte("start_time_utc", now_utc().isoformat())

    response = query.execute()
    return response.data or []


def get_booking_detail(
    access_token: str,
    refresh_token: str,
    booking_id: str,
    user_id: str,
) -> Optional[dict]:
    """
    Fetch a single booking, ensuring it belongs to the requesting user.
    Returns None if not found or not authorised.
    """
    client = get_client(access_token, refresh_token)
    booking = get_booking_by_id(client, booking_id)
    if booking and str(booking.get("user_id")) == str(user_id):
        return booking
    return None


# ── Cancellation ─────────────────────────────────────────────

def cancel_booking(
    access_token: str,
    refresh_token: str,
    booking_id: str,
    user_id: str,
    reason: str = "User cancellation",
) -> dict:
    """
    Cancel a booking and determine the applicable refund.

    Returns:
        {
            "success": bool,
            "booking": dict,
            "refund_percent": float,
            "refund_amount": float,
            "refund_label": str,
            "message": str,
        }

    Raises:
        BookingError: if booking not found, already cancelled, or too close to start time
    """
    client = get_client(access_token, refresh_token)

    booking = get_booking_by_id(client, booking_id)
    if not booking:
        raise BookingError("Booking not found.")
    if str(booking.get("user_id")) != str(user_id):
        raise BookingError("You are not authorised to cancel this booking.")

    status = booking.get("status")
    if status in (BookingStatus.CANCELLED, BookingStatus.REFUNDED):
        raise BookingError("This booking is already cancelled.")
    if status not in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT):
        raise BookingError(f"Cannot cancel a booking with status: {status}")

    # Determine refund based on time remaining
    from utils.time_utils import parse_iso_datetime
    start_utc = parse_iso_datetime(str(booking.get("start_time_utc", "")))
    hours_remaining = hours_until_booking(start_utc) if start_utc else -1

    refund_policy = get_refund_policy_for_cancellation(hours_remaining)
    refund_amount = round(float(booking.get("total_amount", 0)) * refund_policy["refund_percent"], 2)

    # Update booking status
    try:
        response = client.table("bookings").update({
            "status": BookingStatus.CANCELLED,
            "admin_notes": f"Cancelled by user. Reason: {reason}",
        }).eq("id", booking_id).execute()

        if not response.data:
            raise BookingError("Cancellation failed. Please try again.")

        updated_booking = response.data[0]

    except BookingError:
        raise
    except Exception as e:
        logger.error(f"Cancellation failed for booking {booking_id}: {e}")
        raise BookingError("Cancellation failed. Please contact support.")

    # Refund processing happens in Phase 4 (payment_service.py)
    # Here we record intent and return for the UI to display
    return {
        "success": True,
        "booking": updated_booking,
        "refund_percent": refund_policy["refund_percent"],
        "refund_amount": refund_amount,
        "refund_label": refund_policy["label"],
        "message": (
            f"Booking cancelled. "
            f"{'A refund of $' + str(refund_amount) + ' will be processed within 5–10 business days.' if refund_amount > 0 else 'No refund applies based on our cancellation policy.'}"
        ),
    }


# ── Private Helpers ───────────────────────────────────────────

def _check_slot_conflicts(
    client,
    court_id: str,
    booking_date: str,
    start_time_utc: datetime,
    end_time_utc: datetime,
) -> None:
    """
    Application-layer conflict check before inserting a hold.
    Raises BookingConflictError if a conflict is found.
    """
    from db.queries import get_bookings_for_court_on_date, get_active_holds_for_court
    from utils.time_utils import parse_iso_datetime

    # Check existing bookings
    bookings = get_bookings_for_court_on_date(client, court_id, booking_date)
    for b in bookings:
        b_start = parse_iso_datetime(str(b.get("start_time_utc", "")))
        b_end = parse_iso_datetime(str(b.get("end_time_utc", "")))
        if b_start and b_end:
            if start_time_utc < b_end and end_time_utc > b_start:
                raise BookingConflictError(
                    "This slot was just booked by someone else. Please choose a different time."
                )

    # Check active holds
    holds = get_active_holds_for_court(client, court_id, booking_date)
    for h in holds:
        h_start = parse_iso_datetime(str(h.get("start_time_utc", "")))
        h_end = parse_iso_datetime(str(h.get("end_time_utc", "")))
        if h_start and h_end:
            if start_time_utc < h_end and end_time_utc > h_start:
                raise BookingConflictError(
                    "This slot is currently being held by another user. "
                    "Please choose a different time or try again in a few minutes."
                )


def _get_hold_by_idempotency_key(client, idempotency_key: str) -> Optional[dict]:
    """Return an existing non-expired, non-converted hold with this key."""
    try:
        response = (
            client.table("booking_holds")
            .select("*")
            .eq("idempotency_key", idempotency_key)
            .eq("is_converted", False)
            .gt("expires_at", now_utc().isoformat())
            .maybe_single()
            .execute()
        )
        return response.data
    except Exception:
        return None


def _get_booking_by_hold_id(admin_client, hold_id: str) -> Optional[dict]:
    """Look up a booking created from a specific hold."""
    try:
        response = (
            admin_client.table("bookings")
            .select("*")
            .eq("hold_id", hold_id)
            .maybe_single()
            .execute()
        )
        return response.data
    except Exception:
        return None


def _create_payment_record(
    admin_client,
    booking: dict,
    stripe_session_id: str,
    stripe_payment_intent_id: str,
) -> None:
    """Create a payment record linked to the confirmed booking."""
    try:
        payment_data = {
            "booking_id":                   booking["id"],
            "facility_id":                  booking["facility_id"],
            "user_id":                      booking["user_id"],
            "stripe_checkout_session_id":   stripe_session_id,
            "stripe_payment_intent_id":     stripe_payment_intent_id,
            "amount":                       booking["total_amount"],
            "currency":                     booking.get("currency", "usd"),
            "payment_status":               "completed",
            "refund_status":                "none",
            "idempotency_key":              stripe_session_id,  # Use session ID as idempotency
            "paid_at":                      now_utc().isoformat(),
        }
        admin_client.table("payments").insert(payment_data).execute()
    except Exception as e:
        # Non-critical — payment record can be re-created from Stripe data
        logger.error(f"Failed to create payment record for booking {booking['id']}: {e}")


def generate_idempotency_key() -> str:
    """Generate a fresh UUID to use as an idempotency key for a new hold attempt."""
    return str(uuid.uuid4())
