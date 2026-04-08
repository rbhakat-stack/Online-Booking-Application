"""
Admin Dashboard
================
High-level overview for facility admins:
  • KPI metric cards (dark gradient, electric cyan values)
  • Today's booking schedule timeline
  • Recent activity feed
  • Quick action buttons

Design: dark metric cards with electric cyan/violet gradients,
clean white schedule cards — inspired by modern SaaS dashboards.
"""

import streamlit as st
from datetime import date

from components.auth_guard import show_auth_status_sidebar, require_admin
from services.auth_service import get_auth_service
from services.admin_service import (
    get_dashboard_stats,
    get_todays_bookings,
    get_recent_activity,
)
from db.supabase_client import get_admin_client
from db.queries import get_admin_facilities, get_active_facilities
from utils.time_utils import utc_to_local, parse_iso_datetime, format_time, format_date
from utils.constants import BookingStatus

_STATUS_BADGE = {
    BookingStatus.CONFIRMED:       ("badge-confirmed",   "Confirmed"),
    BookingStatus.PENDING_PAYMENT: ("badge-pending",     "Pending"),
    BookingStatus.CANCELLED:       ("badge-cancelled",   "Cancelled"),
    BookingStatus.REFUNDED:        ("badge-refunded",    "Refunded"),
    BookingStatus.NO_SHOW:         ("badge-no-show",     "No Show"),
}

_SPORT_ICONS = {
    "pickleball": "🏓", "badminton": "🏸",
    "tennis": "🎾", "karate": "🥋", "multi-sport": "🏅",
}


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    require_admin()
    auth_service.load_session_from_state()

    user    = auth_service.get_current_user()
    profile = auth_service.get_current_profile() or {}
    name    = profile.get("full_name", "Admin").split()[0]

    # ── Facility selector ─────────────────────────────────────
    admin_client = get_admin_client()
    role = profile.get("role", "player")

    if role == "super_admin":
        facilities = get_active_facilities(admin_client)
    else:
        facilities = get_admin_facilities(admin_client, str(user.id))

    if not facilities:
        st.error("No facilities assigned to your account. Contact a super admin.")
        return

    facility_map = {f["id"]: f for f in facilities}
    fac_id = st.session_state.get("_admin_facility_id") or list(facility_map.keys())[0]

    # ── Page header ───────────────────────────────────────────
    today_str = format_date(date.today(), "%A, %B %d %Y")

    col_hdr, col_sel = st.columns([3, 2])
    with col_hdr:
        st.markdown(
            f"""
            <div class="admin-page-header">
                <div>
                    <div class="header-title">Good work, {name} 👋</div>
                    <div class="header-subtitle">{today_str}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_sel:
        st.markdown("<br>", unsafe_allow_html=True)
        fac_id = st.selectbox(
            "Facility",
            options=list(facility_map.keys()),
            format_func=lambda x: facility_map[x]["name"],
            index=list(facility_map.keys()).index(fac_id)
                  if fac_id in facility_map else 0,
            key="admin_dash_fac",
            label_visibility="collapsed",
        )
        st.session_state["_admin_facility_id"] = fac_id

    fac = facility_map[fac_id]
    timezone = fac.get("timezone", "America/New_York")

    # ── Load data ─────────────────────────────────────────────
    with st.spinner(""):
        stats       = get_dashboard_stats(fac_id, timezone)
        schedule    = get_todays_bookings(fac_id, timezone)
        recent      = get_recent_activity(fac_id, limit=10)

    # ── KPI Cards ─────────────────────────────────────────────
    st.markdown(
        "<div class='admin-section-header'>📊 Today at a Glance</div>",
        unsafe_allow_html=True,
    )

    kpis = [
        ("🗓", f"{stats['today_booking_count']}", "Bookings Today",
         f"+{stats['pending_count']} pending" if stats['pending_count'] else "All confirmed",
         "neu" if not stats['pending_count'] else "up"),
        ("💰", f"${stats['today_revenue']:.0f}", "Today's Revenue",
         f"${stats['monthly_revenue']:.0f} this month", "up"),
        ("🏟️", f"{stats['active_courts']}", "Active Courts",
         f"{stats['occupancy_pct']}% occupancy today", "neu"),
        ("❌", f"{stats['cancelled_today']}", "Cancellations",
         "today" if stats['cancelled_today'] else "All good today",
         "down" if stats['cancelled_today'] else "neu"),
    ]

    cols = st.columns(4)
    for col, (icon, value, label, delta, delta_type) in zip(cols, kpis):
        with col:
            st.markdown(
                f"""
                <div class="admin-metric-card">
                    <div class="metric-icon">{icon}</div>
                    <div class="metric-value">{value}</div>
                    <div class="metric-label">{label}</div>
                    <div class="metric-delta {delta_type}">{delta}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Two-column layout ─────────────────────────────────────
    col_sched, col_activity = st.columns([3, 2], gap="medium")

    with col_sched:
        st.markdown(
            "<div class='admin-section-header'>📅 Today's Schedule</div>",
            unsafe_allow_html=True,
        )
        if not schedule:
            st.markdown(
                """
                <div style="text-align:center;padding:2rem;color:#94a3b8;
                            background:#f8fafc;border-radius:12px;border:1px dashed #e2e8f0">
                    <div style="font-size:2rem;margin-bottom:0.5rem">🏟️</div>
                    No bookings scheduled for today.
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            _render_schedule_timeline(schedule, timezone)

    with col_activity:
        st.markdown(
            "<div class='admin-section-header'>⚡ Recent Activity</div>",
            unsafe_allow_html=True,
        )
        _render_recent_activity(recent, timezone)

    # ── Quick Actions ─────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        "<div class='admin-section-header'>🚀 Quick Actions</div>",
        unsafe_allow_html=True,
    )
    qa1, qa2, qa3, qa4 = st.columns(4)
    with qa1:
        if st.button("📅 Manage Bookings", use_container_width=True, type="primary"):
            st.switch_page("pages/admin/bookings_mgmt.py")
    with qa2:
        if st.button("⚙️ Configuration", use_container_width=True):
            st.switch_page("pages/admin/config.py")
    with qa3:
        if st.button("💰 Revenue & Metrics", use_container_width=True):
            st.switch_page("pages/admin/metrics.py")
    with qa4:
        if st.button("🎾 View Availability", use_container_width=True):
            st.switch_page("pages/availability.py")


# ── Schedule Timeline ──────────────────────────────────────────

def _render_schedule_timeline(bookings: list[dict], timezone: str):
    rows_html = ""
    for b in bookings:
        court   = b.get("courts") or {}
        user_p  = b.get("user_profiles") or {}
        sport   = court.get("sport_type", "")
        icon    = _SPORT_ICONS.get(sport, "🏟️")
        status  = b.get("status", "")
        badge_cls, badge_lbl = _STATUS_BADGE.get(status, ("badge-expired", status.title()))

        start_utc = parse_iso_datetime(str(b.get("start_time_utc", "")))
        end_utc   = parse_iso_datetime(str(b.get("end_time_utc", "")))
        if start_utc:
            local_start = utc_to_local(start_utc, timezone)
            local_end   = utc_to_local(end_utc, timezone) if end_utc else None
            time_str = f"{format_time(local_start.time())}"
            if local_end:
                time_str += f" – {format_time(local_end.time())}"
        else:
            time_str = "—"

        name  = user_p.get("full_name", "Unknown")
        total = float(b.get("total_amount", 0))

        rows_html += f"""
        <tr>
            <td style="font-weight:700;color:#0ea5e9;white-space:nowrap">{time_str}</td>
            <td>{icon} <strong>{court.get('name', '—')}</strong></td>
            <td>{name}</td>
            <td><span class="badge {badge_cls}">{badge_lbl}</span></td>
            <td style="text-align:right;font-weight:700;color:#8b5cf6">${total:.0f}</td>
        </tr>
        """

    st.markdown(
        f"""
        <div style="border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;
                    background:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.04)">
        <table class="admin-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Court</th>
                    <th>Customer</th>
                    <th>Status</th>
                    <th style="text-align:right">Paid</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Recent Activity Feed ───────────────────────────────────────

def _render_recent_activity(activity: list[dict], timezone: str):
    if not activity:
        st.caption("No recent activity.")
        return

    items_html = ""
    for a in activity:
        status  = a.get("status", "")
        badge_cls, badge_lbl = _STATUS_BADGE.get(status, ("badge-expired", status.title()))
        court   = a.get("courts") or {}
        user_p  = a.get("user_profiles") or {}
        name    = user_p.get("full_name", "Unknown")
        sport   = court.get("sport_type", "")
        icon    = _SPORT_ICONS.get(sport, "🏟️")
        bdate   = a.get("booking_date", "")

        items_html += f"""
        <div style="display:flex;align-items:center;gap:0.65rem;
                    padding:0.6rem 0;border-bottom:1px solid #f1f5f9">
            <span style="font-size:1.3rem">{icon}</span>
            <div style="flex:1;min-width:0">
                <div style="font-weight:600;font-size:0.875rem;color:#0f172a;
                            white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                    {name}
                </div>
                <div style="font-size:0.75rem;color:#94a3b8">{bdate}</div>
            </div>
            <span class="badge {badge_cls}">{badge_lbl}</span>
        </div>
        """

    st.markdown(
        f"""
        <div style="background:#fff;border-radius:12px;border:1px solid #e2e8f0;
                    padding:0.5rem 1rem;box-shadow:0 1px 4px rgba(0,0,0,0.04)">
            {items_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


render()
