"""
Slot Selector Component
=========================
Renders an interactive time-slot grid.

Two modes:
  1. Combined (auto-assign) — shows a grid of time slots; user picks a time.
     The court is assigned automatically when they proceed to book.
  2. Per-court — shows a court × time matrix (for admins or when auto-assign is off).

Streamlit limitation:
  Buttons don't maintain visual "selected" state across reruns natively.
  We work around this by storing the selected slot in session_state and using
  CSS classes to colour selected vs. unselected buttons.

  Pattern:
    - Each slot button has a unique key
    - On click, we write to st.session_state and call st.rerun()
    - On rerender, the selected slot shows with different styling (via st.markdown hack)
"""

from datetime import date, time, datetime
from typing import Optional

import streamlit as st

from utils.time_utils import format_time
from utils.constants import SessionKey


# ── Combined Slot Grid (Auto-Assign) ─────────────────────────

def render_combined_slot_grid(
    combined_slots: list[dict],
    selected_start_utc: Optional[datetime] = None,
    columns_per_row: int = 4,
) -> Optional[dict]:
    """
    Render a grid of time slots in combined mode.
    Each slot shows availability count and can be clicked to select.

    Args:
        combined_slots:     Output of availability_service.get_combined_availability()
        selected_start_utc: Currently selected slot's UTC start time (from session_state)
        columns_per_row:    How many slots to show per row (responsive)

    Returns:
        The selected slot dict if a slot was just clicked, else None.
    """
    if not combined_slots:
        st.markdown(
            """
            <div style="text-align:center;padding:3rem;color:#9ca3af;background:#f9fafb;
                        border-radius:12px;border:2px dashed #e5e7eb">
                <div style="font-size:2.5rem;margin-bottom:0.5rem">🗓️</div>
                <div style="font-weight:600;color:#6b7280">No available slots</div>
                <div style="font-size:0.875rem;margin-top:0.3rem">
                    Try a different date or shorter duration
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return None

    just_selected = None

    # Render slots in rows
    for row_start in range(0, len(combined_slots), columns_per_row):
        row_slots = combined_slots[row_start : row_start + columns_per_row]
        cols = st.columns(columns_per_row)

        for col, slot in zip(cols, row_slots):
            with col:
                is_selected = (
                    selected_start_utc is not None
                    and slot["start_utc"] == selected_start_utc
                )
                available = slot["available"]
                avail_count = slot["available_courts"]
                total_count = slot["total_courts"]

                # Button label
                label = slot["label"]
                if available:
                    sub = f"✓ {avail_count}/{total_count} court{'s' if avail_count != 1 else ''}"
                else:
                    sub = "Unavailable"

                # Style hint via markdown above button
                if is_selected:
                    st.markdown(
                        f"<div style='background:#4361ee;color:#fff;border-radius:8px 8px 0 0;"
                        f"padding:0.3rem 0.5rem;text-align:center;font-size:0.8rem;font-weight:700'>"
                        f"✓ Selected</div>",
                        unsafe_allow_html=True,
                    )

                if available:
                    clicked = st.button(
                        f"{label}\n{sub}",
                        key=f"slot_{slot['start_utc'].isoformat()}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary",
                    )
                else:
                    st.markdown(
                        f"""
                        <div style="
                            background:#f3f4f6;
                            border:1.5px solid #e5e7eb;
                            border-radius:8px;
                            padding:0.5rem;
                            text-align:center;
                            color:#9ca3af;
                            font-size:0.85rem;
                            text-decoration:line-through;
                        ">
                            {label}<br><span style='font-size:0.75rem'>{sub}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    clicked = False

                if clicked and available and not is_selected:
                    just_selected = slot

    return just_selected


# ── Per-Court Slot Grid ───────────────────────────────────────

def render_per_court_slot_grid(
    court_availability: dict,
    selected_court_id: Optional[str] = None,
    selected_start_utc: Optional[datetime] = None,
    columns_per_row: int = 3,
) -> Optional[tuple[str, dict]]:
    """
    Render slots grouped by court.

    Returns (court_id, slot_dict) if a slot was clicked, else None.
    """
    if not court_availability:
        st.info("No courts found for this facility.")
        return None

    just_selected = None

    for court_id, data in court_availability.items():
        court = data["court"]
        slots = data["slots"]
        avail_count = data.get("available_count", 0)

        sport_icon = _sport_icon(court.get("sport_type", ""))
        status_text = f"{avail_count} slots available" if avail_count else "No slots available"
        status_color = "#22c55e" if avail_count else "#ef4444"

        st.markdown(
            f"""
            <div style="
                display:flex;align-items:center;gap:0.75rem;
                background:#f8f9ff;border-radius:10px;
                padding:0.75rem 1rem;margin-bottom:0.5rem;
                border:1px solid #e0e0f0;
            ">
                <span style='font-size:1.5rem'>{sport_icon}</span>
                <div>
                    <strong style='color:#1a1a2e'>{court['name']}</strong>
                    <span style='color:{status_color};font-size:0.8rem;margin-left:0.5rem'>
                        {status_text}
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        available_slots = [s for s in slots if s["available"]]
        if not available_slots:
            st.caption("No available slots for this court on the selected date.")
            st.markdown("---")
            continue

        for row_start in range(0, len(available_slots), columns_per_row):
            row_slots = available_slots[row_start : row_start + columns_per_row]
            cols = st.columns(columns_per_row)

            for col, slot in zip(cols, row_slots):
                with col:
                    is_selected = (
                        selected_court_id == court_id
                        and selected_start_utc is not None
                        and slot["start_utc"] == selected_start_utc
                    )
                    clicked = st.button(
                        slot["label"],
                        key=f"slot_{court_id}_{slot['start_utc'].isoformat()}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary",
                    )
                    if clicked and not is_selected:
                        just_selected = (court_id, slot)

        st.markdown("---")

    return just_selected


# ── Selection Summary ─────────────────────────────────────────

def render_slot_selection_summary(
    slot: dict,
    court: Optional[dict],
    booking_date: date,
    duration_minutes: int,
    price_info: Optional[dict] = None,
) -> None:
    """
    Show a summary card for the currently selected slot.
    Displayed below the grid when a slot is selected.
    """
    from utils.time_utils import format_date, format_duration

    court_name = court["name"] if court else "Auto-assigned"
    sport = court.get("sport_type", "").title() if court else ""

    st.markdown(
        f"""
        <div style="
            background:linear-gradient(135deg,#f0f7ff,#f8f9ff);
            border:2px solid #4361ee;
            border-radius:12px;
            padding:1.25rem 1.5rem;
            margin-top:1rem;
        ">
            <div style="font-weight:700;font-size:1.05rem;color:#1a1a2e;margin-bottom:0.5rem">
                ✅ Slot Selected
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;font-size:0.9rem">
                <div><span style='color:#6b7280'>Date:</span>
                     <strong> {format_date(booking_date)}</strong></div>
                <div><span style='color:#6b7280'>Time:</span>
                     <strong> {slot['label']}</strong></div>
                <div><span style='color:#6b7280'>Duration:</span>
                     <strong> {format_duration(duration_minutes)}</strong></div>
                <div><span style='color:#6b7280'>Court:</span>
                     <strong> {court_name}{' (' + sport + ')' if sport else ''}</strong></div>
                {_price_cell(price_info) if price_info else ''}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Helpers ───────────────────────────────────────────────────

def _sport_icon(sport_type: str) -> str:
    icons = {
        "pickleball": "🏓",
        "badminton":  "🏸",
        "tennis":     "🎾",
        "karate":     "🥋",
        "multi-sport":"🏅",
    }
    return icons.get(sport_type.lower() if sport_type else "", "🏟️")


def _price_cell(price_info: dict) -> str:
    total = price_info.get("total_amount", 0)
    rule = price_info.get("rule_name", "")
    return (
        f"<div><span style='color:#6b7280'>Price:</span>"
        f" <strong style='color:#4361ee'>${total:.2f}</strong>"
        f"<span style='color:#9ca3af;font-size:0.8rem'> ({rule})</span></div>"
    )
