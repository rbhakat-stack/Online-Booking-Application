"""
Login / Sign Up / Password Reset Page
========================================
Three-tab layout:
  Tab 1 — Sign In      (email + password)
  Tab 2 — Create Account (registration form with validation)
  Tab 3 — Reset Password (sends Supabase magic link)

After successful sign-in, user is redirected based on role:
  - Admin → admin dashboard
  - Player → availability page
"""

import streamlit as st
from services.auth_service import get_auth_service, AuthError
from components.auth_guard import show_auth_status_sidebar


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()

    # Already authenticated → show quick nav
    if auth_service.is_authenticated():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.html(
                """
                <div style="text-align:center;padding:2rem 0 1.5rem">
                    <div style="font-size:3rem;margin-bottom:0.5rem">✅</div>
                    <h3 style="color:#0f172a;margin:0 0 0.25rem">You're signed in!</h3>
                    <p style="color:#64748b;margin:0">Where would you like to go?</p>
                </div>
                """
            )
            if st.button("📅 Book a Court", type="primary", use_container_width=True):
                st.switch_page("pages/availability.py")
            st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
            if st.button("📋 My Bookings", use_container_width=True):
                st.switch_page("pages/my_bookings.py")
        return

    # ── Auth card ─────────────────────────────────────────────
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.html(
            """
            <div style="text-align:center;padding:1.75rem 0 1.25rem">
                <div style="font-size:2.5rem;margin-bottom:0.5rem">🏓</div>
                <h2 style="color:#0f172a;font-weight:800;margin:0">Welcome to SportsPlex</h2>
                <p style="color:#64748b;margin:0.4rem 0 0">Sign in or create your account below</p>
            </div>
            """
        )

        # One-time messages from redirects
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

        st.html(
            """
            <div style="text-align:center;font-size:0.78rem;color:#94a3b8;margin-top:1rem">
                🔒 Your data is secured with Supabase Auth &amp; Stripe-grade encryption
            </div>
            """
        )


# ── Tab: Sign In ──────────────────────────────────────────────

def _render_sign_in(auth_service):
    st.html("<div style='margin-bottom:0.75rem;font-weight:600;color:#0f172a'>Sign in to your account</div>")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email Address", placeholder="you@example.com",
                              label_visibility="visible")
        password = st.text_input("Password", type="password",
                                 placeholder="Your password")
        submitted = st.form_submit_button(
            "Sign In", type="primary", use_container_width=True
        )

    if submitted:
        _do_sign_in(auth_service, email, password)

    st.html(
        "<p style='text-align:center;font-size:0.82rem;color:#94a3b8;margin-top:0.75rem'>"
        "New here? Switch to the <strong>Create Account</strong> tab.</p>"
    )


def _do_sign_in(auth_service, email: str, password: str):
    if not email.strip() or not password:
        st.error("Please enter both your email and password.")
        return
    with st.spinner("Signing in…"):
        try:
            from utils.constants import SessionKey
            result = auth_service.sign_in(email, password)
            auth_service.save_session_to_state(result)
            st.success("Welcome back! Redirecting…")
            # If a Stripe session is pending (user paid but session was lost),
            # send them back to payment_success.py to complete booking confirmation.
            pending_stripe = st.session_state.get(SessionKey.STRIPE_SESSION_ID, "")
            if pending_stripe and str(pending_stripe).startswith("cs_"):
                st.switch_page("pages/payment_success.py")
            st.rerun()
        except AuthError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")


# ── Tab: Sign Up ──────────────────────────────────────────────

def _render_sign_up(auth_service):
    st.html("<div style='margin-bottom:0.75rem;font-weight:600;color:#0f172a'>Create a new account</div>")

    with st.form("signup_form", clear_on_submit=False):
        full_name = st.text_input("Full Name *", placeholder="Jane Smith")
        email     = st.text_input("Email Address *", placeholder="you@example.com")
        phone     = st.text_input("Phone Number", placeholder="(555) 123-4567",
                                  help="Optional — for booking reminders")

        st.html("<div style='font-size:0.82rem;color:#64748b;margin:0.25rem 0'>Password — min. 8 chars, 1 uppercase, 1 number</div>")
        password = st.text_input("Password *", type="password",
                                 placeholder="Create a strong password",
                                 label_visibility="collapsed")
        confirm  = st.text_input("Confirm Password *", type="password",
                                 placeholder="Repeat your password",
                                 label_visibility="collapsed")
        terms = st.checkbox("I agree to the Terms of Service and Privacy Policy")

        submitted = st.form_submit_button(
            "Create Account", type="primary", use_container_width=True
        )

    if submitted:
        _do_sign_up(auth_service, full_name, email, phone, password, confirm, terms)

    st.html(
        """
        <div style="background:#f8fafc;border-radius:10px;padding:0.75rem 1rem;
                    font-size:0.8rem;color:#64748b;margin-top:0.5rem;border:1px solid #e2e8f0">
            <strong>Password requirements:</strong>&nbsp;
            8+ characters &nbsp;&middot;&nbsp; 1 uppercase &nbsp;&middot;&nbsp; 1 number
        </div>
        """
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
        errors.append("You must accept the Terms of Service to continue.")

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
                phone=phone.strip() if phone.strip() else None,
            )
            if result.get("session"):
                auth_service.save_session_to_state({
                    "user":          result["user"],
                    "session":       result["session"],
                    "profile":       None,
                    "access_token":  result["session"].access_token,
                    "refresh_token": result["session"].refresh_token,
                })
                profile = auth_service.get_profile(
                    str(result["user"].id), result["session"].access_token
                )
                st.session_state.profile = profile
                st.success("🎉 Account created! Welcome to SportsPlex.")
                st.rerun()
            else:
                st.success(result["message"])
                st.info(
                    "**Next step:** Check your email inbox (including spam) for a verification link. "
                    "Once verified, return here and sign in."
                )
        except AuthError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")


# ── Tab: Reset Password ───────────────────────────────────────

def _render_reset(auth_service):
    st.html("<div style='margin-bottom:0.75rem;font-weight:600;color:#0f172a'>Reset your password</div>")
    st.html("<p style='font-size:0.875rem;color:#64748b'>Enter your email and we'll send a secure reset link.</p>")

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
            st.info("Check your spam folder if the email doesn't arrive within a few minutes.")
        except AuthError as e:
            st.error(str(e))
        except Exception:
            st.error("An unexpected error occurred. Please try again.")


render()
