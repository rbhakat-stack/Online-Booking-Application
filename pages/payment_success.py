"""
Payment Success / Return Page
================================
Stripe redirects here after checkout with:
    ?session_id=cs_live_xxxxx

Critical security flow:
  1. Read session_id from st.query_params (set by Stripe redirect)
  2. Check idempotency: has this session already been confirmed?
  3. Call payment_service.process_successful_payment() which:
       a. Calls stripe.checkout.Session.retrieve(session_id) server-side
       b. Verifies payment_status == "paid"
       c. Verifies metadata.user_id matches current user
       d. Calls booking_service.confirm_booking_from_hold()
  4. Show booking confirmation or error page

NEVER confirm a booking based solely on reaching this URL.
The verification above is the authoritative check.

Webhook alternative (post-MVP):
  When a separate webhook handler is deployed, it will handle
  checkout.session.completed events directly and this page becomes a
  "loading..." screen that polls for booking status instead of triggering
  confirmation itself. That prevents the "closed browser" edge case.
"""

import streamlit as st
from components.auth_guard import show_auth_status_sidebar
from services.auth_service import get_auth_service
from services.payment_service import process_successful_payment, PaymentVerificationError
from utils.time_utils import (
    parse_iso_datetime,
    utc_to_local,
    format_date,
    format_time,
    format_duration,
)
from utils.constants import SessionKey


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    auth_service.load_session_from_state()

    # ── Read session_id ───────────────────────────────────────
    params = st.query_params
    session_id = params.get("session_id", "")

    # Also accept from session_state (for tab-reload edge case)
    if not session_id:
        session_id = st.session_state.get(SessionKey.STRIPE_SESSION_ID, "")

    if not session_id:
        _render_no_session()
        return

    if not str(session_id).startswith("cs_"):
        _render_invalid_session()
        return

    # ── Auth check ────────────────────────────────────────────
    if not auth_service.is_authenticated():
        # Store session_id so it survives login redirect
        st.session_state[SessionKey.STRIPE_SESSION_ID] = session_id
        st.warning(
            "Your payment was processed! Please log in to confirm your booking."
        )
        st.info("After logging in, return to this page to see your confirmation.")
        if st.button("Log In Now", type="primary"):
            st.switch_page("pages/login.py")
        return

    user = auth_service.get_current_user()

    # ── Show spinner while verifying ─────────────────────────
    with st.spinner("Verifying your payment and confirming booking…"):
        # Retrieve stored price info (available if user didn't refresh)
        price_info = st.session_state.get("_booking_price_info")

        try:
            result = process_successful_payment(
                stripe_session_id=str(session_id),
                current_user_id=str(user.id),
                price_info=price_info,
            )
        except PaymentVerificationError as e:
            _render_verification_error(str(e))
            return
        except Exception as e:
            _render_verification_error(
                f"An unexpected error occurred during verification: {e}\n\n"
                "Your payment may have been processed. Please contact support with "
                f"your session ID: `{session_id}`"
            )
            return

    # ── Handle result ─────────────────────────────────────────
    if result["success"]:
        _render_booking_confirmed(
            booking=result["booking"],
            already_confirmed=result.get("already_confirmed", False),
        )
        # Clean up session state booking flow data
        _cleanup_booking_session_state()
    else:
        _render_payment_failed(
            error=result.get("error", "Payment verification failed."),
            session_id=str(session_id),
        )


# ── Result Pages ──────────────────────────────────────────────

def _render_booking_confirmed(booking: dict, already_confirmed: bool = False):
    """Full booking confirmation page shown after successful payment."""
    court_data = booking.get("courts") or {}
    facility_data = court_data.get("facilities") or {}
    timezone = facility_data.get("timezone", "America/New_York")

    # Parse times
    start_utc = parse_iso_datetime(str(booking.get("start_time_utc", "")))
    end_utc = parse_iso_datetime(str(booking.get("end_time_utc", "")))

    if start_utc:
        local_start = utc_to_local(start_utc, timezone)
        local_end = utc_to_local(end_utc, timezone) if end_utc else None
        date_str = format_date(local_start.date())
        time_str = format_time(local_start.time())
        end_str = format_time(local_end.time()) if local_end else "?"
    else:
        date_str = booking.get("booking_date", "—")
        time_str = "—"
        end_str = "—"

    duration_min = booking.get("duration_minutes", 0)
    total = float(booking.get("total_amount", 0))
    booking_id_short = str(booking.get("id", ""))[:8].upper()
    sport_icons = {
        "pickleball": "🏓", "badminton": "🏸", "tennis": "🎾", "karate": "🥋",
    }
    sport_type = court_data.get("sport_type", "")
    sport_icon = sport_icons.get(sport_type, "🏟️")

    # ── Header ────────────────────────────────────────────────
    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        st.markdown(
            f"""
            <div style="text-align:center;padding:2rem 0 1rem">
                <div style="font-size:4rem">✅</div>
                <h2 style="color:#065f46;font-weight:800;margin:0.5rem 0">
                    {'Booking Confirmed!' if not already_confirmed else 'Already Confirmed!'}
                </h2>
                <p style="color:#6b7280">
                    {'Your court is booked and payment has been received.' if not already_confirmed
                     else 'This booking was already confirmed — you are all set!'}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Booking Details Card ──────────────────────────────────
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.markdown(
            f"""
            <div style="
                background:linear-gradient(135deg,#f0fdf4,#dcfce7);
                border:2px solid #86efac;
                border-radius:16px;
                padding:2rem;
                text-align:center;
            ">
                <div style="font-size:3rem;margin-bottom:0.5rem">{sport_icon}</div>
                <h3 style="color:#1a1a2e;margin:0 0 0.25rem">{court_data.get('name', 'Court')}</h3>
                <div style="color:#6b7280;font-size:0.9rem;margin-bottom:1.5rem">
                    {facility_data.get('name', 'SportsPlex')}
                </div>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;
                            text-align:left;background:white;border-radius:10px;
                            padding:1rem 1.5rem;margin-bottom:1rem">
                    <div>
                        <div style="color:#9ca3af;font-size:0.78rem;font-weight:600;
                                    text-transform:uppercase;letter-spacing:0.05em">Date</div>
                        <div style="font-weight:700;color:#1a1a2e;margin-top:0.2rem">{date_str}</div>
                    </div>
                    <div>
                        <div style="color:#9ca3af;font-size:0.78rem;font-weight:600;
                                    text-transform:uppercase;letter-spacing:0.05em">Time</div>
                        <div style="font-weight:700;color:#1a1a2e;margin-top:0.2rem">
                            {time_str} – {end_str}
                        </div>
                    </div>
                    <div>
                        <div style="color:#9ca3af;font-size:0.78rem;font-weight:600;
                                    text-transform:uppercase;letter-spacing:0.05em">Duration</div>
                        <div style="font-weight:700;color:#1a1a2e;margin-top:0.2rem">
                            {format_duration(duration_min)}
                        </div>
                    </div>
                    <div>
                        <div style="color:#9ca3af;font-size:0.78rem;font-weight:600;
                                    text-transform:uppercase;letter-spacing:0.05em">Total Paid</div>
                        <div style="font-weight:700;color:#4361ee;margin-top:0.2rem">
                            ${total:.2f}
                        </div>
                    </div>
                </div>

                <div style="background:white;border-radius:8px;padding:0.75rem;
                            border:1px solid #e5e7eb;font-size:0.8rem;color:#6b7280">
                    <strong>Booking Reference:</strong>
                    <span style="font-family:monospace;color:#1a1a2e"> #{booking_id_short}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── CTA Buttons ───────────────────────────────────────
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("📋 View My Bookings", use_container_width=True, type="primary"):
                st.switch_page("pages/my_bookings.py")
        with col_b:
            if st.button("🎾 Book Another Court", use_container_width=True):
                st.switch_page("pages/availability.py")

    # ── What to Bring ─────────────────────────────────────────
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.markdown("#### 📌 What to Know")
        col_i, col_j = st.columns(2)
        with col_i:
            st.info(
                "**Arrive on time**\n\n"
                "Courts are reserved for your booked time only. "
                "Please arrive a few minutes early."
            )
        with col_j:
            st.info(
                "**Cancellation**\n\n"
                "Cancel at least 24 hours before your session "
                "for a full refund via My Bookings."
            )


def _render_payment_failed(error: str, session_id: str):
    """Shown when payment verification fails or payment is not completed."""
    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        st.markdown(
            """
            <div style="text-align:center;padding:2rem 0 1rem">
                <div style="font-size:4rem">❌</div>
                <h2 style="color:#991b1b;font-weight:800;margin:0.5rem 0">
                    Payment Not Confirmed
                </h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.error(error)

        st.markdown(
            """
            **What to do next:**
            - If you were charged, please contact our support team with your payment receipt
            - If payment did not go through, you can try booking again
            - Your booking hold may have expired — you'll need to select a new slot
            """
        )

        st.markdown(
            f"<div style='font-size:0.8rem;color:#9ca3af;margin-top:0.5rem'>"
            f"Session reference: <code>{session_id[:20]}…</code></div>",
            unsafe_allow_html=True,
        )

        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🎾 Try Again", type="primary", use_container_width=True):
                st.switch_page("pages/availability.py")
        with col_b:
            if st.button("🏠 Go Home", use_container_width=True):
                st.switch_page("pages/home.py")


def _render_verification_error(error: str):
    """Shown when Stripe API verification itself fails."""
    st.error(f"**Payment Verification Error**\n\n{error}")
    st.markdown(
        "Please **do not attempt to book again** until you have confirmed with support "
        "whether your payment was processed."
    )
    if st.button("🏠 Go to Home Page"):
        st.switch_page("pages/home.py")


def _render_no_session():
    """Shown when the page is accessed without a session_id param."""
    st.markdown("## 💳 Payment Return Page")
    st.info(
        "This page is the return destination after Stripe Checkout.\n\n"
        "If you arrived here directly, please complete a booking first."
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Book a Court", type="primary", use_container_width=True):
            st.switch_page("pages/availability.py")
    with col2:
        if st.button("My Bookings", use_container_width=True):
            st.switch_page("pages/my_bookings.py")


def _render_invalid_session():
    """Shown when the session_id param has an unexpected format."""
    st.error("Invalid payment session. Please return to the home page.")
    if st.button("🏠 Go Home"):
        st.switch_page("pages/home.py")


# ── Cleanup ───────────────────────────────────────────────────

def _cleanup_booking_session_state():
    """Remove booking flow state after confirmation."""
    for key in [
        "_booking_slot", "_booking_price_info", "_booking_court",
        "active_hold", "booking_idempotency_key", "booking_notes",
        "stripe_checkout_url",
        SessionKey.SELECTED_COURT_ID,
        SessionKey.SELECTED_START_TIME,
        "_avail_selected_start_utc",
        "_avail_selected_slot",
    ]:
        st.session_state.pop(key, None)
    # Keep STRIPE_SESSION_ID a bit longer so the page can show idempotent results
    # It will be cleared on next availability search


render()
