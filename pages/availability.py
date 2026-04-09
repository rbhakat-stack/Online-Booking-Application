"""
Availability Browser — Book a Court
======================================
Users select:
  1. Facility
  2. Sport type (optional filter)
  3. Date
  4. Duration

The page then fetches real-time availability and renders a slot grid.
Clicking a slot → session state updated → "Proceed to Book" button appears.
Clicking "Proceed to Book" → navigates to pages/book.py.

Availability is computed by:
  availability_service.get_facility_availability()
  availability_service.get_combined_availability()

All DB I/O happens here; the availability service is pure computation.
"""

from datetime import date, timedelta
from typing import Optional

import streamlit as st

from components.auth_guard import show_auth_status_sidebar
from components.slot_selector import render_combined_slot_grid, render_slot_selection_summary
from components.pricing_summary import render_compact_price
from services.auth_service import get_auth_service
from services.availability_service import get_facility_availability, get_combined_availability, pick_best_court
from services.pricing_service import calculate_price, generate_duration_options
from db.supabase_client import get_client, get_session_client, get_admin_client
from db.queries import (
    get_active_facilities,
    get_active_courts,
    get_facility_settings,
    get_facility_operating_hours,
    get_facility_closures,
    get_bookings_for_court_on_date,
    get_active_holds_for_court,
    get_blackout_periods_for_date,
    get_pricing_rules,
)
from utils.time_utils import today_local, format_date
from utils.constants import SPORT_TYPES, SPORT_ICONS, SessionKey, BookingStatus


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    auth_service.load_session_from_state()

    st.markdown("## 🎾 Book a Court")
    st.markdown("Select your session details and choose an available time slot.")

    # ── Step 1: Load Facilities ──────────────────────────────
    client = get_client()           # Anon client — facilities are publicly readable
    facilities = get_active_facilities(client)

    if not facilities:
        st.warning("No facilities are currently active. Please check back soon.")
        return

    # ── Filters Panel ────────────────────────────────────────
    with st.container():
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

        with col1:
            facility_options = {f["id"]: f["name"] for f in facilities}
            # Restore previously selected facility
            saved_fac_id = st.session_state.get(SessionKey.SELECTED_FACILITY_ID)
            default_fac_idx = 0
            if saved_fac_id and saved_fac_id in facility_options:
                default_fac_idx = list(facility_options.keys()).index(saved_fac_id)

            selected_fac_id = st.selectbox(
                "🏟️ Facility",
                options=list(facility_options.keys()),
                format_func=lambda x: facility_options[x],
                index=default_fac_idx,
                key="fac_selector",
            )
            st.session_state[SessionKey.SELECTED_FACILITY_ID] = selected_fac_id

        with col2:
            # Sport is always required — no "Any" or "multi-sport" options.
            # Restore previously selected sport, defaulting to pickleball.
            saved_sport = st.session_state.get("selected_sport_type", "pickleball")
            default_sport_idx = (
                SPORT_TYPES.index(saved_sport)
                if saved_sport in SPORT_TYPES
                else 0
            )
            sport_filter = st.selectbox(
                "🏅 Sport",
                options=SPORT_TYPES,
                format_func=lambda s: f"{SPORT_ICONS.get(s, '')} {s.title()}",
                index=default_sport_idx,
                key="sport_filter",
            )
            st.session_state["selected_sport_type"] = sport_filter

        with col3:
            # Load facility settings to know the booking window
            settings = _load_facility_settings(client, selected_fac_id)
            booking_window = int(settings.get("booking_window_days", 30))
            today = today_local(
                next((f["timezone"] for f in facilities if f["id"] == selected_fac_id), "America/New_York")
            )
            min_date = today
            max_date = today + timedelta(days=booking_window)

            saved_date = st.session_state.get(SessionKey.SELECTED_DATE)
            default_date = saved_date if saved_date and min_date <= saved_date <= max_date else today

            selected_date = st.date_input(
                "📅 Date",
                value=default_date,
                min_value=min_date,
                max_value=max_date,
                key="date_picker",
            )
            st.session_state[SessionKey.SELECTED_DATE] = selected_date

        with col4:
            # Cap increment at 30 min: slots appear at :00 and :30 each hour.
            # This ensures a 7:30-8:30 booking leaves 8:30-9:30 open.
            slot_increment = min(int(settings.get("booking_increment_minutes", 30)), 30)
            duration_opts = generate_duration_options(
                min_booking_minutes=int(settings.get("min_booking_minutes", 60)),
                max_booking_hours=int(settings.get("max_booking_hours", 4)),
                booking_increment_minutes=slot_increment,
            )
            saved_duration = st.session_state.get(SessionKey.SELECTED_DURATION)
            dur_labels = [d["label"] for d in duration_opts]
            dur_minutes = [d["minutes"] for d in duration_opts]
            default_dur_idx = 0
            if saved_duration and saved_duration in dur_minutes:
                default_dur_idx = dur_minutes.index(saved_duration)

            duration_label = st.selectbox(
                "⏱️ Duration",
                options=dur_labels,
                index=default_dur_idx,
                key="duration_selector",
            )
            selected_duration = dur_minutes[dur_labels.index(duration_label)]
            st.session_state[SessionKey.SELECTED_DURATION] = selected_duration

    st.markdown("---")

    # ── Load Availability Data ───────────────────────────────
    # Exclude the current user's own holds so their previous hold for a slot
    # does not prevent them from re-selecting the same slot.
    current_user = auth_service.get_current_user()
    current_user_id = str(current_user.id) if current_user else None

    with st.spinner("Checking availability…"):
        try:
            availability_data = _load_availability(
                client=client,
                facility_id=selected_fac_id,
                selected_date=selected_date,
                duration_minutes=selected_duration,
                settings=settings,
                sport_type_filter=sport_filter,
                timezone=next((f["timezone"] for f in facilities if f["id"] == selected_fac_id), "America/New_York"),
                exclude_user_id=current_user_id,
            )
        except Exception as e:
            st.error(f"Failed to load availability: {e}")
            return

    if availability_data is None:
        st.info("Availability data could not be loaded. Please try again.")
        return

    court_avail = availability_data["court_availability"]
    combined_slots = availability_data["combined_slots"]
    pricing_rules = availability_data["pricing_rules"]
    courts_map = availability_data["courts_map"]

    # ── Date / Sport Header ───────────────────────────────────
    sport_icon   = SPORT_ICONS.get(sport_filter, "🏟️")
    sport_label  = sport_filter.title()
    courts_count = len(courts_map)   # total courts of this sport type

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(
            f"### {sport_icon} {sport_label} — {format_date(selected_date)}"
        )
        st.caption(
            f"{courts_count} {sport_label} court{'s' if courts_count != 1 else ''} · "
            "Each slot shows how many courts are free at that time"
        )
    with col2:
        open_slots = [s for s in combined_slots if s["available"]]
        if open_slots:
            st.success(f"✅ {len(open_slots)} time slots open")
        else:
            st.error("❌ No slots available")

    # ── Slot Grid ─────────────────────────────────────────────
    # 3 columns gives wider, more readable buttons and avoids the
    # "4 columns = 4 sport types?" confusion.
    selected_start_utc = st.session_state.get("_avail_selected_start_utc")
    just_selected = render_combined_slot_grid(
        combined_slots=combined_slots,
        selected_start_utc=selected_start_utc,
        columns_per_row=3,
    )

    if just_selected:
        # Store selection in session state and rerun to refresh UI
        st.session_state["_avail_selected_start_utc"] = just_selected["start_utc"]
        st.session_state["_avail_selected_slot"] = just_selected
        st.rerun()

    # ── Selected Slot Actions ─────────────────────────────────
    selected_slot = st.session_state.get("_avail_selected_slot")
    if selected_slot and selected_slot.get("start_utc") == selected_start_utc:
        st.markdown("---")
        st.markdown("### 📋 Your Selection")

        # Auto-assign court for price preview
        auto_court_id = pick_best_court(
            court_avail, selected_slot["start_utc"], sport_filter
        )
        auto_court = courts_map.get(auto_court_id) if auto_court_id else None

        # Calculate price preview
        if pricing_rules and auto_court:
            price_info = calculate_price(
                pricing_rules=pricing_rules,
                booking_date=selected_date,
                start_time=selected_slot["start_time"],
                duration_minutes=selected_duration,
                sport_type=auto_court.get("sport_type"),
                court_id=auto_court_id,
                membership_type=(
                    (auth_service.get_current_profile() or {}).get("membership_type", "none")
                ),
            )
        else:
            price_info = None

        col1, col2 = st.columns([3, 1])
        with col1:
            render_slot_selection_summary(
                slot=selected_slot,
                court=auto_court,
                booking_date=selected_date,
                duration_minutes=selected_duration,
                price_info=price_info,
            )

        with col2:
            st.markdown("<br>", unsafe_allow_html=True)

            # ── Auth check before proceed ────────────────────
            if not auth_service.is_authenticated():
                st.warning("Please log in to book.")
                if st.button("Log In", type="primary", use_container_width=True):
                    st.switch_page("pages/login.py")
            else:
                # Check waiver
                profile = auth_service.get_current_profile() or {}
                if not profile.get("waiver_accepted"):
                    st.warning("⚠️ Accept waiver first.")
                    if st.button("Go to Profile", use_container_width=True):
                        st.switch_page("pages/profile.py")
                else:
                    if st.button(
                        "Proceed to Book →",
                        type="primary",
                        use_container_width=True,
                    ):
                        # Store all needed info in session state for book.py
                        _store_booking_selection(
                            facility_id=selected_fac_id,
                            court_id=auto_court_id,
                            slot=selected_slot,
                            duration_minutes=selected_duration,
                            price_info=price_info,
                            court=auto_court,
                        )
                        # Clear idempotency key so book.py generates a fresh one
                        st.session_state["booking_idempotency_key"] = None
                        st.switch_page("pages/book.py")

                    if st.button(
                        "Clear Selection",
                        use_container_width=True,
                    ):
                        _clear_slot_selection()
                        st.rerun()

    # ── Pricing Legend ────────────────────────────────────────
    _render_pricing_legend(pricing_rules, selected_date)


# ── Data Loading ──────────────────────────────────────────────

def _load_facility_settings(client, facility_id: str) -> dict:
    """Load settings with safe defaults if not configured."""
    settings = get_facility_settings(client, facility_id)
    return settings or {
        "min_booking_minutes": 60,
        "booking_increment_minutes": 30,
        "max_booking_hours": 4,
        "buffer_minutes_between_bookings": 0,
        "booking_window_days": 30,
        "hold_expiry_minutes": 10,
        "cancellation_window_hours": 24,
        "partial_refund_window_hours": 12,
        "allow_auto_assign_court": True,
        "allow_waitlist": False,
    }


def _load_availability(
    client,
    facility_id: str,
    selected_date: date,
    duration_minutes: int,
    settings: dict,
    sport_type_filter: str,          # Always required — no "Any" option
    timezone: str,
    exclude_user_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Fetch all data needed for availability computation and run the engine.
    Returns a dict with court_availability, combined_slots, pricing_rules, courts_map.
    """
    date_str = selected_date.isoformat()

    # Load courts
    courts = get_active_courts(client, facility_id, sport_type_filter)
    if not courts:
        return {
            "court_availability": {},
            "combined_slots": [],
            "pricing_rules": [],
            "courts_map": {},
        }

    courts_map = {str(c["id"]): c for c in courts}

    # Load operating hours, closures, blackout periods
    operating_hours = get_facility_operating_hours(client, facility_id)
    closures = get_facility_closures(client, facility_id)
    blackout_periods = get_blackout_periods_for_date(client, facility_id, date_str)

    # Load existing bookings + holds for all courts on this date.
    # We use the admin client here so that Postgres RLS does not hide other
    # users' bookings.  With the anon key, RLS restricts reads to the user's
    # own rows — meaning other users' confirmed bookings are invisible and
    # every slot falsely appears available (5/5 instead of 4/5).
    # The admin client bypasses RLS; no user-controlled values are interpolated
    # into these queries (only server-side court IDs and date strings).
    avail_client = get_admin_client()
    all_bookings = []
    all_holds = []
    for court in courts:
        court_id = str(court["id"])
        all_bookings.extend(
            get_bookings_for_court_on_date(
                avail_client, court_id, date_str,
                conflict_statuses=[BookingStatus.PENDING_PAYMENT, BookingStatus.CONFIRMED],
            )
        )
        all_holds.extend(
            get_active_holds_for_court(
                avail_client, court_id, date_str,
                exclude_user_id=exclude_user_id,  # Don't block user's own slot
            )
        )

    # Load pricing rules
    pricing_rules = get_pricing_rules(client, facility_id)

    # Run availability engine.
    # Override booking_increment_minutes to at most 30 so time slots are
    # generated at :00 and :30 each hour.  A booking at 7:30-8:30 then
    # leaves 8:30-9:30 open (they don't overlap: 8:30 < 8:30 is false).
    engine_settings = {
        **settings,
        "booking_increment_minutes": min(
            int(settings.get("booking_increment_minutes", 30)), 30
        ),
    }
    court_availability = get_facility_availability(
        requested_date=selected_date,
        duration_minutes=duration_minutes,
        courts=courts,
        operating_hours_list=operating_hours,
        facility_settings=engine_settings,
        existing_bookings=all_bookings,
        active_holds=all_holds,
        closures=closures,
        blackout_periods=blackout_periods,
        timezone=timezone,
    )

    combined_slots = get_combined_availability(court_availability)

    return {
        "court_availability": court_availability,
        "combined_slots": combined_slots,
        "pricing_rules": pricing_rules,
        "courts_map": courts_map,
    }


# ── Session State Helpers ─────────────────────────────────────

def _store_booking_selection(
    facility_id: str,
    court_id: Optional[str],
    slot: dict,
    duration_minutes: int,
    price_info: Optional[dict],
    court: Optional[dict],
) -> None:
    """Persist selection to session state for book.py to read."""
    st.session_state[SessionKey.SELECTED_FACILITY_ID] = facility_id
    st.session_state[SessionKey.SELECTED_COURT_ID] = court_id
    st.session_state[SessionKey.SELECTED_START_TIME] = slot["start_utc"]
    st.session_state[SessionKey.SELECTED_DURATION] = duration_minutes
    # Store full slot + price info for book.py (no re-fetch needed for display)
    st.session_state["_booking_slot"] = slot
    st.session_state["_booking_price_info"] = price_info
    st.session_state["_booking_court"] = court


def _clear_slot_selection() -> None:
    for key in [
        "_avail_selected_start_utc", "_avail_selected_slot",
        "_booking_slot", "_booking_price_info", "_booking_court",
        SessionKey.SELECTED_COURT_ID, SessionKey.SELECTED_START_TIME,
    ]:
        st.session_state.pop(key, None)


# ── Pricing Legend ────────────────────────────────────────────

def _render_pricing_legend(pricing_rules: list[dict], booking_date: date) -> None:
    """Show a quick pricing reference below the slot grid."""
    if not pricing_rules:
        return

    st.markdown("---")
    with st.expander("💰 Pricing Information", expanded=False):
        active_rules = [r for r in pricing_rules if r.get("is_active") and r.get("rule_type") != "event"]
        if not active_rules:
            st.caption("No pricing information available.")
            return

        cols = st.columns(min(len(active_rules), 4))
        for col, rule in zip(cols, active_rules[:4]):
            with col:
                days = rule.get("applies_to_days")
                day_str = ", ".join(d.title()[:3] for d in days) if days else "All days"
                start = rule.get("peak_start_time", "")
                end = rule.get("peak_end_time", "")
                time_str = f"{start}–{end}" if start and end else "All hours"

                st.markdown(
                    f"""
                    <div style="background:#f8f9ff;border-radius:8px;padding:0.75rem;
                                border:1px solid #e0e0f0;text-align:center">
                        <div style="font-weight:700;color:#1a1a2e">{rule['name']}</div>
                        <div style="font-size:1.3rem;font-weight:800;color:#4361ee;margin:0.3rem 0">
                            ${float(rule['price_per_hour']):.0f}<span style='font-size:0.8rem;font-weight:400'>/hr</span>
                        </div>
                        <div style="font-size:0.75rem;color:#6b7280">{day_str}</div>
                        <div style="font-size:0.75rem;color:#6b7280">{time_str}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


render()
