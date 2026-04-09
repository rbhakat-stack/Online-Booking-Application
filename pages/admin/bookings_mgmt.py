"""
Admin Booking Management
=========================
Search, filter, and manage all bookings for the facility.

Features:
  • Date range + status + sport type filters
  • Paginated data table with all bookings
  • Expandable row: full booking detail + payment info
  • Admin cancel (with reason + optional refund amount)
  • Admin note editing
"""

import streamlit as st
from datetime import date, timedelta

from components.auth_guard import show_auth_status_sidebar, require_admin
from services.auth_service import get_auth_service
from services.admin_service import search_bookings, admin_cancel_booking, add_admin_note
from db.supabase_client import get_admin_client
from db.queries import get_admin_facilities, get_active_facilities
from utils.time_utils import (
    utc_to_local, parse_iso_datetime, format_time, format_date,
    format_duration, hours_until_booking, get_refund_policy_for_cancellation,
)
from utils.constants import BookingStatus, SPORT_TYPES, SPORT_ICONS

_PAGE_SIZE = 25

_STATUS_BADGE = {
    BookingStatus.CONFIRMED:       ("badge-confirmed",   "Confirmed"),
    BookingStatus.PENDING_PAYMENT: ("badge-pending",     "Pending"),
    BookingStatus.CANCELLED:       ("badge-cancelled",   "Cancelled"),
    BookingStatus.REFUNDED:        ("badge-refunded",    "Refunded"),
    BookingStatus.NO_SHOW:         ("badge-no-show",     "No Show"),
    BookingStatus.HOLD:            ("badge-hold",        "Hold"),
    BookingStatus.EXPIRED:         ("badge-expired",     "Expired"),
}


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
                    <div class="header-title">📅 Manage Bookings</div>
                    <div class="header-subtitle">Search, view, and manage all reservations</div>
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
            key="bkmgmt_fac",
            label_visibility="collapsed",
        )
        st.session_state["_admin_facility_id"] = fac_id

    fac = facility_map[fac_id]
    timezone = fac.get("timezone", "America/New_York")

    # ── One-time result banners ───────────────────────────────
    _show_action_banner()

    # ── Filters ───────────────────────────────────────────────
    st.markdown(
        "<div class='admin-section-header'>🔍 Filters</div>",
        unsafe_allow_html=True,
    )

    fc1, fc2, fc3, fc4, fc5 = st.columns([2, 2, 2, 2, 1])
    with fc1:
        date_from = st.date_input(
            "From",
            value=date.today() - timedelta(days=7),
            key="bk_date_from",
        )
    with fc2:
        date_to = st.date_input(
            "To",
            value=date.today() + timedelta(days=30),
            key="bk_date_to",
        )
    with fc3:
        status_options = {
            "All": None,
            "Confirmed": [BookingStatus.CONFIRMED],
            "Pending":   [BookingStatus.PENDING_PAYMENT],
            "Cancelled": [BookingStatus.CANCELLED],
            "Refunded":  [BookingStatus.REFUNDED],
        }
        status_label = st.selectbox("Status", list(status_options.keys()), key="bk_status")
        status_filter = status_options[status_label]
    with fc4:
        sport_options = ["All"] + SPORT_TYPES
        sport_sel = st.selectbox(
            "Sport",
            sport_options,
            format_func=lambda s: f"{SPORT_ICONS.get(s, '')} {s.title()}" if s != "All" else "All Sports",
            key="bk_sport",
        )
        sport_filter = None if sport_sel == "All" else sport_sel
    with fc5:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Apply", type="primary", use_container_width=True):
            st.session_state["_bk_offset"] = 0
            st.rerun()

    # ── Load results ──────────────────────────────────────────
    offset = st.session_state.get("_bk_offset", 0)

    with st.spinner("Loading bookings…"):
        bookings = search_bookings(
            facility_id=fac_id,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            status_filter=status_filter,
            sport_type=sport_filter,
            limit=_PAGE_SIZE + 1,
            offset=offset,
        )

    has_more = len(bookings) > _PAGE_SIZE
    bookings = bookings[:_PAGE_SIZE]

    # ── Results count ─────────────────────────────────────────
    st.markdown(
        f"<div style='color:#64748b;font-size:0.85rem;margin:0.5rem 0'>"
        f"Showing {offset + 1}–{offset + len(bookings)} bookings"
        f"{'  (more available)' if has_more else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not bookings:
        st.info("No bookings found matching your filters.")
        return

    # ── Table ─────────────────────────────────────────────────
    st.markdown("<div class='admin-section-header'>📋 Results</div>", unsafe_allow_html=True)

    for booking in bookings:
        _render_booking_row(booking, timezone)

    # ── Pagination ────────────────────────────────────────────
    pag1, pag2, pag3 = st.columns([1, 2, 1])
    with pag1:
        if offset > 0:
            if st.button("← Previous", use_container_width=True):
                st.session_state["_bk_offset"] = max(0, offset - _PAGE_SIZE)
                st.rerun()
    with pag3:
        if has_more:
            if st.button("Next →", type="primary", use_container_width=True):
                st.session_state["_bk_offset"] = offset + _PAGE_SIZE
                st.rerun()


# ── Booking Row + Detail Panel ────────────────────────────────

def _render_booking_row(booking: dict, timezone: str):
    booking_id = str(booking.get("id", ""))
    detail_key = f"_bkmgmt_detail_{booking_id}"
    cancel_key = f"_bkmgmt_cancel_{booking_id}"

    court   = booking.get("courts") or {}
    user_p  = booking.get("user_profiles") or {}
    status  = booking.get("status", "")
    sport   = court.get("sport_type", "")
    icon    = SPORT_ICONS.get(sport, "🏟️")
    badge_cls, badge_lbl = _STATUS_BADGE.get(status, ("badge-expired", status.title()))

    start_utc = parse_iso_datetime(str(booking.get("start_time_utc", "")))
    end_utc   = parse_iso_datetime(str(booking.get("end_time_utc", "")))
    if start_utc:
        local_s = utc_to_local(start_utc, timezone)
        local_e = utc_to_local(end_utc, timezone) if end_utc else None
        time_str = f"{format_time(local_s.time())}" + (f" – {format_time(local_e.time())}" if local_e else "")
    else:
        time_str = "—"

    bdate  = booking.get("booking_date", "—")
    total  = float(booking.get("total_amount", 0))
    name   = user_p.get("full_name", "Unknown")
    email  = user_p.get("email", "")
    bid_short = booking_id[:8].upper()

    # Row HTML
    st.markdown(
        f"""
        <div style="background:#fff;border-radius:10px;border:1px solid #e2e8f0;
                    padding:0.85rem 1.1rem;margin-bottom:0.4rem;
                    box-shadow:0 1px 3px rgba(0,0,0,0.04)">
            <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap">
                <span style="font-size:1.4rem">{icon}</span>
                <div style="flex:2;min-width:120px">
                    <div style="font-weight:700;color:#0f172a">{name}</div>
                    <div style="font-size:0.75rem;color:#94a3b8">{email}</div>
                </div>
                <div style="flex:2;min-width:120px">
                    <div style="font-size:0.875rem;font-weight:600;color:#0f172a">{bdate}</div>
                    <div style="font-size:0.78rem;color:#64748b">{time_str}</div>
                </div>
                <div style="min-width:80px">
                    <div style="font-size:0.875rem;color:#64748b">{court.get('name', '—')}</div>
                </div>
                <span class="badge {badge_cls}">{badge_lbl}</span>
                <div style="font-weight:700;color:#8b5cf6;min-width:60px;text-align:right">
                    ${total:.2f}
                </div>
                <div style="font-size:0.72rem;color:#94a3b8;min-width:60px">
                    #{bid_short}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Action buttons
    btn_a, btn_b, btn_c, _ = st.columns([1, 1, 1, 4])
    with btn_a:
        if st.button("Details", key=f"det_{booking_id}", use_container_width=True):
            st.session_state[detail_key] = not st.session_state.get(detail_key, False)
            st.session_state.pop(cancel_key, None)
            st.rerun()
    with btn_b:
        if status in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT):
            if st.button("Cancel", key=f"can_{booking_id}", use_container_width=True):
                st.session_state[cancel_key] = not st.session_state.get(cancel_key, False)
                st.session_state.pop(detail_key, None)
                st.rerun()

    # Expanded panels
    if st.session_state.get(detail_key):
        _render_detail_panel(booking, timezone)
    if st.session_state.get(cancel_key):
        _render_cancel_panel(booking, timezone)


def _render_detail_panel(booking: dict, timezone: str):
    court  = booking.get("courts") or {}
    user_p = booking.get("user_profiles") or {}
    bid    = str(booking.get("id", ""))

    base     = float(booking.get("base_amount", 0))
    discount = float(booking.get("discount_amount", 0))
    total    = float(booking.get("total_amount", 0))
    notes    = booking.get("notes", "") or ""
    admin_notes = booking.get("admin_notes", "") or ""
    stripe_pi   = booking.get("stripe_payment_intent_id", "")

    with st.container():
        st.markdown(
            f"""
            <div style="background:#f8fafc;border-radius:10px;border:1px solid #e2e8f0;
                        padding:1.25rem 1.5rem;margin-bottom:0.75rem">
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem;font-size:0.875rem">
                    <div><span style='color:#64748b'>Customer:</span> <strong>{user_p.get('full_name','—')}</strong></div>
                    <div><span style='color:#64748b'>Email:</span> <strong>{user_p.get('email','—')}</strong></div>
                    <div><span style='color:#64748b'>Phone:</span> <strong>{user_p.get('phone','—')}</strong></div>
                    <div><span style='color:#64748b'>Court:</span> <strong>{court.get('name','—')}</strong></div>
                    <div><span style='color:#64748b'>Duration:</span> <strong>{format_duration(booking.get('duration_minutes',0))}</strong></div>
                    <div><span style='color:#64748b'>Type:</span> <strong>{'Indoor' if court.get('indoor') else 'Outdoor'}</strong></div>
                    <div><span style='color:#64748b'>Base:</span> <strong>${base:.2f}</strong></div>
                    <div><span style='color:#64748b'>Discount:</span> <strong style='color:#10b981'>-${discount:.2f}</strong></div>
                    <div><span style='color:#64748b'>Total:</span> <strong style='color:#8b5cf6'>${total:.2f}</strong></div>
                </div>
                {"<div style='margin-top:0.75rem;font-size:0.85rem'><span style='color:#64748b'>Notes: </span>" + notes + "</div>" if notes else ""}
                {"<div style='margin-top:0.5rem;font-size:0.8rem;color:#94a3b8'><span>Admin notes: </span>" + admin_notes + "</div>" if admin_notes else ""}
                {"<div style='margin-top:0.5rem;font-size:0.75rem;color:#94a3b8'>Payment intent: <code>" + stripe_pi + "</code></div>" if stripe_pi else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Admin note form
        with st.expander("Add / Edit Admin Note"):
            new_note = st.text_area(
                "Note",
                value=admin_notes,
                key=f"note_txt_{bid}",
                label_visibility="collapsed",
                placeholder="Internal note visible only to admins…",
            )
            if st.button("Save Note", key=f"save_note_{bid}"):
                if add_admin_note(bid, new_note):
                    st.success("Note saved.")
                    st.rerun()
                else:
                    st.error("Failed to save note.")


def _render_cancel_panel(booking: dict, timezone: str):
    bid    = str(booking.get("id", ""))
    total  = float(booking.get("total_amount", 0))
    has_pi = bool(booking.get("stripe_payment_intent_id"))

    start_utc = parse_iso_datetime(str(booking.get("start_time_utc", "")))
    hours_left = hours_until_booking(start_utc) if start_utc else 0
    policy = get_refund_policy_for_cancellation(hours_left)
    suggested_refund = round(total * policy["refund_percent"], 2)

    with st.container():
        st.markdown(
            f"""
            <div style="background:#fff7ed;border:1.5px solid #fb923c;
                        border-radius:10px;padding:1rem 1.25rem;margin-bottom:0.5rem">
                <strong style="color:#c2410c">Admin Cancellation</strong><br>
                <span style="font-size:0.875rem;color:#64748b">
                    Refund policy: {policy['label']} — suggested refund: ${suggested_refund:.2f}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        reason = st.text_input(
            "Cancellation reason",
            key=f"cancel_reason_{bid}",
            placeholder="Maintenance, admin override, duplicate booking…",
        )
        issue_refund = st.checkbox(
            "Issue Stripe refund",
            value=has_pi and policy["eligible"],
            key=f"do_refund_{bid}",
            disabled=not has_pi,
        )
        if issue_refund:
            refund_amount = st.number_input(
                "Refund amount ($)",
                min_value=0.0,
                max_value=total,
                value=suggested_refund,
                step=0.01,
                key=f"refund_amt_{bid}",
            )
        else:
            refund_amount = 0.0

        ca, cb = st.columns(2)
        with ca:
            if st.button("Confirm Cancellation", type="primary",
                         key=f"do_cancel_{bid}", use_container_width=True):
                if not reason.strip():
                    st.error("Please provide a cancellation reason.")
                else:
                    with st.spinner("Cancelling…"):
                        result = admin_cancel_booking(
                            booking_id=bid,
                            reason=reason.strip(),
                            issue_refund=issue_refund,
                            refund_amount_dollars=refund_amount,
                        )
                    st.session_state["_bkmgmt_result"] = result
                    st.session_state.pop(f"_bkmgmt_cancel_{bid}", None)
                    st.rerun()
        with cb:
            if st.button("Keep Booking", key=f"keep_{bid}", use_container_width=True):
                st.session_state.pop(f"_bkmgmt_cancel_{bid}", None)
                st.rerun()


# ── Banner ────────────────────────────────────────────────────

def _show_action_banner():
    result = st.session_state.pop("_bkmgmt_result", None)
    if not result:
        return
    if result.get("success"):
        st.success(result["message"])
    else:
        st.error(result["message"])


render()
