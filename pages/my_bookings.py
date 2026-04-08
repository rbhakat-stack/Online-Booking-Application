"""
My Bookings Page
=================
Authenticated users view, manage, and cancel their bookings here.

Tab structure:
  • Upcoming — confirmed + pending_payment, start_time_utc >= now
  • Past      — all bookings with start_time_utc < now, plus cancelled/refunded

Cancellation flow:
  1. User clicks "Cancel Booking" on a card
  2. A confirmation panel appears (with refund policy preview)
  3. User confirms → process_cancellation_refund() called
  4. Success/failure banner shown; booking list refreshes

Design notes:
  - Booking list is fetched fresh on every render (st.cache_data not used
    because Streamlit session_state mutations must trigger a list refresh).
  - Pagination: default 20 bookings per tab; "Load More" appends 20 more.
  - Cancellation state is stored in session_state so it survives the rerun
    triggered by the confirmation button.
"""

import streamlit as st

from components.auth_guard import show_auth_status_sidebar
from components.booking_card import render_booking_card
from services.auth_service import get_auth_service
from services.booking_service import get_user_bookings, get_booking_detail, BookingError
from services.payment_service import process_cancellation_refund, PaymentError
from utils.time_utils import (
    parse_iso_datetime,
    utc_to_local,
    format_date,
    format_time,
    format_duration,
    hours_until_booking,
    get_refund_policy_for_cancellation,
)
from utils.constants import BookingStatus, RefundPolicy

_PAGE_SIZE = 20


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    auth_service.load_session_from_state()

    if not auth_service.is_authenticated():
        st.warning("Please log in to view your bookings.")
        if st.button("Log In", type="primary"):
            st.switch_page("pages/login.py")
        return

    user = auth_service.get_current_user()
    user_id = str(user.id)
    access_token = st.session_state.get("access_token", "")
    refresh_token = st.session_state.get("refresh_token", "")

    st.markdown("## 📋 My Bookings")

    # ── Post-cancellation banner (shown once then cleared) ────
    _show_cancellation_result_banner()

    # ── Cancel confirmation panel ─────────────────────────────
    cancel_booking_id = st.session_state.get("_cancel_booking_id")
    if cancel_booking_id:
        _render_cancel_confirmation(
            booking_id=cancel_booking_id,
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────
    tab_upcoming, tab_past = st.tabs(["Upcoming", "Past"])

    with tab_upcoming:
        _render_upcoming_tab(user_id, access_token, refresh_token)

    with tab_past:
        _render_past_tab(user_id, access_token, refresh_token)


# ── Tab Content ───────────────────────────────────────────────

def _render_upcoming_tab(user_id: str, access_token: str, refresh_token: str):
    """Shows upcoming confirmed + pending_payment bookings."""
    limit = st.session_state.get("_upcoming_limit", _PAGE_SIZE)

    try:
        bookings = get_user_bookings(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
            statuses=[BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT],
            upcoming_only=True,
            limit=limit + 1,    # Fetch one extra to detect if more exist
        )
    except Exception as e:
        st.error(f"Could not load bookings: {e}")
        return

    has_more = len(bookings) > limit
    bookings = bookings[:limit]

    if not bookings:
        _render_empty_state(
            icon="🎾",
            title="No upcoming bookings",
            message="You don't have any upcoming court reservations.",
            cta_label="Book a Court",
            cta_page="pages/availability.py",
        )
        return

    st.markdown(
        f"<div style='color:#6b7280;font-size:0.9rem;margin-bottom:0.75rem'>"
        f"Showing {len(bookings)} upcoming booking{'s' if len(bookings) != 1 else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    for booking in bookings:
        _render_booking_with_detail(booking, cancellable=True)

    if has_more:
        if st.button("Load More", key="upcoming_load_more"):
            st.session_state["_upcoming_limit"] = limit + _PAGE_SIZE
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Book Another Court", type="primary", key="upcoming_book_cta"):
        st.switch_page("pages/availability.py")


def _render_past_tab(user_id: str, access_token: str, refresh_token: str):
    """Shows past and cancelled bookings."""
    limit = st.session_state.get("_past_limit", _PAGE_SIZE)

    try:
        bookings = get_user_bookings(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
            statuses=BookingStatus.VISIBLE_STATUSES,
            upcoming_only=False,
            limit=limit + 1,
        )
    except Exception as e:
        st.error(f"Could not load bookings: {e}")
        return

    # Past = everything that already started or is cancelled/refunded
    from utils.time_utils import now_utc
    past_bookings = []
    for b in bookings:
        status = b.get("status", "")
        start_utc = parse_iso_datetime(str(b.get("start_time_utc", "")))
        is_past = start_utc and start_utc <= now_utc()
        is_terminal = status in (BookingStatus.CANCELLED, BookingStatus.REFUNDED, BookingStatus.NO_SHOW)
        if is_past or is_terminal:
            past_bookings.append(b)

    has_more = len(bookings) > limit
    past_bookings = past_bookings[:limit]

    if not past_bookings:
        _render_empty_state(
            icon="📂",
            title="No past bookings",
            message="Your booking history will appear here once you have completed a session.",
            cta_label="Book Your First Court",
            cta_page="pages/availability.py",
        )
        return

    st.markdown(
        f"<div style='color:#6b7280;font-size:0.9rem;margin-bottom:0.75rem'>"
        f"Showing {len(past_bookings)} past booking{'s' if len(past_bookings) != 1 else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    for booking in past_bookings:
        status = booking.get("status", "")
        cancellable = status in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT)
        _render_booking_with_detail(booking, cancellable=cancellable)

    if has_more:
        if st.button("Load More", key="past_load_more"):
            st.session_state["_past_limit"] = limit + _PAGE_SIZE
            st.rerun()


# ── Booking Row with Inline Detail ────────────────────────────

def _render_booking_with_detail(booking: dict, cancellable: bool):
    """
    Render a booking card. When the user clicks "View Details", expand
    an inline panel below the card. When they click "Cancel Booking",
    set _cancel_booking_id in session_state and rerun.
    """
    booking_id = str(booking.get("id", ""))
    show_detail_key = f"_detail_{booking_id}"

    def on_details_click(bid: str):
        # Toggle detail panel
        current = st.session_state.get(show_detail_key, False)
        st.session_state[show_detail_key] = not current
        st.rerun()

    def on_cancel_click(bid: str):
        # Clear any previously open cancel panel first
        if st.session_state.get("_cancel_booking_id") == bid:
            st.session_state.pop("_cancel_booking_id", None)
        else:
            st.session_state["_cancel_booking_id"] = bid
        st.rerun()

    render_booking_card(
        booking=booking,
        show_cancel_button=cancellable,
        on_cancel_click=on_cancel_click if cancellable else None,
        on_details_click=on_details_click,
    )

    # Inline detail panel
    if st.session_state.get(show_detail_key, False):
        _render_booking_detail_panel(booking)


def _render_booking_detail_panel(booking: dict):
    """Expandable detail card beneath a booking row."""
    court_data = booking.get("courts") or {}
    facility_data = court_data.get("facilities") or {}
    timezone = facility_data.get("timezone", "America/New_York")

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

    booking_id_short = str(booking.get("id", ""))[:8].upper()
    stripe_session = booking.get("stripe_checkout_session_id", "")
    stripe_intent = booking.get("stripe_payment_intent_id", "")
    base = float(booking.get("base_amount", 0))
    discount = float(booking.get("discount_amount", 0))
    total = float(booking.get("total_amount", 0))
    duration_min = booking.get("duration_minutes", 0)
    notes = booking.get("notes", "") or ""
    status = booking.get("status", "")
    indoor = court_data.get("indoor", True)

    with st.container():
        st.markdown(
            f"""
            <div style="
                background:#f8f9ff;border-radius:10px;
                border:1px solid #e0e0f0;padding:1.25rem 1.5rem;
                margin:-0.5rem 0 0.75rem 0;
            ">
            <div style="font-weight:700;color:#1a1a2e;margin-bottom:0.75rem;
                        border-bottom:1px solid #e0e0f0;padding-bottom:0.5rem">
                Booking Details
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.6rem;font-size:0.875rem">
                <div><span style='color:#6b7280'>Date:</span> <strong>{date_str}</strong></div>
                <div><span style='color:#6b7280'>Time:</span> <strong>{time_str} – {end_str}</strong></div>
                <div><span style='color:#6b7280'>Duration:</span> <strong>{format_duration(duration_min)}</strong></div>
                <div><span style='color:#6b7280'>Court:</span> <strong>{court_data.get('name', '—')}</strong></div>
                <div><span style='color:#6b7280'>Facility:</span> <strong>{facility_data.get('name', '—')}</strong></div>
                <div><span style='color:#6b7280'>Type:</span> <strong>{'Indoor' if indoor else 'Outdoor'}</strong></div>
            </div>

            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #e0e0f0;
                        font-size:0.875rem;display:grid;grid-template-columns:1fr 1fr;gap:0.4rem">
                <div><span style='color:#6b7280'>Base amount:</span> <strong>${base:.2f}</strong></div>
                <div><span style='color:#6b7280'>Discount:</span>
                    <strong style='color:#16a34a'>-${discount:.2f}</strong>
                </div>
                <div style="grid-column:1/-1;font-size:1rem">
                    <span style='color:#6b7280'>Total paid:</span>
                    <strong style='color:#4361ee'>${total:.2f}</strong>
                </div>
            </div>

            {"<div style='margin-top:0.6rem;font-size:0.85rem;color:#6b7280'><em>" + notes + "</em></div>" if notes else ""}

            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #e0e0f0;
                        font-size:0.75rem;color:#9ca3af">
                <div>Booking ref: <code>#{booking_id_short}</code></div>
                {"<div>Payment: <code>" + stripe_session[:20] + "…</code></div>" if stripe_session else ""}
            </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Refund estimate for cancellable upcoming bookings
        if status in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT) and start_utc:
            hours_left = hours_until_booking(start_utc)
            if hours_left > 0:
                policy = get_refund_policy_for_cancellation(hours_left)
                refund_amount = round(total * policy["refund_percent"], 2)
                icon = "✅" if policy["eligible"] else "⚠️"
                st.info(
                    f"{icon} **Cancellation policy:** {policy['label']}\n\n"
                    + (
                        f"If cancelled now: **${refund_amount:.2f}** refunded to your original payment method."
                        if policy["eligible"]
                        else "No refund is available for cancellations within 12 hours of your session."
                    )
                )


# ── Cancellation Confirmation ──────────────────────────────────

def _render_cancel_confirmation(
    booking_id: str,
    user_id: str,
    access_token: str,
    refresh_token: str,
):
    """
    Inline cancellation confirmation panel.
    Shown when the user has clicked "Cancel Booking" on a card.
    Displays the applicable refund policy before the user confirms.
    """
    try:
        booking = get_booking_detail(access_token, refresh_token, booking_id, user_id)
    except Exception:
        booking = None

    if not booking:
        st.error("Booking not found or already cancelled.")
        st.session_state.pop("_cancel_booking_id", None)
        return

    court_data = booking.get("courts") or {}
    facility_data = court_data.get("facilities") or {}
    timezone = facility_data.get("timezone", "America/New_York")
    start_utc = parse_iso_datetime(str(booking.get("start_time_utc", "")))
    local_start = utc_to_local(start_utc, timezone) if start_utc else None
    total = float(booking.get("total_amount", 0))

    hours_left = hours_until_booking(start_utc) if start_utc else 0
    policy = get_refund_policy_for_cancellation(hours_left)
    refund_amount = round(total * policy["refund_percent"], 2)

    date_str = format_date(local_start.date()) if local_start else "—"
    time_str = format_time(local_start.time()) if local_start else "—"

    st.markdown(
        f"""
        <div style="
            background:#fff7ed;border:2px solid #fb923c;
            border-radius:12px;padding:1.25rem 1.5rem;margin-bottom:0.5rem;
        ">
            <div style="font-size:1.1rem;font-weight:800;color:#c2410c;margin-bottom:0.5rem">
                Cancel Booking?
            </div>
            <div style="font-size:0.9rem;color:#1a1a2e;margin-bottom:0.75rem">
                <strong>{court_data.get('name', 'Court')}</strong> at
                <strong>{facility_data.get('name', 'Facility')}</strong><br>
                {date_str} &middot; {time_str} &middot; ${total:.2f} paid
            </div>
            <div style="background:#fff;border-radius:8px;padding:0.75rem;
                        border:1px solid #fed7aa;font-size:0.875rem">
                <strong>Refund policy:</strong> {policy['label']}<br>
                <strong>{"You will receive: $" + str(refund_amount) if policy["eligible"] else "No refund applies."}</strong>
                {"" if not policy["eligible"] else
                 "<br><span style='color:#6b7280;font-size:0.8rem'>Refunds typically appear within 5–10 business days.</span>"}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_confirm, col_keep = st.columns(2)
    with col_confirm:
        if st.button(
            "Yes, Cancel Booking",
            type="primary",
            key=f"confirm_cancel_{booking_id}",
            use_container_width=True,
        ):
            _execute_cancellation(booking_id, user_id, access_token, refresh_token)

    with col_keep:
        if st.button(
            "Keep My Booking",
            key=f"keep_{booking_id}",
            use_container_width=True,
        ):
            st.session_state.pop("_cancel_booking_id", None)
            st.rerun()


def _execute_cancellation(
    booking_id: str,
    user_id: str,
    access_token: str,
    refresh_token: str,
):
    """
    Call process_cancellation_refund and store the result in session_state
    to display a banner after the rerun.
    """
    with st.spinner("Cancelling booking and processing refund…"):
        try:
            result = process_cancellation_refund(
                booking_id=booking_id,
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            st.session_state["_cancel_result"] = {
                "success": True,
                "message": result["message"],
                "refund_amount": result.get("refund_amount", 0),
            }
        except (BookingError, PaymentError, Exception) as e:
            st.session_state["_cancel_result"] = {
                "success": False,
                "message": str(e),
            }

    # Clear the confirmation state regardless of outcome
    st.session_state.pop("_cancel_booking_id", None)
    # Reset pagination so the list refreshes
    st.session_state.pop("_upcoming_limit", None)
    st.session_state.pop("_past_limit", None)
    st.rerun()


# ── Post-Cancellation Banner ──────────────────────────────────

def _show_cancellation_result_banner():
    """Show a one-time success/failure banner after a cancellation completes."""
    result = st.session_state.pop("_cancel_result", None)
    if not result:
        return

    if result["success"]:
        st.success(result["message"])
    else:
        st.error(f"**Cancellation failed:** {result['message']}")


# ── Empty State ───────────────────────────────────────────────

def _render_empty_state(
    icon: str,
    title: str,
    message: str,
    cta_label: str,
    cta_page: str,
):
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.markdown(
            f"""
            <div style="text-align:center;padding:3rem 0">
                <div style="font-size:4rem">{icon}</div>
                <h3 style="color:#1a1a2e;margin:0.75rem 0 0.25rem">{title}</h3>
                <p style="color:#6b7280">{message}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(cta_label, type="primary", use_container_width=True):
            st.switch_page(cta_page)


render()
