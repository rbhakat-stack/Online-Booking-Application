"""
Booking Card Component
========================
Renders a compact booking summary card for My Bookings page and admin views.
"""

import streamlit as st
from utils.time_utils import utc_to_local, parse_iso_datetime, format_date, format_time, format_duration
from utils.constants import BookingStatus


def render_booking_card(
    booking: dict,
    show_cancel_button: bool = True,
    on_cancel_click=None,
    on_details_click=None,
) -> None:
    """
    Render a compact booking card.

    Args:
        booking:             Booking dict (with nested courts + facilities)
        show_cancel_button:  Whether to show the cancel button
        on_cancel_click:     Callback when cancel is clicked (receives booking_id)
        on_details_click:    Callback when "View Details" is clicked
    """
    court_data = booking.get("courts") or {}
    facility_data = court_data.get("facilities") or {}
    timezone = facility_data.get("timezone", "America/New_York")

    # Parse times
    start_utc = parse_iso_datetime(str(booking.get("start_time_utc", "")))
    end_utc = parse_iso_datetime(str(booking.get("end_time_utc", "")))

    if start_utc:
        local_start = utc_to_local(start_utc, timezone)
        date_str = format_date(local_start.date())
        time_str = f"{format_time(local_start.time())} – {format_time(utc_to_local(end_utc, timezone).time()) if end_utc else '?'}"
    else:
        date_str = booking.get("booking_date", "—")
        time_str = "Time unavailable"

    duration_min = booking.get("duration_minutes", 0)
    status = booking.get("status", "unknown")
    total = float(booking.get("total_amount", 0))

    # Status badge colour
    badge_colors = {
        "confirmed":        ("#d1fae5", "#065f46"),
        "pending_payment":  ("#dbeafe", "#1e40af"),
        "cancelled":        ("#fee2e2", "#991b1b"),
        "refunded":         ("#ede9fe", "#5b21b6"),
        "hold":             ("#fef3c7", "#92400e"),
        "expired":          ("#f3f4f6", "#4b5563"),
        "no_show":          ("#fee2e2", "#991b1b"),
        "blocked":          ("#f3f4f6", "#4b5563"),
    }
    badge_bg, badge_text = badge_colors.get(status, ("#f3f4f6", "#4b5563"))
    status_label = BookingStatus.LABELS.get(status, status.replace("_", " ").title())

    sport_icons = {
        "pickleball": "🏓", "badminton": "🏸", "tennis": "🎾",
        "karate": "🥋", "multi-sport": "🏅",
    }
    sport_type = court_data.get("sport_type", "")
    sport_icon = sport_icons.get(sport_type, "🏟️")
    court_name = court_data.get("name", "Court")
    facility_name = facility_data.get("name", "Facility")

    booking_id = booking.get("id", "")

    st.markdown(
        f"""
        <div style="
            background:#ffffff;border-radius:12px;
            padding:1rem 1.25rem;margin-bottom:0.75rem;
            border:1px solid #e5e7eb;
            box-shadow:0 1px 4px rgba(0,0,0,0.04);
        ">
            <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div style="display:flex;gap:0.75rem;align-items:center">
                    <span style="font-size:2rem">{sport_icon}</span>
                    <div>
                        <div style="font-weight:700;color:#1a1a2e">{court_name}</div>
                        <div style="font-size:0.82rem;color:#6b7280">{facility_name}</div>
                    </div>
                </div>
                <span style="
                    background:{badge_bg};color:{badge_text};
                    border-radius:999px;padding:0.2rem 0.7rem;
                    font-size:0.75rem;font-weight:600;white-space:nowrap
                ">{status_label}</span>
            </div>
            <div style="margin-top:0.75rem;display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.4rem;font-size:0.875rem">
                <div><span style='color:#6b7280'>📅 </span>{date_str}</div>
                <div><span style='color:#6b7280'>⏰ </span>{time_str}</div>
                <div><span style='color:#6b7280'>⏱ </span>{format_duration(duration_min)}</div>
            </div>
            <div style="margin-top:0.5rem;font-size:0.875rem">
                <span style='color:#6b7280'>Total paid: </span>
                <strong style='color:#4361ee'>${total:.2f}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Action buttons
    if show_cancel_button and status in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT):
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button(
                "View Details",
                key=f"details_{booking_id}",
                use_container_width=True,
            ):
                if on_details_click:
                    on_details_click(booking_id)
        with col2:
            if st.button(
                "Cancel Booking",
                key=f"cancel_{booking_id}",
                use_container_width=True,
                type="secondary",
            ):
                if on_cancel_click:
                    on_cancel_click(booking_id)
