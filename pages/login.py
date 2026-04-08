"""
Login / Sign Up / Password Reset Page
========================================
Three-tab layout:
  Tab 1 — Sign In      (email + password)
  Tab 2 — Create Account (registration)
  Tab 3 — Reset Password (sends Supabase magic link)

After a successful sign-in, the user is redirected based on their role:
  - Admin → admin dashboard (Phase 6)
  - Player → availability page (Phase 3)

Redirected here from protected pages when not authenticated.
"""

import streamlit as st
from services.auth_service import get_auth_service, AuthError
from components.auth_guard import show_auth_status_sidebar


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()

    # Redirect if already logged in ─────────────────────────
    if auth_service.is_authenticated():
        st.success("✅ You're already signed in!")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("📅 Book a Court", type="primary", use_container_width=True):
                st.switch_page("pages/availability.py")
            if st.button("📋 My Bookings", use_container_width=True):
                st.switch_page("pages/my_bookings.py")
        return

    # Page header ────────────────────────────────────────────
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            """
            <div style="text-align:center;padding:1.5rem 0 1rem">
                <h2 style="color:#1a1a2e;font-weight:800">Welcome to SportsPlex</h2>
                <p style="color:#6b7280">Sign in or create a new account below</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Surface a success message (e.g., "email sent") from a previous action
        msg = st.session_state.get("auth_success_message")
        if msg:
            st.success(msg)
            st.session_state.auth_success_message = None

        tab_signin, tab_signup, tab_reset = st.tabs(
            ["🔑 Sign In", "📝 Create Account", "🔒 Reset Password"]
        )

        with tab_signin:
            _render_sign_in(auth_service)

        with tab_signup:
            _render_sign_up(auth_service)

        with tab_reset:
            _render_reset(auth_service)


# ── Tab: Sign In ─────────────────────────────────────────────

def _render_sign_in(auth_service):
    st.markdown("#### Sign in to your account")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email Address", placeholder="you@example.com")
        password = st.text_input("Password", type="password", placeholder="Your password")

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button(
                "Sign In", type="primary", use_container_width=True
            )

    if submitted:
        _do_sign_in(auth_service, email, password)

    st.markdown(
        "<p style='text-align:center;font-size:0.85rem;color:#6b7280;margin-top:0.5rem'>"
        "Don't have an account? Switch to the <strong>Create Account</strong> tab above.</p>",
        unsafe_allow_html=True,
    )


def _do_sign_in(auth_service, email: str, password: str):
    if not email.strip() or not password:
        st.error("Please enter both your email and password.")
        return

    with st.spinner("Signing in…"):
        try:
            result = auth_service.sign_in(email, password)
            auth_service.save_session_to_state(result)

            role = (result.get("profile") or {}).get("role", "player")
            st.success("Welcome back! Redirecting…")
            st.rerun()

        except AuthError as e:
            st.error(str(e))
        except Exception:
            st.error("An unexpected error occurred. Please try again.")


# ── Tab: Sign Up ─────────────────────────────────────────────

def _render_sign_up(auth_service):
    st.markdown("#### Create a new account")

    with st.form("signup_form", clear_on_submit=False):
        full_name = st.text_input(
            "Full Name *",
            placeholder="Jane Smith",
            help="Your name as it will appear on bookings",
        )
        email = st.text_input("Email Address *", placeholder="you@example.com")
        phone = st.text_input(
            "Phone Number",
            placeholder="(555) 123-4567",
            help="Optional — for booking reminders",
        )
        st.markdown("**Password *** — min. 8 chars, 1 uppercase, 1 number")
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Create a strong password",
            label_visibility="collapsed",
        )
        confirm = st.text_input(
            "Confirm Password",
            type="password",
            placeholder="Repeat your password",
            label_visibility="collapsed",
        )
        terms = st.checkbox(
            "I agree to the Terms of Service and Privacy Policy",
            help="You can read these by expanding the waiver section in your Profile page after sign-up.",
        )

        submitted = st.form_submit_button(
            "Create Account", type="primary", use_container_width=True
        )

    if submitted:
        _do_sign_up(auth_service, full_name, email, phone, password, confirm, terms)

    # Password rules helper
    st.markdown(
        """
        <div style="background:#f8f9ff;border-radius:8px;padding:0.75rem 1rem;
                    font-size:0.8rem;color:#555;margin-top:0.5rem;border:1px solid #e0e0f0">
        <strong>Password requirements:</strong><br>
        ✓ &nbsp;At least 8 characters<br>
        ✓ &nbsp;At least 1 uppercase letter<br>
        ✓ &nbsp;At least 1 number
        </div>
        """,
        unsafe_allow_html=True,
    )


def _do_sign_up(auth_service, full_name, email, phone, password, confirm, terms):
    errors = []

    if not full_name.strip():
        errors.append("Full name is required.")
    if not email.strip():
        errors.append("Email address is required.")
    if not password:
        errors.append("Password is required.")
    if password != confirm:
        errors.append("Passwords do not match.")
    if not terms:
        errors.append("You must accept the Terms of Service to create an account.")

    if errors:
        for err in errors:
            st.error(err)
        return

    with st.spinner("Creating your account…"):
        try:
            result = auth_service.sign_up(
                email=email,
                password=password,
                full_name=full_name,
                phone=phone if phone.strip() else None,
            )

            if result.get("session"):
                # Email confirmation disabled in Supabase — log in directly
                auth_service.save_session_to_state({
                    "user": result["user"],
                    "session": result["session"],
                    "profile": None,
                    "access_token": result["session"].access_token,
                    "refresh_token": result["session"].refresh_token,
                })
                # Load profile
                profile = auth_service.get_profile(
                    str(result["user"].id),
                    result["session"].access_token,
                )
                st.session_state.profile = profile
                st.success("🎉 Account created! Welcome to SportsPlex.")
                st.rerun()
            else:
                # Email confirmation required (default Supabase setting)
                st.success(result["message"])
                st.info(
                    "💡 **Next step:** Check your email inbox (including spam) for "
                    "a verification link. Once verified, return here and sign in."
                )

        except AuthError as e:
            st.error(str(e))
        except Exception:
            st.error("An unexpected error occurred. Please try again.")


# ── Tab: Reset Password ───────────────────────────────────────

def _render_reset(auth_service):
    st.markdown("#### Reset your password")
    st.markdown(
        "Enter your email address below and we'll send you a secure link "
        "to set a new password."
    )

    with st.form("reset_form"):
        email = st.text_input("Email Address", placeholder="you@example.com")
        submitted = st.form_submit_button(
            "Send Reset Link", type="primary", use_container_width=True
        )

    if submitted:
        _do_reset(auth_service, email)


def _do_reset(auth_service, email: str):
    if not email.strip():
        st.error("Please enter your email address.")
        return

    with st.spinner("Sending reset email…"):
        try:
            result = auth_service.reset_password(email)
            st.success(result["message"])
            st.info(
                "💡 Check your spam folder if the email doesn't arrive within a few minutes."
            )
        except AuthError as e:
            st.error(str(e))
        except Exception:
            st.error("An unexpected error occurred. Please try again.")


render()
