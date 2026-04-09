"""
Payment Service — Stripe Integration
======================================
Handles all Stripe Checkout operations for the booking platform.

Architecture & Design Decisions:
─────────────────────────────────
1. HOSTED CHECKOUT (not Elements)
   We use Stripe Checkout (hosted page) rather than building a custom payment
   form. Benefits: PCI compliance handled by Stripe, supports many payment
   methods automatically, works perfectly with Streamlit's redirect model.

2. SERVER-SIDE VERIFICATION (critical security requirement)
   After Stripe redirects back to success_url, we ALWAYS call
   stripe.checkout.Session.retrieve(session_id) server-side to verify
   payment_status == "paid" before confirming any booking.
   We never trust the mere fact that the user reached the success URL.

3. NO WEBHOOKS (MVP limitation — documented workaround)
   Streamlit Community Cloud does not support persistent webhook endpoints.
   Workaround: verify via return URL + server-side API call (safe for MVP).

   KNOWN RISK: If a user pays but closes the browser before the success URL
   loads, the booking hold expires and the slot is released. Their payment
   is captured. This requires admin intervention to issue a manual refund.

   POST-MVP FIX: Deploy a separate lightweight webhook handler (FastAPI on
   Railway/Render) that listens for checkout.session.completed and calls
   confirm_booking_from_hold() directly. See README for details.

4. IDEMPOTENCY
   confirm_booking_from_hold() is idempotent — if called twice with the same
   hold_id (e.g., user hits back + forward), it returns the existing booking.
   Stripe session IDs are stored as unique constraints on the bookings table.

5. HOLD vs. STRIPE SESSION EXPIRY MISMATCH
   Our booking hold expires in 10 minutes (configurable).
   Stripe requires sessions to last at least 30 minutes.
   We do NOT set expires_at on the Stripe session — we use Stripe's default.
   The 10-minute countdown is communicated to users on the UI.
   If a hold expires before the user pays, we detect this in payment_success.py
   and offer a refund if payment was captured.

6. AMOUNTS
   Stripe works in the smallest currency unit (cents for USD).
   All amounts are converted: dollars × 100 = cents for Stripe API calls,
   cents ÷ 100 = dollars for display and DB storage.
"""

import logging
import stripe
from typing import Optional

from db.supabase_client import get_admin_client
from utils.config import get_config
from utils.time_utils import format_date, format_time, format_duration

logger = logging.getLogger(__name__)


# ── SDK Compatibility Helper ──────────────────────────────────

def _safe_meta(metadata, key: str, default: str = "") -> str:
    """
    Extract a single key from a Stripe session metadata object.

    Works across ALL Stripe Python SDK versions (v4 and v5):

    SDK v4: StripeObject inherits from dict → metadata[key] works via __getitem__.
    SDK v5: StripeObject no longer inherits from dict, so:
      - dict(metadata) silently returns {} (StripeObject.__iter__ does not yield keys)
      - metadata.get("key") raises AttributeError("get") via __getattr__
      - metadata["key"] works via __getitem__ which IS defined in all versions
      - getattr(metadata, "key") works via __getattr__ as a field-lookup fallback

    We never call .get() on the raw StripeObject.  We never call dict() on it.
    We go key-by-key using __getitem__ then getattr as a fallback.
    """
    if not metadata:
        return default
    # Primary: __getitem__ — defined on StripeObject in all SDK versions
    try:
        val = metadata[key]
        if val is not None:
            return str(val)
        return default
    except (KeyError, IndexError):
        pass   # Key not present — fall through to attribute access
    except Exception:
        pass   # Unexpected error — try next strategy
    # Fallback: attribute-style access (v5 __getattr__ delegates to inner dict)
    try:
        val = getattr(metadata, key, None)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return default


# ── Client Setup ─────────────────────────────────────────────

def _init_stripe() -> None:
    """Configure Stripe with the secret key. Called before any Stripe API call."""
    config = get_config()
    stripe.api_key = config.stripe_secret_key


# ── Custom Exceptions ─────────────────────────────────────────

class PaymentError(Exception):
    """Raised when a payment operation fails with a user-safe message."""


class PaymentVerificationError(PaymentError):
    """Raised when Stripe session verification fails."""


# ── Checkout Session Creation ─────────────────────────────────

def create_checkout_session(
    hold: dict,
    price_info: dict,
    court: dict,
    booking_date,           # datetime.date
    user_email: str,
    app_url: str,
    notes: str = "",
) -> dict:
    """
    Create a Stripe Checkout session for a confirmed booking hold.

    Steps:
    1. Build line items from price breakdown
    2. Create Stripe session with hold metadata
    3. Update hold record with stripe_session_id (for correlation)
    4. Return {"url": checkout_url, "session_id": stripe_session_id}

    Args:
        hold:         Booking hold record from the database
        price_info:   Output of pricing_service.calculate_price()
        court:        Court record (for product name/description)
        booking_date: Date of the booking (local)
        user_email:   Pre-fill email on Stripe checkout
        app_url:      Base URL of the app (from config)
        notes:        User-entered booking notes (stored in metadata)

    Raises:
        PaymentError: on Stripe API failures or invalid amounts
    """
    _init_stripe()

    court_name = court.get("name", "Court")
    sport = (court.get("sport_type") or "").title()
    duration_minutes = int(hold.get("duration_minutes", 60))

    # Human-readable product details shown on Stripe checkout
    product_name = f"Court Booking — {court_name}"
    product_description = (
        f"{format_date(booking_date)} · "
        f"{format_duration(duration_minutes)}"
        + (f" · {sport}" if sport else "")
    )

    total_amount = float(price_info.get("total_amount", 0))
    if total_amount <= 0:
        raise PaymentError(
            "Cannot process a $0 payment through Stripe. "
            "Please contact the facility for free-of-charge bookings."
        )

    # Stripe uses integer cents — convert carefully to avoid float rounding
    total_cents = round(total_amount * 100)

    # Build line items. We use a single line item representing the full booking.
    # Discount/tax breakdown is shown on our own pricing summary, not on Stripe.
    line_items = [
        {
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": product_name,
                    "description": product_description,
                },
                "unit_amount": total_cents,
            },
            "quantity": 1,
        }
    ]

    # success_url: Stripe replaces {CHECKOUT_SESSION_ID} with the actual session ID.
    # In Python f-strings, {{ }} produces literal { } in the output.
    # Result: "{app_url}/payment-success?session_id={CHECKOUT_SESSION_ID}"
    # Streamlit reads session_id from st.query_params on the payment-success page.
    success_url = f"{app_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"

    # cancel_url: User cancelled on Stripe → return to book page so we can
    # release the hold immediately.  The hold_id is passed as a query param so
    # book.py can expire it without relying on session_state (which may be
    # lost after the Stripe redirect).
    cancel_url = f"{app_url}/book?stripe_cancelled=1&hold_id={hold['id']}"

    # Metadata passed through Stripe — we read these back in payment_success.py
    metadata = {
        "hold_id":      hold["id"],
        "facility_id":  hold["facility_id"],
        "court_id":     hold["court_id"],
        "user_id":      hold["user_id"],
        "booking_date": hold["booking_date"],
        "app":          "sportsplex",       # Identify our bookings in Stripe dashboard
    }
    if notes:
        metadata["notes"] = notes[:500]    # Stripe metadata values max 500 chars

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=user_email,
            metadata=metadata,
            # payment_intent_data: attach metadata to the PaymentIntent too
            # so it's visible in the Stripe dashboard without drilling into the session
            payment_intent_data={
                "metadata": metadata,
                "description": product_description,
            },
        )
    except stripe.AuthenticationError:
        logger.error("Stripe authentication failed — check STRIPE_SECRET_KEY")
        raise PaymentError("Payment system configuration error. Please contact support.")
    except stripe.InvalidRequestError as e:
        logger.error(f"Stripe invalid request: {e}")
        raise PaymentError(f"Payment request error: {e.user_message or str(e)}")
    except stripe.StripeError as e:
        logger.error(f"Stripe API error creating session: {e}")
        raise PaymentError("Payment service temporarily unavailable. Please try again.")

    # Record the Stripe session ID on the hold so we can look it up later
    _link_stripe_session_to_hold(hold["id"], session.id)

    logger.info(
        f"Created Stripe session {session.id} for hold {hold['id']} "
        f"— amount ${total_amount:.2f}"
    )

    return {
        "url": session.url,
        "session_id": session.id,
    }


# ── Payment Verification ──────────────────────────────────────

def verify_payment_session(session_id: str) -> dict:
    """
    Retrieve and verify a Stripe Checkout session via the Stripe API.

    ⚠️  SECURITY: This is the authoritative check. The session_id in the URL
    proves the user went through Stripe's redirect, but NOT that they paid.
    We MUST verify payment_status server-side.

    Args:
        session_id: The Stripe Checkout session ID (starts with 'cs_')

    Returns:
        {
            "paid":                bool,
            "session_id":          str,
            "payment_status":      str,       # "paid" | "unpaid" | "no_payment_required"
            "payment_intent_id":   str | None,
            "hold_id":             str | None, # From session metadata
            "user_id":             str | None, # From session metadata
            "facility_id":         str | None,
            "amount_total_dollars":float,      # Stripe amount_total ÷ 100
            "customer_email":      str | None,
            "error":               str | None, # Set if something went wrong
        }
    """
    _init_stripe()

    if not session_id or not session_id.startswith("cs_"):
        return {"paid": False, "error": "Invalid session ID format."}

    try:
        # expand=["payment_intent"] fetches the PaymentIntent in one call
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["payment_intent"],
        )
    except stripe.InvalidRequestError:
        return {"paid": False, "error": "Payment session not found."}
    except stripe.StripeError as e:
        logger.error(f"Stripe API error verifying session {session_id}: {e}")
        return {"paid": False, "error": "Payment verification temporarily unavailable."}

    # Read metadata key-by-key using _safe_meta so we never call .get() or
    # dict() on the raw StripeObject — both of those break in Stripe SDK v5
    # (dict() silently returns {}, .get() raises AttributeError("get")).
    raw_meta = session.metadata

    paid = session.payment_status == "paid"

    # Extract payment_intent_id safely (may be expanded object or string)
    pi = session.payment_intent
    payment_intent_id = pi.id if hasattr(pi, "id") else (pi if isinstance(pi, str) else None)

    hold_id     = _safe_meta(raw_meta, "hold_id")     or None
    user_id     = _safe_meta(raw_meta, "user_id")     or None
    facility_id = _safe_meta(raw_meta, "facility_id") or None
    notes       = _safe_meta(raw_meta, "notes", "")

    logger.debug(
        f"verify_payment_session: session={session.id} paid={paid} "
        f"hold_id={hold_id!r} user_id={user_id!r}"
    )

    return {
        "paid":                 paid,
        "session_id":           session.id,
        "payment_status":       session.payment_status,
        "payment_intent_id":    payment_intent_id,
        "hold_id":              hold_id,
        "user_id":              user_id,
        "facility_id":          facility_id,
        "amount_total_dollars": (session.amount_total or 0) / 100.0,
        "customer_email":       session.customer_email,
        "notes":                notes,
        "error":                None,
    }


def process_successful_payment(
    stripe_session_id: str,
    current_user_id: str,
    price_info: Optional[dict] = None,
) -> dict:
    """
    Full payment verification + booking confirmation pipeline.

    Called from payment_success.py after Stripe redirects back.

    Steps:
    1. Check if this session_id has already been processed (idempotency)
    2. Verify Stripe session payment_status == "paid"
    3. Security: verify metadata.user_id matches current_user_id
    4. Confirm booking via booking_service.confirm_booking_from_hold()
    5. Update payment record
    6. Return confirmed booking

    Args:
        stripe_session_id: From URL query param (st.query_params["session_id"])
        current_user_id:   ID of the currently logged-in user
        price_info:        Price breakdown (from session_state; may be None if page refreshed)

    Returns:
        {
            "success":  bool,
            "booking":  dict | None,
            "error":    str | None,
            "already_confirmed": bool,   # True if this is an idempotent retry
        }

    Raises:
        PaymentVerificationError: on critical verification failures
    """
    # ── Step 1: Idempotency check ────────────────────────────
    # Check if this Stripe session has already been confirmed
    existing_booking = _get_booking_by_stripe_session(stripe_session_id)
    if existing_booking and existing_booking.get("status") == "confirmed":
        logger.info(f"Idempotent: session {stripe_session_id} already confirmed booking {existing_booking['id']}")
        return {
            "success": True,
            "booking": existing_booking,
            "error": None,
            "already_confirmed": True,
        }

    # ── Step 2: Verify with Stripe ────────────────────────────
    verification = verify_payment_session(stripe_session_id)

    if verification.get("error"):
        return {
            "success": False,
            "booking": None,
            "error": verification["error"],
            "already_confirmed": False,
        }

    if not verification["paid"]:
        status = verification.get("payment_status", "unknown")
        return {
            "success": False,
            "booking": None,
            "error": (
                f"Payment not completed (status: {status}). "
                "If you were charged, please contact support immediately."
            ),
            "already_confirmed": False,
        }

    # ── Step 3: Security — verify user matches ───────────────
    metadata_user_id = verification.get("user_id", "")
    if metadata_user_id and str(metadata_user_id) != str(current_user_id):
        logger.error(
            f"User ID mismatch! Session metadata has {metadata_user_id}, "
            f"current user is {current_user_id}. Session: {stripe_session_id}"
        )
        raise PaymentVerificationError(
            "Security check failed — this payment session does not belong to your account. "
            "Please contact support."
        )

    hold_id = verification.get("hold_id")
    if not hold_id:
        raise PaymentVerificationError(
            "Booking reference not found in payment session. "
            "Your payment was captured. Please contact support with your payment receipt."
        )

    # ── Step 4: Confirm booking ──────────────────────────────
    from services.booking_service import confirm_booking_from_hold, BookingError, BookingConflictError

    # Build price_info from Stripe data if not available in session_state
    if not price_info:
        price_info = {
            "base_amount":     verification["amount_total_dollars"],
            "discount_amount": 0.0,
            "total_amount":    verification["amount_total_dollars"],
        }

    try:
        booking = confirm_booking_from_hold(
            hold_id=hold_id,
            stripe_checkout_session_id=stripe_session_id,
            stripe_payment_intent_id=verification.get("payment_intent_id") or "",
            pricing_result=price_info,
            notes=verification.get("notes", ""),
            # Payment is already captured by Stripe — bypass the hold expiry
            # guard so a slow checkout or session-loss recovery never blocks
            # an otherwise valid booking confirmation.
            bypass_expiry_check=True,
        )

        logger.info(
            f"Booking confirmed: {booking['id']} from Stripe session {stripe_session_id}"
        )

        return {
            "success": True,
            "booking": booking,
            "error": None,
            "already_confirmed": False,
        }

    except BookingConflictError as e:
        # Slot was taken between hold creation and confirmation
        # Payment is captured — this MUST trigger a refund
        logger.error(
            f"Conflict after payment for session {stripe_session_id}: {e}. "
            f"Need to refund payment_intent {verification.get('payment_intent_id')}"
        )
        _auto_refund_on_conflict(
            payment_intent_id=verification.get("payment_intent_id"),
            session_id=stripe_session_id,
        )
        return {
            "success": False,
            "booking": None,
            "error": (
                "⚠️ A booking conflict was detected after your payment was processed. "
                "We've automatically initiated a full refund — please allow 5–10 business days. "
                "We sincerely apologise for the inconvenience."
            ),
            "already_confirmed": False,
        }

    except BookingError as e:
        logger.error(f"Booking confirmation failed for session {stripe_session_id}: {e}")
        return {
            "success": False,
            "booking": None,
            "error": str(e),
            "already_confirmed": False,
        }


# ── Refunds ───────────────────────────────────────────────────

def issue_refund(
    stripe_payment_intent_id: str,
    amount_dollars: float = 0.0,    # 0 = full refund
    reason: str = "requested_by_customer",
) -> dict:
    """
    Issue a full or partial refund via Stripe.

    Args:
        stripe_payment_intent_id: From the payments table
        amount_dollars: Amount to refund (0 = full refund of what was charged)
        reason: "requested_by_customer" | "duplicate" | "fraudulent"

    Returns:
        {"success": bool, "refund_id": str | None, "amount_dollars": float, "error": str | None}
    """
    _init_stripe()

    refund_params: dict = {
        "payment_intent": stripe_payment_intent_id,
        "reason": reason,
    }
    if amount_dollars > 0:
        refund_params["amount"] = round(amount_dollars * 100)  # Cents

    try:
        refund = stripe.Refund.create(**refund_params)
        logger.info(
            f"Refund {refund.id} created: ${(refund.amount or 0) / 100:.2f} "
            f"for payment intent {stripe_payment_intent_id}"
        )
        return {
            "success": True,
            "refund_id": refund.id,
            "status": refund.status,
            "amount_dollars": (refund.amount or 0) / 100.0,
            "error": None,
        }
    except stripe.InvalidRequestError as e:
        logger.error(f"Stripe refund invalid request: {e}")
        return {"success": False, "refund_id": None, "amount_dollars": 0, "error": str(e)}
    except stripe.StripeError as e:
        logger.error(f"Stripe refund failed: {e}")
        return {
            "success": False,
            "refund_id": None,
            "amount_dollars": 0,
            "error": "Refund failed. Please contact support — your refund will be processed manually.",
        }


def process_cancellation_refund(
    booking_id: str,
    user_id: str,
    access_token: str,
    refresh_token: str,
) -> dict:
    """
    Cancel a booking and issue the appropriate Stripe refund.

    Combines:
      1. booking_service.cancel_booking() → determines refund amount
      2. Get payment record → get payment_intent_id
      3. issue_refund() → execute Stripe refund

    Returns:
        {
            "success":        bool,
            "booking":        dict,
            "refund_amount":  float,
            "refund_label":   str,
            "message":        str,
        }
    """
    from services.booking_service import cancel_booking, BookingError
    from db.supabase_client import get_client
    from db.queries import get_payment_by_booking

    # Step 1: Cancel the booking in our DB (determines refund amount)
    try:
        cancellation = cancel_booking(
            access_token=access_token,
            refresh_token=refresh_token,
            booking_id=booking_id,
            user_id=user_id,
        )
    except BookingError as e:
        return {"success": False, "message": str(e)}

    refund_amount = cancellation["refund_amount"]
    refund_label = cancellation["refund_label"]

    if refund_amount <= 0:
        return {
            "success": True,
            "booking": cancellation["booking"],
            "refund_amount": 0,
            "refund_label": refund_label,
            "message": cancellation["message"],
        }

    # Step 2: Find the Stripe payment intent for this booking
    client = get_client(access_token, refresh_token)
    payment = get_payment_by_booking(client, booking_id)

    if not payment or not payment.get("stripe_payment_intent_id"):
        # Booking cancelled but no Stripe record — may be a test/admin booking
        logger.warning(f"No Stripe payment found for booking {booking_id}; skipping refund")
        return {
            "success": True,
            "booking": cancellation["booking"],
            "refund_amount": 0,
            "refund_label": "No payment found — contact support if you were charged.",
            "message": "Booking cancelled. Please contact support if a refund is owed.",
        }

    payment_intent_id = payment["stripe_payment_intent_id"]

    # Step 3: Issue Stripe refund
    refund_result = issue_refund(
        stripe_payment_intent_id=payment_intent_id,
        amount_dollars=refund_amount,
        reason="requested_by_customer",
    )

    if refund_result["success"]:
        # Update payment record with refund info
        _update_payment_refund_record(
            payment_id=payment["id"],
            refund_amount=refund_result["amount_dollars"],
        )
        message = (
            f"Booking cancelled. A refund of **${refund_result['amount_dollars']:.2f}** "
            f"has been initiated and should appear within 5–10 business days."
        )
    else:
        message = (
            f"Booking cancelled, but the automated refund failed: {refund_result['error']} "
            "Please contact support to process your refund manually."
        )

    return {
        "success": True,
        "booking": cancellation["booking"],
        "refund_amount": refund_result.get("amount_dollars", 0),
        "refund_label": refund_label,
        "message": message,
    }


# ── Private Helpers ───────────────────────────────────────────

def _link_stripe_session_to_hold(hold_id: str, stripe_session_id: str) -> None:
    """Record the Stripe session ID on the booking hold for traceability."""
    try:
        admin_client = get_admin_client()
        admin_client.table("booking_holds").update({
            "stripe_session_id": stripe_session_id,
        }).eq("id", hold_id).execute()
    except Exception as e:
        # Non-critical — session ID is also in Stripe metadata
        logger.warning(f"Could not link Stripe session to hold {hold_id}: {e}")


def _get_booking_by_stripe_session(stripe_session_id: str) -> Optional[dict]:
    """Look up a booking by its Stripe session ID (for idempotency)."""
    try:
        admin_client = get_admin_client()
        response = (
            admin_client.table("bookings")
            .select("*, courts(name, sport_type, facilities(name, timezone))")
            .eq("stripe_checkout_session_id", stripe_session_id)
            .maybe_single()
            .execute()
        )
        return response.data
    except Exception:
        return None


def _update_payment_refund_record(payment_id: str, refund_amount: float) -> None:
    """Update the payment record with refund details."""
    try:
        admin_client = get_admin_client()
        original = (
            admin_client.table("payments")
            .select("amount, refunded_amount")
            .eq("id", payment_id)
            .maybe_single()
            .execute()
        )
        if not original.data:
            return

        original_amount = float(original.data.get("amount", 0))
        new_refunded = float(original.data.get("refunded_amount", 0)) + refund_amount
        is_full_refund = abs(new_refunded - original_amount) < 0.01

        admin_client.table("payments").update({
            "refunded_amount": round(new_refunded, 2),
            "payment_status":  "refunded" if is_full_refund else "partial_refund",
            "refund_status":   "full"    if is_full_refund else "partial",
        }).eq("id", payment_id).execute()
    except Exception as e:
        logger.error(f"Failed to update payment refund record {payment_id}: {e}")


def _auto_refund_on_conflict(
    payment_intent_id: Optional[str],
    session_id: str,
) -> None:
    """
    Emergency auto-refund when a booking conflict is detected post-payment.
    This is a last-resort safeguard — it should be extremely rare due to
    the hold mechanism and DB exclusion constraints.
    """
    if not payment_intent_id:
        logger.error(
            f"CRITICAL: Conflict on session {session_id} but no payment_intent_id — "
            "cannot auto-refund. Manual intervention required."
        )
        return

    result = issue_refund(
        stripe_payment_intent_id=payment_intent_id,
        amount_dollars=0,           # Full refund
        reason="duplicate",
    )
    if result["success"]:
        logger.info(
            f"Auto-refund successful for conflict on session {session_id}: "
            f"${result['amount_dollars']:.2f} refunded"
        )
    else:
        logger.error(
            f"CRITICAL: Auto-refund FAILED for session {session_id}! "
            f"Error: {result['error']}. Manual refund required."
        )
