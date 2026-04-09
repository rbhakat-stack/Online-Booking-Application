"""
Booking Confirmation Page
==========================
Users review their selected slot and confirm their booking.

Flow:
  1. Read slot + court + price from session state (set by availability.py)
  2. Re-validate slot is still available (quick DB check)
  3. Display full booking summary + pricing + cancellation policy
  4. User optionally enters notes and a promo code
  5. "Create Hold & Pay" →
       a. Create booking hold (10-min expiry)
       b. Create Stripe Checkout session (via payment_service)
       c. Show "Proceed to Stripe" button + auto-redirect link
  6. On return from Stripe → payment_success.py verifies payment → confirms booking
"""

from datetime import date
from typing import Optional

import streamlit as st

from components.auth_guard import require_auth, show_auth_status_sidebar, require_waiver
from components.pricing_summary import render_pricing_summary
from services.auth_service import get_auth_service
from services.booking_service import (
    create_hold,
    BookingError,
    BookingConflictError,
    generate_idempotency_key,
)
from services.pricing_service import calculate_price
from db.supabase_client import get_client, get_session_client, get_admin_client
from db.queries import (
    get_bookings_for_court_on_date,
    get_active_holds_for_court,
    get_promo_code,
    get_facility_settings,
)
from utils.time_utils import (
    format_date,
    format_time,
    format_duration,
    parse_iso_datetime,
    is_hold_expired,
)
from utils.constants import SessionKey, BookingStatus
from utils.validators import validate_notes, validate_promo_code, sanitize_text


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()

    # ── Stripe cancel redirect handler ────────────────────────
    # When the user clicks "Back" on Stripe's checkout page, Stripe redirects
    # to /book?stripe_cancelled=1&hold_id=<uuid>.  We immediately expire the
    # hold so the slot is released for other users (and for this user's retry).
    _handle_stripe_cancel()

    require_auth("Please log in to complete your booking.")
    require_waiver()    # Ensure waiver accepted before booking

    # ── Read session state ────────────────────────────────────
    slot = st.session_state.get("_booking_slot")
    price_info = st.session_state.get("_booking_price_info")
    court = st.session_state.get("_booking_court")
    facility_id = st.session_state.get(SessionKey.SELECTED_FACILITY_ID)
    court_id = st.session_state.get(SessionKey.SELECTED_COURT_ID)
    start_utc = st.session_state.get(SessionKey.SELECTED_START_TIME)
    duration_minutes = st.session_state.get(SessionKey.SELECTED_DURATION)
    booking_date = st.session_state.get(SessionKey.SELECTED_DATE)

    # Guard: required session state missing
    if not all([slot, facility_id, court_id, start_utc, duration_minutes, booking_date]):
        st.warning("⚠️ No slot selected. Please go back and choose an available time.")
        if st.button("← Back to Availability", type="primary"):
            st.switch_page("pages/availability.py")
        return

    # ── Check active hold ────────────────────────────────────
    active_hold = _get_active_hold()
    if active_hold and not is_hold_expired(str(active_hold.get("expires_at", ""))):
        _render_hold_active_state(active_hold, slot, court, booking_date, duration_minutes, price_info)
        return

    # ── Main booking form ─────────────────────────────────────
    st.markdown("## 📋 Review Your Booking")
    st.markdown("Double-check your details and complete your booking below.")

    col_main, col_side = st.columns([2, 1])

    with col_main:
        _render_booking_summary(slot, court, booking_date, duration_minutes)

    with col_side:
        # Re-calculate price if not available (e.g., page refresh)
        if not price_info:
            price_info = _recalculate_price(
                facility_id, court_id, booking_date, slot, duration_minutes,
                auth_service.get_current_profile() or {},
            )
        if price_info:
            render_pricing_summary(
                price_info=price_info,
                cancellation_window_hours=_get_setting(facility_id, "cancellation_window_hours", 24),
                partial_refund_window_hours=_get_setting(facility_id, "partial_refund_window_hours", 12),
            )

    st.markdown("---")

    # ── Promo Code ────────────────────────────────────────────
    promo_result = _render_promo_code_section(facility_id)
    if promo_result:
        # Re-render price with promo applied
        applied_promo = promo_result
    else:
        applied_promo = None

    # ── Notes ─────────────────────────────────────────────────
    notes = st.text_area(
        "📝 Special Requests / Notes (optional)",
        max_chars=500,
        placeholder="e.g., Please ensure net height is regulation for competitive play.",
        key="booking_notes",
    )

    st.markdown("---")

    # ── Slot Availability Check ───────────────────────────────
    slot_still_available = _check_slot_still_available(
        court_id=court_id,
        booking_date=str(booking_date),
        start_utc=start_utc,
    )

    if not slot_still_available:
        st.error(
            "⚠️ **This slot was just taken by another user.** "
            "Please go back and select a different time."
        )
        if st.button("← Choose Another Slot", type="primary"):
            _clear_booking_session()
            st.switch_page("pages/availability.py")
        return

    # ── Confirm & Pay ─────────────────────────────────────────
    _render_payment_section(
        auth_service=auth_service,
        facility_id=facility_id,
        court_id=court_id,
        court=court,
        start_utc=start_utc,
        booking_date=booking_date,
        duration_minutes=duration_minutes,
        price_info=price_info,
        notes=notes,
        applied_promo=applied_promo,
    )


# ── Sub-sections ──────────────────────────────────────────────

def _render_booking_summary(slot, court, booking_date: date, duration_minutes: int):
    """Render the main booking detail card."""
    court_name = court["name"] if court else "Auto-assigned"
    sport = court.get("sport_type", "").title() if court else ""
    indoor = court.get("indoor", True) if court else True

    sport_icons = {
        "pickleball": "🏓", "badminton": "🏸", "tennis": "🎾", "karate": "🥋",
    }
    sport_icon = sport_icons.get(court.get("sport_type", "") if court else "", "🏟️")

    st.markdown(
        f"""
        <div style="background:#f8f9ff;border-radius:12px;padding:1.5rem;border:1px solid #e0e0f0">
            <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem">
                <span style="font-size:2.5rem">{sport_icon}</span>
                <div>
                    <div style="font-weight:800;font-size:1.1rem;color:#1a1a2e">{court_name}</div>
                    <div style="color:#6b7280;font-size:0.875rem">
                        {sport} · {'Indoor' if indoor else 'Outdoor'}
                    </div>
                </div>
            </div>
            <table style="width:100%;font-size:0.9rem;border-collapse:collapse">
                <tr>
                    <td style="color:#6b7280;padding:0.25rem 0;width:40%">Date</td>
                    <td style="font-weight:600;color:#1a1a2e">{format_date(booking_date)}</td>
                </tr>
                <tr>
                    <td style="color:#6b7280;padding:0.25rem 0">Time</td>
                    <td style="font-weight:600;color:#1a1a2e">{slot['label']}</td>
                </tr>
                <tr>
                    <td style="color:#6b7280;padding:0.25rem 0">Duration</td>
                    <td style="font-weight:600;color:#1a1a2e">{format_duration(duration_minutes)}</td>
                </tr>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_promo_code_section(facility_id: str) -> Optional[dict]:
    """Render promo code input. Returns promo record if valid code entered."""
    with st.expander("🏷️ Have a promo code?", expanded=False):
        col1, col2 = st.columns([3, 1])
        with col1:
            code = st.text_input(
                "Promo Code",
                placeholder="Enter code (e.g. SUMMER20)",
                key="promo_code_input",
                label_visibility="collapsed",
            )
        with col2:
            apply_clicked = st.button("Apply", key="apply_promo")

        if apply_clicked and code.strip():
            valid, err = validate_promo_code(code)
            if not valid:
                st.error(err)
                return None

            client = get_client()
            promo = get_promo_code(client, code)
            if not promo:
                st.error("❌ Invalid or expired promo code.")
                return None

            # Check usage limit
            max_uses = promo.get("max_uses")
            used = promo.get("used_count", 0)
            if max_uses and used >= max_uses:
                st.error("❌ This promo code has reached its usage limit.")
                return None

            discount_type = promo.get("discount_type", "percent")
            discount_value = float(promo.get("discount_value", 0))
            if discount_type == "percent":
                display = f"{discount_value:.0f}% off"
            else:
                display = f"${discount_value:.2f} off"

            st.success(f"✅ Promo code applied: **{promo['description'] or code.upper()}** — {display}")
            return promo

    return None


def _render_hold_active_state(hold, slot, court, booking_date, duration_minutes, price_info):
    """
    Show the state when a hold is already active for this slot.
    If a Stripe session exists on the hold, offer to resume payment.
    """
    from utils.time_utils import parse_iso_datetime, now_utc
    expires_at = parse_iso_datetime(str(hold.get("expires_at", "")))
    if expires_at:
        remaining_secs = max(0, (expires_at - now_utc()).total_seconds())
        remaining_min = int(remaining_secs / 60)
        remaining_sec = int(remaining_secs % 60)
        time_left = f"{remaining_min}m {remaining_sec:02d}s"
    else:
        time_left = "a few minutes"

    st.warning(
        f"⏳ **Your slot is on hold — {time_left} remaining.** "
        "Complete payment before the hold expires."
    )

    col_main, col_side = st.columns([2, 1])
    with col_main:
        _render_booking_summary(slot, court, booking_date, duration_minutes)
    with col_side:
        if price_info:
            render_pricing_summary(price_info, show_policy=False)

    st.markdown("---")

    # If there is already a Stripe checkout URL stored for this hold, show it
    stripe_url = st.session_state.get("stripe_checkout_url")
    if stripe_url:
        st.success("A payment session is ready. Click below to complete your payment.")
        st.link_button(
            "🔒 Complete Payment on Stripe →",
            stripe_url,
            type="primary",
            use_container_width=True,
        )
        st.markdown(
            f'<p style="text-align:center;font-size:0.8rem;color:#9ca3af;">'
            f'Or <a href="{stripe_url}" target="_self" style="color:#4361ee">click here</a> '
            f'if the button does not work.</p>',
            unsafe_allow_html=True,
        )
    else:
        # Hold exists but no Stripe session yet — let them create one
        st.info(
            "Your slot is reserved. Click below to proceed to payment "
            "before the hold expires."
        )
        auth_service = get_auth_service()
        user = auth_service.get_current_user()
        total = float(price_info.get("total_amount", 0)) if price_info else 0
        if user and st.button(
            f"🔒 Proceed to Payment — ${total:.2f}",
            type="primary",
            use_container_width=True,
        ):
            _create_stripe_session_and_redirect(
                hold=hold,
                price_info=price_info,
                court=court,
                booking_date=booking_date,
                user_email=user.email,
            )

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Release Hold & Choose Different Slot", use_container_width=True):
            from services.booking_service import release_hold
            release_hold(
                access_token=st.session_state.access_token,
                refresh_token=st.session_state.get("refresh_token", ""),
                hold_id=hold["id"],
                user_id=str(st.session_state.user.id),
            )
            st.session_state.pop("stripe_checkout_url", None)
            _clear_booking_session()
            st.switch_page("pages/availability.py")


def _render_payment_section(
    auth_service,
    facility_id: str,
    court_id: str,
    court: Optional[dict],
    start_utc,
    booking_date: date,
    duration_minutes: int,
    price_info: Optional[dict],
    notes: str,
    applied_promo: Optional[dict],
):
    """Render the confirm + pay button and handle the hold creation."""
    total = float(price_info.get("total_amount", 0)) if price_info else 0

    # Apply promo discount for display
    if applied_promo:
        discount_type = applied_promo.get("discount_type", "percent")
        discount_value = float(applied_promo.get("discount_value", 0))
        if discount_type == "percent":
            promo_discount = round(total * discount_value / 100, 2)
        else:
            promo_discount = min(discount_value, total)
        total_after_promo = max(0, round(total - promo_discount, 2))
    else:
        promo_discount = 0
        total_after_promo = total

    # Build a promo-adjusted copy of price_info so Stripe shows the right total
    adjusted_price_info = dict(price_info) if price_info else {}
    adjusted_price_info["total_amount"] = total_after_promo
    if applied_promo:
        adjusted_price_info["discount_amount"] = promo_discount

    # Terms checkbox
    agreed = st.checkbox(
        "I confirm I have read and agree to the cancellation policy shown above.",
        key="terms_agreed",
    )

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#1a1a2e,#4361ee);
                    color:#fff;border-radius:12px;padding:1.25rem;
                    text-align:center;margin-bottom:1rem">
            <div style="font-size:0.9rem;opacity:0.8">Total Due</div>
            <div style="font-size:2.5rem;font-weight:800">${total_after_promo:.2f}</div>
            <div style="font-size:0.8rem;opacity:0.7">Secure checkout via Stripe</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not agreed:
        st.info("Please check the box above to confirm and proceed.")
        return

    # Confirm button
    if st.button(
        f"🔒 Create Hold & Proceed to Payment — ${total_after_promo:.2f}",
        type="primary",
        use_container_width=True,
    ):
        _do_create_hold(
            auth_service=auth_service,
            facility_id=facility_id,
            court_id=court_id,
            court=court,
            start_utc=start_utc,
            booking_date=booking_date,
            duration_minutes=duration_minutes,
            estimated_amount=total_after_promo,
            price_info=adjusted_price_info,
            notes=sanitize_text(notes),
            promo_id=applied_promo.get("id") if applied_promo else None,
        )


def _do_create_hold(
    auth_service,
    facility_id: str,
    court_id: str,
    court: Optional[dict],
    start_utc,
    booking_date: date,
    duration_minutes: int,
    estimated_amount: float,
    price_info: Optional[dict],
    notes: str,
    promo_id: Optional[str],
):
    """Execute hold creation and handle errors."""
    user = auth_service.get_current_user()
    if not user:
        st.error("Session expired. Please log in again.")
        st.switch_page("pages/login.py")
        return

    # Generate or reuse idempotency key
    idem_key = st.session_state.get("booking_idempotency_key")
    if not idem_key:
        idem_key = generate_idempotency_key()
        st.session_state["booking_idempotency_key"] = idem_key

    # Calculate end_time_utc from start + duration
    from datetime import timedelta
    end_utc = start_utc + timedelta(minutes=duration_minutes)

    settings = _load_settings_cached(facility_id)
    hold_expiry = int(settings.get("hold_expiry_minutes", 10))

    with st.spinner("Reserving your slot…"):
        try:
            hold = create_hold(
                access_token=st.session_state.access_token,
                refresh_token=st.session_state.get("refresh_token", ""),
                facility_id=facility_id,
                court_id=court_id,
                user_id=str(user.id),
                booking_date=booking_date.isoformat(),
                start_time_utc=start_utc,
                end_time_utc=end_utc,
                duration_minutes=duration_minutes,
                estimated_amount=estimated_amount,
                idempotency_key=idem_key,
                promo_code_id=promo_id,
                hold_expiry_minutes=hold_expiry,
            )

            # Store hold in session state
            # Note: booking_notes is already persisted automatically by the
            # st.text_area widget (key="booking_notes") — do NOT write it here
            # or Streamlit raises "cannot be modified after widget is instantiated".
            st.session_state["active_hold"] = hold

            st.success(f"✅ Slot reserved — {hold_expiry} minutes to complete payment!")

            # Create Stripe Checkout session and show payment button
            _create_stripe_session_and_redirect(
                hold=hold,
                price_info=price_info,
                court=court,
                booking_date=booking_date,
                user_email=user.email,
            )

        except BookingConflictError as e:
            st.error(f"⚠️ {e}")
            st.session_state["booking_idempotency_key"] = None  # Allow retry with new key
            if st.button("← Choose Another Slot", type="primary"):
                _clear_booking_session()
                st.switch_page("pages/availability.py")

        except BookingError as e:
            st.error(str(e))
            st.session_state["booking_idempotency_key"] = None


# ── Stripe Session Helper ─────────────────────────────────────

def _create_stripe_session_and_redirect(
    hold: dict,
    price_info: Optional[dict],
    court: Optional[dict],
    booking_date,
    user_email: str,
) -> None:
    """
    Create a Stripe Checkout session for the active hold and render
    a payment button. Called after hold creation and when hold is already active.

    On success: renders a link_button that sends the user to Stripe.
    On error: shows a user-friendly error; hold remains active so user can retry.
    """
    from services.payment_service import create_checkout_session, PaymentError
    from utils.config import get_config

    config = get_config()

    # Use stored price_info or build a minimal one from the hold
    if not price_info:
        price_info = {
            "total_amount": float(hold.get("estimated_amount", 0)),
            "base_amount":  float(hold.get("estimated_amount", 0)),
            "discount_amount": 0.0,
        }

    if not court:
        court = {"name": "Court", "sport_type": ""}

    total = float(price_info.get("total_amount", 0))

    with st.spinner("Preparing secure checkout…"):
        try:
            checkout = create_checkout_session(
                hold=hold,
                price_info=price_info,
                court=court,
                booking_date=booking_date,
                user_email=user_email,
                app_url=config.app_url,
                notes=st.session_state.get("booking_notes", ""),
            )

            # Store checkout URL so the active-hold view can show it on rerun
            st.session_state["stripe_checkout_url"] = checkout["url"]
            st.session_state[SessionKey.STRIPE_SESSION_ID] = checkout["session_id"]

        except PaymentError as e:
            st.error(f"Payment setup failed: {e}")
            return
        except Exception as e:
            st.error("Payment service unavailable. Please try again in a moment.")
            return

    # ── Show payment button ───────────────────────────────────
    st.markdown("---")
    st.markdown(
        """
        <div style="text-align:center;padding:0.5rem 0 1rem">
            <div style="font-size:1.1rem;font-weight:700;color:#1a1a2e">
                Complete your payment on Stripe
            </div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:0.25rem">
                Secure · Encrypted · Powered by Stripe
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.link_button(
            f"🔒 Pay ${total:.2f} on Stripe →",
            checkout["url"],
            type="primary",
            use_container_width=True,
        )

    st.markdown(
        f"<p style='text-align:center;font-size:0.78rem;color:#9ca3af;margin-top:0.5rem'>"
        f"You will be redirected to Stripe's secure payment page. "
        f"After payment, you'll return here automatically.<br>"
        f"<a href='{checkout['url']}' style='color:#4361ee'>Click here if not redirected</a>"
        f"</p>",
        unsafe_allow_html=True,
    )

    st.caption(
        "🔐 Your card details are handled entirely by Stripe. "
        "SportsPlex never sees or stores your payment information."
    )


# ── Utility Helpers ───────────────────────────────────────────

def _handle_stripe_cancel() -> None:
    """
    Called at the top of render() before any other logic.

    When the user clicks "Back" on Stripe's checkout page, Stripe redirects to
    /book?stripe_cancelled=1&hold_id=<uuid>.  This function:
      1. Detects that cancel redirect via query params
      2. Expires the booking hold immediately so the slot is freed
      3. Clears booking session state
      4. Redirects the user to availability so they can choose a different slot
         (or re-select the same one — the hold is now gone)

    Without this, the hold would linger for up to 10 minutes, blocking the user
    from re-booking the same slot (they would see "held by another user").
    """
    params = st.query_params
    if params.get("stripe_cancelled") != "1":
        return

    hold_id = params.get("hold_id", "")

    # Expire the hold
    if hold_id:
        try:
            from services.booking_service import release_hold
            access_token = st.session_state.get("access_token", "")
            refresh_token = st.session_state.get("refresh_token", "")
            user = st.session_state.get("user")
            if user and access_token:
                release_hold(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    hold_id=hold_id,
                    user_id=str(user.id),
                )
            elif hold_id:
                # Fallback: use admin client to expire the hold even if
                # the user's session tokens are unavailable after redirect
                from db.supabase_client import get_admin_client
                from utils.time_utils import now_utc
                get_admin_client().table("booking_holds").update({
                    "expires_at": now_utc().isoformat(),
                }).eq("id", hold_id).execute()
        except Exception as exc:
            # Non-critical — hold will expire on its own within 10 minutes
            import logging
            logging.getLogger(__name__).warning(f"Could not release hold {hold_id} on cancel: {exc}")

    # Clear booking session state
    for key in ["active_hold", "booking_idempotency_key", "stripe_checkout_url",
                SessionKey.STRIPE_SESSION_ID]:
        st.session_state.pop(key, None)

    # Clear query params then redirect to availability
    st.query_params.clear()
    st.info("Payment cancelled — your slot hold has been released. Choose a slot to try again.")
    if st.button("← Choose a Slot", type="primary"):
        _clear_booking_session()
        st.switch_page("pages/availability.py")
    st.stop()


def _get_active_hold() -> Optional[dict]:
    hold = st.session_state.get("active_hold")
    if hold and not is_hold_expired(str(hold.get("expires_at", ""))):
        return hold
    return None


def _check_slot_still_available(
    court_id: str,
    booking_date: str,
    start_utc,
) -> bool:
    """
    Quick check that the slot hasn't been taken since the user selected it.
    Checks both confirmed bookings AND active holds from other users.
    The current user's own hold is excluded so they can re-enter the booking
    page after a failed payment attempt without being falsely blocked.
    """
    try:
        from datetime import timedelta
        from utils.time_utils import parse_iso_datetime

        # Use admin client so RLS does not hide other users' bookings/holds.
        # With the anon key, Postgres RLS restricts reads to the caller's own
        # rows — every slot would appear free and the real conflict would only
        # surface (too late) inside create_hold, giving a confusing error.
        client = get_admin_client()
        duration = st.session_state.get(SessionKey.SELECTED_DURATION, 60)
        end_utc = start_utc + timedelta(minutes=duration)

        # Reject slots that have already started (same guard as the availability engine)
        from utils.time_utils import now_utc
        if start_utc <= now_utc():
            return False

        # Current user's ID — their own hold should not block them
        current_user_id = ""
        user = st.session_state.get("user")
        if user:
            try:
                current_user_id = str(user.id)
            except Exception:
                pass

        # Check confirmed bookings (the only statuses that truly occupy a slot)
        bookings = get_bookings_for_court_on_date(
            client, court_id, booking_date,
            conflict_statuses=[BookingStatus.PENDING_PAYMENT, BookingStatus.CONFIRMED],
        )
        for b in bookings:
            b_start = parse_iso_datetime(str(b.get("start_time_utc", "")))
            b_end = parse_iso_datetime(str(b.get("end_time_utc", "")))
            if b_start and b_end and start_utc < b_end and end_utc > b_start:
                return False

        # Also check active holds from OTHER users
        holds = get_active_holds_for_court(
            client, court_id, booking_date,
            exclude_user_id=current_user_id,
        )
        for h in holds:
            h_start = parse_iso_datetime(str(h.get("start_time_utc", "")))
            h_end = parse_iso_datetime(str(h.get("end_time_utc", "")))
            if h_start and h_end and start_utc < h_end and end_utc > h_start:
                return False

        return True
    except Exception:
        return True  # Optimistic — let DB constraint catch real conflicts


def _recalculate_price(
    facility_id: str,
    court_id: str,
    booking_date: date,
    slot: dict,
    duration_minutes: int,
    profile: dict,
) -> Optional[dict]:
    """Recalculate price from scratch (used after page refresh)."""
    try:
        client = get_client()
        from db.queries import get_pricing_rules, get_court_by_id
        pricing_rules = get_pricing_rules(client, facility_id)
        court = get_court_by_id(client, court_id)
        return calculate_price(
            pricing_rules=pricing_rules,
            booking_date=booking_date,
            start_time=slot["start_time"],
            duration_minutes=duration_minutes,
            sport_type=court.get("sport_type") if court else None,
            court_id=court_id,
            membership_type=profile.get("membership_type", "none"),
        )
    except Exception:
        return None


def _load_settings_cached(facility_id: str) -> dict:
    """Load facility settings with defaults."""
    try:
        client = get_client()
        settings = get_facility_settings(client, facility_id)
        return settings or {}
    except Exception:
        return {}


def _get_setting(facility_id: str, key: str, default) -> int:
    settings = _load_settings_cached(facility_id)
    return int(settings.get(key, default))


def _clear_booking_session():
    for key in [
        "_booking_slot", "_booking_price_info", "_booking_court",
        "active_hold", "booking_idempotency_key", "booking_notes",
        SessionKey.SELECTED_COURT_ID, SessionKey.SELECTED_START_TIME,
        "_avail_selected_start_utc", "_avail_selected_slot",
    ]:
        st.session_state.pop(key, None)


render()
