"""
My Profile Page
================
Authenticated users can:
  1. View and edit personal information (name, phone)
  2. Change their password (via Supabase reset email)
  3. Accept the Terms of Service & Liability Waiver
  4. View membership and account metadata

The waiver must be accepted before a first booking can be made.
(Enforced by require_waiver() in components/auth_guard.py on booking pages.)
"""

import streamlit as st
from components.auth_guard import require_auth, show_auth_status_sidebar
from services.auth_service import get_auth_service, AuthError
from utils.time_utils import parse_iso_datetime, format_datetime_local


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    require_auth("Please log in to view your profile.")

    user = auth_service.get_current_user()
    profile = auth_service.get_current_profile()

    # Reload profile if missing (e.g., arrived directly at this URL)
    if not profile and user:
        profile = auth_service.get_profile(
            str(user.id), st.session_state.get("access_token", "")
        )
        st.session_state.profile = profile

    if not profile:
        st.error("Could not load your profile. Please log out and sign in again.")
        return

    # ── Waiver Banner ────────────────────────────────────────
    if not profile.get("waiver_accepted"):
        st.warning(
            "⚠️ **Action required:** You must accept our Terms & Liability Waiver "
            "before making your first booking. See the **Terms & Waiver** tab below.",
        )

    st.markdown("## 👤 My Profile")

    tab_info, tab_security, tab_waiver = st.tabs(
        ["📋 Personal Info", "🔒 Account & Security", "📄 Terms & Waiver"]
    )

    with tab_info:
        _render_personal_info(auth_service, user, profile)

    with tab_security:
        _render_security(auth_service, user)

    with tab_waiver:
        _render_waiver(auth_service, user, profile)


# ── Tab: Personal Info ───────────────────────────────────────

def _render_personal_info(auth_service, user, profile: dict):
    st.markdown("### Personal Information")

    # Read-only account summary
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Email:** {user.email}")
        role = profile.get("role", "player").replace("_", " ").title()
        st.markdown(f"**Account Type:** {role}")
    with col2:
        membership = profile.get("membership_type", "none").title()
        st.markdown(f"**Membership:** {membership}")
        joined_raw = profile.get("created_at")
        if joined_raw:
            joined_dt = parse_iso_datetime(joined_raw)
            joined_str = format_datetime_local(joined_dt, fmt="%B %Y") if joined_dt else "—"
        else:
            joined_str = "—"
        st.markdown(f"**Member Since:** {joined_str}")

    waiver_status = "✅ Accepted" if profile.get("waiver_accepted") else "❌ Not accepted"
    st.markdown(f"**Waiver Status:** {waiver_status}")

    st.markdown("---")
    st.markdown("**Edit Profile**")

    with st.form("profile_edit_form"):
        full_name = st.text_input(
            "Full Name *",
            value=profile.get("full_name", ""),
            placeholder="Jane Smith",
        )
        phone = st.text_input(
            "Phone Number",
            value=profile.get("phone", ""),
            placeholder="(555) 123-4567",
            help="Optional — for booking reminders",
        )
        submitted = st.form_submit_button("Save Changes", type="primary")

    if submitted:
        with st.spinner("Saving…"):
            try:
                updated = auth_service.update_profile(
                    user_id=str(user.id),
                    access_token=st.session_state.access_token,
                    full_name=full_name,
                    phone=phone,
                )
                st.session_state.profile = updated
                st.success("✅ Profile updated successfully!")
                st.rerun()
            except AuthError as e:
                st.error(str(e))
            except Exception:
                st.error("Failed to update profile. Please try again.")


# ── Tab: Security ────────────────────────────────────────────

def _render_security(auth_service, user):
    st.markdown("### Account & Security")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Email:** {user.email}")
        uid_short = str(user.id)[:8]
        st.markdown(f"**User ID:** `{uid_short}…`")
    with col2:
        st.markdown("**Password:** ••••••••")

    st.markdown("---")
    st.markdown("#### Change Password")
    st.markdown(
        "We'll send a secure password-reset link to your registered email address. "
        "You'll be prompted to set a new password when you click the link."
    )

    if st.button("Send Password Reset Email", type="secondary"):
        with st.spinner("Sending…"):
            try:
                result = auth_service.reset_password(user.email)
                st.success(result["message"])
            except AuthError as e:
                st.error(str(e))

    st.markdown("---")
    st.markdown("#### Sign Out")

    if st.button("Log Out of This Session", type="secondary"):
        access_token = st.session_state.get("access_token")
        auth_service.sign_out(access_token)
        auth_service.clear_session_state()
        st.success("Signed out successfully.")
        st.rerun()

    with st.expander("⚠️ Sign out of ALL devices"):
        st.caption(
            "This revokes all active sessions for your account. "
            "You will need to sign in again on all your devices."
        )
        if st.button("Sign Out Everywhere", type="secondary", key="signout_all"):
            access_token = st.session_state.get("access_token")
            auth_service.sign_out(access_token)
            auth_service.clear_session_state()
            st.success("Signed out of all sessions.")
            st.rerun()


# ── Tab: Waiver ───────────────────────────────────────────────

def _render_waiver(auth_service, user, profile: dict):
    st.markdown("### Terms of Service & Liability Waiver")

    # Show accepted status if already done
    if profile.get("waiver_accepted"):
        accepted_raw = profile.get("waiver_accepted_at")
        if accepted_raw:
            accepted_dt = parse_iso_datetime(accepted_raw)
            date_str = format_datetime_local(accepted_dt, fmt="%B %d, %Y at %I:%M %p") if accepted_dt else "a previous session"
        else:
            date_str = "a previous session"

        st.success(
            f"✅ **Waiver accepted on {date_str}.** You're cleared to book courts!"
        )
        st.markdown("---")

    # Always display the waiver text (expanded if not yet accepted)
    with st.expander(
        "📄 Read Full Terms & Liability Waiver",
        expanded=not profile.get("waiver_accepted"),
    ):
        st.markdown(
            """
**SPORTSPLEX FACILITY USE AGREEMENT & LIABILITY WAIVER**

*Effective Date: January 1, 2025*

---

**1. ACCEPTANCE OF RISK**

I understand and acknowledge that participating in sports and physical activities at SportsPlex carries inherent risks of physical injury, including but not limited to sprains, strains, fractures, concussions, and other bodily harm. I voluntarily assume all such risks.

**2. RELEASE OF LIABILITY**

In consideration of being permitted to use SportsPlex facilities, I hereby release, waive, discharge, and covenant not to sue SportsPlex, LLC, its owners, officers, employees, agents, volunteers, and representatives from any and all claims, demands, losses, or causes of action arising from, or related to, my participation in any activities at this facility, including claims of negligence.

**3. FACILITY RULES — I agree to:**
- Follow all posted facility rules and staff instructions at all times
- Use equipment properly and report any damage or hazards immediately
- Wear appropriate athletic footwear on all court surfaces
- Not engage in reckless behaviour that may endanger myself or other participants
- Respect all other players, staff, and facility property
- Not bring outside food, drinks (except water), or equipment onto court surfaces without permission
- Vacate the court promptly at the end of my booked time

**4. BOOKING & CANCELLATION POLICY**

| Cancellation Window | Refund |
|---|---|
| More than 24 hours before booking start | **Full refund (100%)** |
| 12–24 hours before booking start | **Partial refund (50%)** |
| Less than 12 hours before booking start | **No refund** |
| No-show (did not cancel) | **No refund** |

*Admin overrides may be applied at SportsPlex's sole discretion for exceptional circumstances.*

**5. FULL-DAY EVENT BOOKINGS**

Full-day event bookings require advance approval from SportsPlex management. Approved events require a deposit at the time of confirmation. Cancellation of approved events may carry additional terms.

**6. MEDIA RELEASE**

I grant SportsPlex permission to use photographs or videos taken of me during facility use for promotional and marketing purposes, unless I submit a written opt-out request to management.

**7. GOVERNING LAW**

This agreement shall be governed by the laws of the State of New York. Any disputes arising from this agreement shall be resolved by binding arbitration in New York County.

**8. SEVERABILITY**

If any provision of this waiver is found to be invalid or unenforceable, the remaining provisions shall remain in full force and effect.

---

*By accepting this waiver, you acknowledge that you have read, understood, and voluntarily agree to all terms stated above, and that this is a legally binding agreement.*
            """
        )

    # Acceptance form (only show if not yet accepted)
    if not profile.get("waiver_accepted"):
        st.markdown("---")

        with st.form("waiver_form"):
            cb_waiver = st.checkbox(
                "✅ I have read and I agree to the Terms of Service and Liability Waiver above. "
                "I understand this is a legally binding agreement."
            )
            cb_age = st.checkbox(
                "✅ I confirm that I am 18 years of age or older, or have obtained written "
                "parental/guardian consent to participate."
            )
            submitted = st.form_submit_button(
                "Accept Waiver & Enable Booking",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not cb_waiver or not cb_age:
                st.error("Please check both boxes to confirm your agreement.")
            else:
                with st.spinner("Recording acceptance…"):
                    success = auth_service.accept_waiver(
                        user_id=str(user.id),
                        access_token=st.session_state.access_token,
                    )
                    if success:
                        # Refresh profile in session state
                        refreshed = auth_service.get_profile(
                            str(user.id), st.session_state.access_token
                        )
                        st.session_state.profile = refreshed
                        st.success("✅ Waiver accepted! You can now book courts.")
                        st.rerun()
                    else:
                        st.error(
                            "Failed to save your acceptance. Please try again or contact support."
                        )


render()
