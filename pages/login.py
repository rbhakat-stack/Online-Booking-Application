"""
Courtify Login / Sign Up / Password Reset Page
==============================================
UI-only redesign for the auth experience.

Important:
- No backend/auth logic changes
- Existing forms, buttons, and flows remain intact
- Only presentation, layout, branding, and hierarchy are updated
"""

import streamlit as st
from components.auth_guard import show_auth_status_sidebar
from services.auth_service import AuthError, get_auth_service


def render():
    auth_service = get_auth_service()
    show_auth_status_sidebar()
    _inject_login_css()

    # Keep the existing post-login shortcuts, only restyled.
    if auth_service.is_authenticated():
        _render_signed_in_state()
        return

    outer_left, center_col, outer_right = st.columns([0.7, 1.2, 0.7], gap="large")
    with center_col:
        _render_brand_panel()
        _render_auth_panel(auth_service)


def _inject_login_css():
    """Scoped CSS for a cleaner, centered Courtify auth layout."""
    st.markdown(
        """
        <style>
        .courtify-brand {
            background:
                radial-gradient(circle at top center, rgba(20, 184, 166, 0.12), transparent 38%),
                linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
            border: 1px solid rgba(30, 58, 138, 0.08);
            border-radius: 28px;
            padding: 1.35rem 1.75rem 1.2rem;
            box-shadow: 0 18px 50px rgba(15, 23, 42, 0.06);
            position: relative;
            overflow: hidden;
            text-align: center;
            margin-bottom: 0.75rem;
        }
        .courtify-brand::after {
            content: "";
            position: absolute;
            inset: auto -1.25rem -1.25rem auto;
            width: 6.75rem;
            height: 6.75rem;
            border-radius: 50%;
            border: 1px solid rgba(20, 184, 166, 0.12);
            background: rgba(20, 184, 166, 0.05);
        }
        .courtify-logo {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.75rem;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.02em;
            margin-bottom: 0.45rem;
        }
        .courtify-logo-mark {
            width: 2.55rem;
            height: 2.55rem;
            border-radius: 0.85rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #1e3a8a 0%, #14b8a6 100%);
            color: white;
            font-size: 1.08rem;
            box-shadow: 0 8px 18px rgba(30, 58, 138, 0.18);
        }
        .courtify-eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.35rem 0.8rem;
            border-radius: 999px;
            background: rgba(20, 184, 166, 0.09);
            color: #0f766e;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 1rem;
        }
        .courtify-brand h1 {
            margin: 0;
            color: #0f172a;
            font-size: clamp(2.1rem, 4vw, 3rem);
            line-height: 1.08;
            letter-spacing: -0.04em;
        }
        .courtify-subheadline {
            color: #475569;
            font-size: 0.92rem;
            line-height: 1.4;
            max-width: none;
            margin: 0;
            letter-spacing: -0.01em;
        }
        .courtify-auth-card {
            background: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 28px;
            padding: 1.85rem;
            box-shadow: 0 24px 64px rgba(15, 23, 42, 0.08);
        }
        .courtify-auth-title {
            color: #0f172a;
            font-size: 2rem;
            font-weight: 800;
            letter-spacing: -0.04em;
            margin: 0;
        }
        .courtify-auth-copy {
            color: #64748b;
            font-size: 0.95rem;
            line-height: 1.6;
            margin: 0.55rem 0 0;
        }
        .courtify-security-note {
            margin-top: 1rem;
            text-align: center;
            color: #64748b;
            font-size: 0.8rem;
        }
        .courtify-divider {
            display: flex;
            align-items: center;
            gap: 0.85rem;
            margin: 1rem 0 0.3rem;
            color: #94a3b8;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .courtify-divider::before,
        .courtify-divider::after {
            content: "";
            height: 1px;
            flex: 1;
            background: rgba(148, 163, 184, 0.25);
        }
        .courtify-helper {
            color: #64748b;
            font-size: 0.82rem;
            text-align: center;
            margin-top: 0.65rem;
        }
        .courtify-password-note {
            background: #f8fafc;
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 14px;
            padding: 0.8rem 0.95rem;
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 0.55rem;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.45rem;
            background: #f8fafc;
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 16px;
            padding: 0.3rem;
        }
        .stTabs [data-baseweb="tab"] {
            height: 2.7rem;
            border-radius: 12px;
            padding: 0 1rem;
            color: #475569;
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background: white;
            color: #1e3a8a;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
        }
        .stTextInput label, .stCheckbox label {
            color: #0f172a !important;
            font-weight: 600 !important;
        }
        .stTextInput input {
            border-radius: 14px !important;
            border: 1px solid rgba(148, 163, 184, 0.28) !important;
            padding-top: 0.8rem !important;
            padding-bottom: 0.8rem !important;
            background: #ffffff !important;
        }
        .stTextInput input:focus {
            border-color: #14b8a6 !important;
            box-shadow: 0 0 0 1px #14b8a6 !important;
        }
        .stButton > button {
            border-radius: 14px !important;
            min-height: 2.9rem !important;
            font-weight: 700 !important;
            transition: transform 120ms ease, box-shadow 120ms ease !important;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
        }
        @media (max-width: 900px) {
            .courtify-brand,
            .courtify-auth-card {
                padding: 1.35rem;
                border-radius: 22px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_signed_in_state():
    col1, col2, col3 = st.columns([1, 1.25, 1], gap="large")
    with col2:
        st.markdown(
            """
            <div class="courtify-auth-card" style="text-align:center;">
                <div class="courtify-logo" style="justify-content:center;">
                    <div class="courtify-logo-mark">C</div>
                    <div>Courtify</div>
                </div>
                <div style="font-size:2.5rem;margin-bottom:0.4rem;">✓</div>
                <h3 style="color:#0f172a;margin:0 0 0.25rem;">You're signed in</h3>
                <p class="courtify-auth-copy" style="margin-top:0;">
                    Choose where you'd like to go next.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Book a Court", type="primary", use_container_width=True):
            st.switch_page("pages/availability.py")
        if st.button("My Bookings", use_container_width=True):
            st.switch_page("pages/my_bookings.py")


def _render_brand_panel():
    st.markdown(
        """
        <div class="courtify-brand">
        <div class="courtify-logo">
            <div class="courtify-logo-mark">C</div>
            <div>Courtify</div>
        </div>
        <p class="courtify-subheadline">
            Reserve Your Court. Play Your Game.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_auth_panel(auth_service):
    st.markdown(
        """
        <div class="courtify-auth-card">
            <div class="courtify-eyebrow">Welcome back</div>
            <h2 class="courtify-auth-title">Access Courtify</h2>
            <p class="courtify-auth-copy">
                Sign in, create your account, or reset your password without leaving the page.
            </p>
        """,
        unsafe_allow_html=True,
    )

    msg = st.session_state.get("auth_success_message")
    if msg:
        st.success(msg)
        st.session_state.auth_success_message = None

    tab_signin, tab_signup, tab_reset = st.tabs(
        ["Sign In", "Create Account", "Reset Password"]
    )

    with tab_signin:
        _render_sign_in(auth_service)
    with tab_signup:
        _render_sign_up(auth_service)
    with tab_reset:
        _render_reset(auth_service)

    st.markdown(
        """
            <div class="courtify-security-note">
                Secure authentication powered by Supabase and encrypted payments through Stripe.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Tab: Sign In

def _render_sign_in(auth_service):
    st.markdown(
        "<div class='courtify-section-title' style='margin-bottom:0.75rem;'>Sign in to your account</div>",
        unsafe_allow_html=True,
    )

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

    st.markdown("<div class='courtify-divider'>OR</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='courtify-helper'>New here? Switch to the <strong>Create Account</strong> tab.</p>",
        unsafe_allow_html=True,
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
    st.markdown(
        "<div class='courtify-section-title' style='margin-bottom:0.75rem;'>Create a new account</div>",
        unsafe_allow_html=True,
    )

    with st.form("signup_form", clear_on_submit=False):
        full_name = st.text_input("Full Name *", placeholder="Jane Smith")
        email     = st.text_input("Email Address *", placeholder="you@example.com")
        phone     = st.text_input("Phone Number", placeholder="(555) 123-4567",
                                  help="Optional — for booking reminders")

        st.markdown(
            "<div class='courtify-helper' style='text-align:left;margin:0.15rem 0 0.45rem;'>Password - min. 8 chars, 1 uppercase, 1 number</div>",
            unsafe_allow_html=True,
        )
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

    st.markdown(
        """
        <div class="courtify-password-note">
            <strong>Password requirements:</strong> 8+ characters, 1 uppercase, 1 number.
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
                st.success("Account created! Welcome to Courtify.")
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
    st.markdown(
        "<div class='courtify-section-title' style='margin-bottom:0.5rem;'>Reset your password</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='courtify-auth-copy' style='margin-bottom:0.9rem;'>Enter your email and we'll send a secure reset link.</p>",
        unsafe_allow_html=True,
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
            st.info("Check your spam folder if the email doesn't arrive within a few minutes.")
        except AuthError as e:
            st.error(str(e))
        except Exception:
            st.error("An unexpected error occurred. Please try again.")


render()
