"""
Facility Configuration (Admin)
================================
Six tabbed sections for full facility management:

  1. Facility Info  — name, contact, timezone, active status
  2. Operating Hours — open/close times per day, is_open toggle
  3. Courts          — all courts, status toggle, add new court
  4. Booking Rules   — settings (hold expiry, windows, increment, etc.)
  5. Pricing Rules   — view, add, enable/disable pricing rules
  6. Closures        — scheduled closures (add / delete)
"""

import streamlit as st
from datetime import datetime, time

from components.auth_guard import show_auth_status_sidebar, require_admin
from services.auth_service import get_auth_service
from services.admin_service import (
    get_full_facility,
    update_facility_info,
    upsert_facility_settings,
    upsert_operating_hours,
    get_all_courts,
    upsert_court,
    set_court_status,
    get_all_pricing_rules,
    upsert_pricing_rule,
    toggle_pricing_rule,
    add_closure,
    remove_closure,
)
from db.supabase_client import get_admin_client
from db.queries import (
    get_admin_facilities,
    get_active_facilities,
    get_facility_settings,
    get_facility_operating_hours,
    get_facility_closures,
)
from utils.constants import SPORT_TYPES, SPORT_ICONS, DAYS_OF_WEEK, PricingRuleType

_COURT_STATUSES = ["active", "inactive", "maintenance"]
_RULE_TYPES = [
    PricingRuleType.BASE,
    PricingRuleType.PEAK,
    PricingRuleType.OFF_PEAK,
    PricingRuleType.WEEKEND,
    PricingRuleType.EVENT,
]
_TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Phoenix", "America/Anchorage",
    "Pacific/Honolulu",
]


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    require_admin()
    auth_service.load_session_from_state()

    user    = auth_service.get_current_user()
    profile = auth_service.get_current_profile() or {}
    role    = profile.get("role", "player")

    admin_client = get_admin_client()
    if role == "super_admin":
        facilities = get_active_facilities(admin_client)
    else:
        facilities = get_admin_facilities(admin_client, str(user.id))

    if not facilities:
        st.error("No facilities assigned. Contact a super admin.")
        return

    facility_map = {f["id"]: f for f in facilities}
    saved_fac = st.session_state.get("_admin_facility_id") or list(facility_map.keys())[0]
    if saved_fac not in facility_map:
        saved_fac = list(facility_map.keys())[0]

    # ── Page Header ───────────────────────────────────────────
    col_hdr, col_fac = st.columns([3, 2])
    with col_hdr:
        st.markdown(
            """
            <div class="admin-page-header">
                <div>
                    <div class="header-title">⚙️ Facility Configuration</div>
                    <div class="header-subtitle">Manage all settings for your facility</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_fac:
        st.markdown("<br>", unsafe_allow_html=True)
        fac_id = st.selectbox(
            "Facility",
            options=list(facility_map.keys()),
            format_func=lambda x: facility_map[x]["name"],
            index=list(facility_map.keys()).index(saved_fac),
            key="cfg_fac",
            label_visibility="collapsed",
        )
        st.session_state["_admin_facility_id"] = fac_id

    # ── Tabs ──────────────────────────────────────────────────
    tabs = st.tabs([
        "🏟️ Facility Info",
        "🕐 Operating Hours",
        "🎾 Courts",
        "📋 Booking Rules",
        "💰 Pricing Rules",
        "🚫 Closures",
    ])

    with tabs[0]:
        _tab_facility_info(fac_id)
    with tabs[1]:
        _tab_operating_hours(fac_id)
    with tabs[2]:
        _tab_courts(fac_id)
    with tabs[3]:
        _tab_booking_rules(fac_id)
    with tabs[4]:
        _tab_pricing_rules(fac_id)
    with tabs[5]:
        _tab_closures(fac_id)


# ── Tab 1: Facility Info ──────────────────────────────────────

def _tab_facility_info(fac_id: str):
    fac = get_full_facility(fac_id)
    if not fac:
        st.error("Could not load facility.")
        return

    st.markdown("<div class='admin-section-header'>Basic Information</div>", unsafe_allow_html=True)

    with st.form("fac_info_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Facility Name *", value=fac.get("name", ""))
            email = st.text_input("Email", value=fac.get("email", "") or "")
            address = st.text_input("Address", value=fac.get("address", "") or "")
            city = st.text_input("City", value=fac.get("city", "") or "")
        with c2:
            phone = st.text_input("Phone", value=fac.get("phone", "") or "")
            slug = st.text_input("Slug (URL-safe)", value=fac.get("slug", "") or "")
            state = st.text_input("State", value=fac.get("state", "") or "")
            zip_code = st.text_input("ZIP Code", value=fac.get("zip_code", "") or "")

        tz_idx = _TIMEZONES.index(fac.get("timezone", "America/New_York")) \
                 if fac.get("timezone") in _TIMEZONES else 0
        timezone = st.selectbox("Timezone", _TIMEZONES, index=tz_idx)
        is_active = st.checkbox("Facility is Active", value=fac.get("is_active", True))

        submitted = st.form_submit_button("Save Facility Info", type="primary")
        if submitted:
            if not name.strip():
                st.error("Facility name is required.")
            else:
                try:
                    update_facility_info(fac_id, {
                        "name": name.strip(),
                        "email": email.strip() or None,
                        "phone": phone.strip() or None,
                        "address": address.strip() or None,
                        "city": city.strip() or None,
                        "state": state.strip() or None,
                        "zip_code": zip_code.strip() or None,
                        "slug": slug.strip() or None,
                        "timezone": timezone,
                        "is_active": is_active,
                    })
                    st.success("Facility info saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")


# ── Tab 2: Operating Hours ────────────────────────────────────

def _tab_operating_hours(fac_id: str):
    hours = get_facility_operating_hours(get_admin_client(), fac_id)
    hours_map = {h["day_of_week"]: h for h in hours}

    st.markdown(
        "<div class='admin-section-header'>Set open and close times per day</div>",
        unsafe_allow_html=True,
    )

    with st.form("hours_form"):
        updated_hours = []
        for day in DAYS_OF_WEEK:
            existing = hours_map.get(day, {})
            col_day, col_open, col_from, col_to = st.columns([2, 1, 2, 2])
            with col_day:
                st.markdown(
                    f"<div style='padding-top:0.5rem;font-weight:600;color:#0f172a'>"
                    f"{day.title()}</div>",
                    unsafe_allow_html=True,
                )
            with col_open:
                is_open = st.checkbox(
                    "Open",
                    value=existing.get("is_open", True),
                    key=f"is_open_{day}",
                )
            with col_from:
                open_val = existing.get("open_time", "08:00:00")
                open_time = st.time_input(
                    "Open",
                    value=_parse_time(open_val),
                    key=f"open_{day}",
                    disabled=not is_open,
                    label_visibility="collapsed",
                )
            with col_to:
                close_val = existing.get("close_time", "22:00:00")
                close_time = st.time_input(
                    "Close",
                    value=_parse_time(close_val),
                    key=f"close_{day}",
                    disabled=not is_open,
                    label_visibility="collapsed",
                )
            updated_hours.append({
                "day_of_week": day,
                "is_open":     is_open,
                "open_time":   open_time.strftime("%H:%M:%S"),
                "close_time":  close_time.strftime("%H:%M:%S"),
            })

        if st.form_submit_button("Save Operating Hours", type="primary"):
            try:
                upsert_operating_hours(fac_id, updated_hours)
                st.success("Operating hours saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")


# ── Tab 3: Courts ─────────────────────────────────────────────

def _tab_courts(fac_id: str):
    courts = get_all_courts(fac_id)

    st.markdown("<div class='admin-section-header'>All Courts</div>", unsafe_allow_html=True)

    if courts:
        _render_courts_table(courts, fac_id)
    else:
        st.info("No courts found. Add your first court below.")

    st.markdown("<div class='admin-section-header'>Add / Edit Court</div>", unsafe_allow_html=True)
    _render_court_form(fac_id, courts)


def _render_courts_table(courts: list[dict], fac_id: str):
    # Build table HTML
    rows_html = ""
    for c in courts:
        cid = str(c.get("id", ""))
        status = c.get("status", "active")
        badge_map = {
            "active": "badge-active", "inactive": "badge-inactive",
            "maintenance": "badge-maintenance",
        }
        badge_cls = badge_map.get(status, "badge-inactive")
        sport = c.get("sport_type", "—")
        sport_icon = SPORT_ICONS.get(sport, "🏟️")

        rows_html += f"""
        <tr>
            <td>{sport_icon} <strong>{c.get('name','—')}</strong></td>
            <td>{sport.title()}</td>
            <td>{'Indoor' if c.get('indoor') else 'Outdoor'}</td>
            <td><span class="badge {badge_cls}">{status.title()}</span></td>
            <td>${float(c.get('hourly_rate',0)):.0f}/hr</td>
            <td style="font-size:0.75rem;color:#94a3b8">#{cid[:8].upper()}</td>
        </tr>
        """

    st.markdown(
        f"""
        <div style="border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;
                    background:#fff;margin-bottom:1rem">
        <table class="admin-table">
            <thead><tr>
                <th>Court</th><th>Sport</th><th>Type</th>
                <th>Status</th><th>Rate</th><th>ID</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Status quick-toggle
    with st.expander("Quick Status Toggle"):
        court_options = {str(c["id"]): c["name"] for c in courts}
        sel_court_id = st.selectbox("Select Court", list(court_options.keys()),
                                    format_func=lambda x: court_options[x],
                                    key="status_toggle_court")
        new_status = st.selectbox("New Status", _COURT_STATUSES, key="status_toggle_val")
        if st.button("Update Status", key="do_status_toggle"):
            if set_court_status(sel_court_id, new_status):
                st.success(f"Court status updated to {new_status}.")
                st.rerun()
            else:
                st.error("Status update failed.")


def _render_court_form(fac_id: str, courts: list[dict]):
    with st.form("court_form"):
        # Optionally editing existing court
        edit_options = {"new": "— Add New Court —"}
        edit_options.update({str(c["id"]): c["name"] for c in courts})

        edit_id = st.selectbox("Edit existing / Add new",
                               list(edit_options.keys()),
                               format_func=lambda x: edit_options[x],
                               key="court_edit_sel")
        existing = next((c for c in courts if str(c.get("id")) == edit_id), {})

        c1, c2 = st.columns(2)
        with c1:
            court_name = st.text_input("Court Name *", value=existing.get("name", ""))
            sport_idx = SPORT_TYPES.index(existing["sport_type"]) \
                        if existing.get("sport_type") in SPORT_TYPES else 0
            sport_type = st.selectbox(
                "Sport Type",
                SPORT_TYPES,
                index=sport_idx,
                format_func=lambda s: f"{SPORT_ICONS.get(s,'')} {s.title()}",
            )
            hourly_rate = st.number_input(
                "Hourly Rate ($)",
                min_value=0.0,
                value=float(existing.get("hourly_rate", 25.0)),
                step=5.0,
            )
        with c2:
            indoor = st.checkbox("Indoor", value=existing.get("indoor", True))
            status_idx = _COURT_STATUSES.index(existing["status"]) \
                         if existing.get("status") in _COURT_STATUSES else 0
            court_status = st.selectbox("Status", _COURT_STATUSES, index=status_idx)
            display_order = st.number_input(
                "Display Order",
                min_value=0,
                value=int(existing.get("display_order", len(courts) + 1)),
                step=1,
            )
        description = st.text_area("Description (optional)",
                                   value=existing.get("description", "") or "")

        if st.form_submit_button("Save Court", type="primary"):
            if not court_name.strip():
                st.error("Court name is required.")
            else:
                try:
                    court_data = {
                        "name":          court_name.strip(),
                        "sport_type":    sport_type,
                        "indoor":        indoor,
                        "status":        court_status,
                        "hourly_rate":   hourly_rate,
                        "display_order": display_order,
                        "description":   description.strip() or None,
                    }
                    if edit_id != "new":
                        court_data["id"] = edit_id
                    upsert_court(fac_id, court_data)
                    st.success("Court saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")


# ── Tab 4: Booking Rules ──────────────────────────────────────

def _tab_booking_rules(fac_id: str):
    settings = get_facility_settings(get_admin_client(), fac_id) or {}

    st.markdown("<div class='admin-section-header'>Booking Configuration</div>", unsafe_allow_html=True)

    with st.form("settings_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            min_booking = st.number_input(
                "Min Booking (minutes)",
                min_value=15, max_value=480, step=15,
                value=int(settings.get("min_booking_minutes", 60)),
            )
            booking_increment = st.number_input(
                "Booking Increment (minutes)",
                min_value=15, max_value=120, step=15,
                value=int(settings.get("booking_increment_minutes", 30)),
            )
            max_booking_hours = st.number_input(
                "Max Booking (hours)",
                min_value=1, max_value=12,
                value=int(settings.get("max_booking_hours", 4)),
            )
        with c2:
            hold_expiry = st.number_input(
                "Hold Expiry (minutes)",
                min_value=5, max_value=60, step=5,
                value=int(settings.get("hold_expiry_minutes", 10)),
            )
            booking_window = st.number_input(
                "Booking Window (days ahead)",
                min_value=1, max_value=365,
                value=int(settings.get("booking_window_days", 30)),
            )
            buffer_minutes = st.number_input(
                "Buffer Between Bookings (minutes)",
                min_value=0, max_value=60, step=5,
                value=int(settings.get("buffer_minutes_between_bookings", 0)),
            )
        with c3:
            cancellation_window = st.number_input(
                "Full Refund Window (hours before)",
                min_value=1, max_value=168,
                value=int(settings.get("cancellation_window_hours", 24)),
            )
            partial_refund_window = st.number_input(
                "Partial Refund Window (hours before)",
                min_value=1, max_value=96,
                value=int(settings.get("partial_refund_window_hours", 12)),
            )
            allow_auto_assign = st.checkbox(
                "Allow Auto-Assign Court",
                value=settings.get("allow_auto_assign_court", True),
            )

        if st.form_submit_button("Save Booking Rules", type="primary"):
            try:
                upsert_facility_settings(fac_id, {
                    "min_booking_minutes":            min_booking,
                    "booking_increment_minutes":      booking_increment,
                    "max_booking_hours":              max_booking_hours,
                    "hold_expiry_minutes":            hold_expiry,
                    "booking_window_days":            booking_window,
                    "buffer_minutes_between_bookings": buffer_minutes,
                    "cancellation_window_hours":      cancellation_window,
                    "partial_refund_window_hours":    partial_refund_window,
                    "allow_auto_assign_court":        allow_auto_assign,
                })
                st.success("Booking rules saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")


# ── Tab 5: Pricing Rules ──────────────────────────────────────

def _tab_pricing_rules(fac_id: str):
    rules = get_all_pricing_rules(fac_id)

    st.markdown("<div class='admin-section-header'>Current Pricing Rules</div>", unsafe_allow_html=True)

    if rules:
        rows_html = ""
        for r in rules:
            rid = str(r.get("id", ""))
            active = r.get("is_active", True)
            status_badge = "badge-active" if active else "badge-inactive"
            status_lbl = "Active" if active else "Inactive"
            days = r.get("applies_to_days")
            day_str = ", ".join(d[:3].title() for d in days) if days else "All days"
            t_start = r.get("peak_start_time", "")
            t_end   = r.get("peak_end_time", "")
            time_str = f"{t_start}–{t_end}" if t_start and t_end else "All hours"

            rows_html += f"""
            <tr>
                <td><strong>{r.get('name','—')}</strong></td>
                <td>{r.get('rule_type','—').replace('_',' ').title()}</td>
                <td style="font-weight:700;color:#8b5cf6">${float(r.get('price_per_hour',0)):.0f}/hr</td>
                <td style="font-size:0.8rem">{day_str}</td>
                <td style="font-size:0.8rem">{time_str}</td>
                <td>{r.get('priority',0)}</td>
                <td><span class="badge {status_badge}">{status_lbl}</span></td>
            </tr>
            """

        st.markdown(
            f"""
            <div style="border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;
                        background:#fff;margin-bottom:1rem">
            <table class="admin-table">
                <thead><tr>
                    <th>Name</th><th>Type</th><th>Rate</th>
                    <th>Days</th><th>Hours</th><th>Priority</th><th>Status</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Toggle active/inactive
        with st.expander("Toggle Rule Active/Inactive"):
            rule_opts = {str(r["id"]): r["name"] for r in rules}
            sel_rule = st.selectbox("Select Rule",
                                    list(rule_opts.keys()),
                                    format_func=lambda x: rule_opts[x],
                                    key="toggle_rule_sel")
            sel_rule_obj = next((r for r in rules if str(r["id"]) == sel_rule), {})
            cur_active = sel_rule_obj.get("is_active", True)
            col1, col2 = st.columns(2)
            with col1:
                if cur_active and st.button("Deactivate", key="deact_rule", use_container_width=True):
                    if toggle_pricing_rule(sel_rule, False):
                        st.success("Rule deactivated.")
                        st.rerun()
            with col2:
                if not cur_active and st.button("Activate", type="primary",
                                                key="act_rule", use_container_width=True):
                    if toggle_pricing_rule(sel_rule, True):
                        st.success("Rule activated.")
                        st.rerun()
    else:
        st.info("No pricing rules found. Add your first rule below.")

    st.markdown("<div class='admin-section-header'>Add / Edit Pricing Rule</div>", unsafe_allow_html=True)

    edit_opts = {"new": "— Add New Rule —"}
    edit_opts.update({str(r["id"]): r["name"] for r in rules})

    edit_rule_id = st.selectbox("Edit existing / Add new",
                                list(edit_opts.keys()),
                                format_func=lambda x: edit_opts[x],
                                key="rule_edit_sel")
    existing_rule = next((r for r in rules if str(r.get("id")) == edit_rule_id), {})

    with st.form("pricing_rule_form"):
        rc1, rc2 = st.columns(2)
        with rc1:
            rule_name = st.text_input("Rule Name *", value=existing_rule.get("name", ""))
            rule_type_idx = _RULE_TYPES.index(existing_rule["rule_type"]) \
                            if existing_rule.get("rule_type") in _RULE_TYPES else 0
            rule_type = st.selectbox(
                "Rule Type",
                _RULE_TYPES,
                index=rule_type_idx,
                format_func=lambda t: t.replace("_", " ").title(),
            )
            price_per_hour = st.number_input(
                "Price Per Hour ($)",
                min_value=0.0,
                value=float(existing_rule.get("price_per_hour", 25.0)),
                step=5.0,
            )
            priority = st.number_input(
                "Priority (higher = applied first)",
                min_value=0, max_value=100,
                value=int(existing_rule.get("priority", 10)),
            )
        with rc2:
            applies_days = st.multiselect(
                "Applies to Days (leave empty = all days)",
                DAYS_OF_WEEK,
                default=existing_rule.get("applies_to_days") or [],
                format_func=lambda d: d.title(),
            )
            peak_start = st.time_input(
                "Peak Start Time",
                value=_parse_time(existing_rule.get("peak_start_time") or "17:00:00"),
            )
            peak_end = st.time_input(
                "Peak End Time",
                value=_parse_time(existing_rule.get("peak_end_time") or "22:00:00"),
            )
            is_active_rule = st.checkbox("Active", value=existing_rule.get("is_active", True))

        if st.form_submit_button("Save Pricing Rule", type="primary"):
            if not rule_name.strip():
                st.error("Rule name is required.")
            else:
                try:
                    rule_data = {
                        "name":           rule_name.strip(),
                        "rule_type":      rule_type,
                        "price_per_hour": price_per_hour,
                        "priority":       priority,
                        "applies_to_days": applies_days if applies_days else None,
                        "peak_start_time": peak_start.strftime("%H:%M:%S"),
                        "peak_end_time":   peak_end.strftime("%H:%M:%S"),
                        "is_active":      is_active_rule,
                    }
                    if edit_rule_id != "new":
                        rule_data["id"] = edit_rule_id
                    upsert_pricing_rule(fac_id, rule_data)
                    st.success("Pricing rule saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")


# ── Tab 6: Closures ───────────────────────────────────────────

def _tab_closures(fac_id: str):
    closures = get_facility_closures(get_admin_client(), fac_id)

    st.markdown("<div class='admin-section-header'>Scheduled Closures</div>", unsafe_allow_html=True)

    if closures:
        rows_html = ""
        for c in closures:
            rows_html += f"""
            <tr>
                <td><strong>{c.get('closure_date','—')}</strong></td>
                <td>{c.get('reason','—')}</td>
                <td>{c.get('closure_type','one_time').replace('_',' ').title()}</td>
            </tr>
            """
        st.markdown(
            f"""
            <div style="border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;
                        background:#fff;margin-bottom:1rem">
            <table class="admin-table">
                <thead><tr><th>Date</th><th>Reason</th><th>Type</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("Remove a Closure"):
            clo_opts = {str(c["id"]): f"{c['closure_date']} — {c.get('reason','')}" for c in closures}
            sel_clo = st.selectbox("Select closure to remove",
                                   list(clo_opts.keys()),
                                   format_func=lambda x: clo_opts[x],
                                   key="del_closure_sel")
            if st.button("Remove Closure", key="do_del_closure", type="primary"):
                if remove_closure(sel_clo):
                    st.success("Closure removed.")
                    st.rerun()
                else:
                    st.error("Failed to remove closure.")
    else:
        st.info("No closures scheduled.")

    st.markdown("<div class='admin-section-header'>Add Closure</div>", unsafe_allow_html=True)
    with st.form("closure_form"):
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            closure_date = st.date_input("Date *", key="clo_date")
        with cc2:
            reason = st.text_input("Reason", key="clo_reason",
                                   placeholder="Holiday, maintenance…")
        with cc3:
            closure_type = st.selectbox("Type", ["one_time", "recurring"],
                                        format_func=lambda t: t.replace("_", " ").title(),
                                        key="clo_type")
        if st.form_submit_button("Add Closure", type="primary"):
            if not closure_date:
                st.error("Date is required.")
            else:
                try:
                    add_closure(fac_id, {
                        "closure_date": closure_date.isoformat(),
                        "reason":       reason.strip() or "Closed",
                        "closure_type": closure_type,
                    })
                    st.success(f"Closure added for {closure_date}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add closure: {e}")


# ── Helper ────────────────────────────────────────────────────

def _parse_time(t_str: str) -> time:
    """Parse 'HH:MM:SS' or 'HH:MM' string into a time object."""
    if not t_str:
        return time(8, 0)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            continue
    return time(8, 0)


render()
