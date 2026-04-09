"""
SportsPlex — Main Application Entry Point
==========================================
This file is the Streamlit entry point (set in .streamlit/config.toml
or as the default app file on Streamlit Community Cloud).

Responsibilities:
1. Page config (title, icon, layout)
2. Load global CSS
3. Initialise session state defaults
4. Define navigation structure (varies by auth state + role)
5. Run the selected page

Navigation is built with st.navigation (Streamlit ≥ 1.36), which gives us:
- Full control over which pages are shown per user role
- Grouped sidebar navigation with labels
- No need for the legacy pages/ auto-discovery

Tradeoff: Because Streamlit reruns app.py on every interaction, the
navigation rebuild is cheap (no DB calls here). All DB/auth work
happens inside the individual page modules.
"""

import streamlit as st
from utils.constants import SessionKey

# ── Page Config ───────────────────────────────────────────────
# Must be the FIRST Streamlit call in the script
st.set_page_config(
    page_title="Courtify — Court Booking",
    page_icon="🏓",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "**Courtify** — Sports court booking platform. Built with Streamlit & Supabase.",
    },
)


# ── Load Global CSS ──────────────────────────────────────────
def _load_css():
    """Inject custom CSS into every page."""
    try:
        with open("styles/custom.css", "r") as f:
            css = f.read()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass  # CSS is cosmetic — silently skip if missing


_load_css()


# ── Session State Initialisation ─────────────────────────────
def _init_session_state():
    """
    Set default values for all session state keys used across the app.
    Only sets a key if it doesn't already exist (idempotent).

    Keys are centralised in utils/constants.py (SessionKey) to prevent typos.
    """
    defaults = {
        # Auth
        SessionKey.USER: None,
        SessionKey.SESSION: None,
        SessionKey.PROFILE: None,
        SessionKey.ACCESS_TOKEN: None,
        SessionKey.REFRESH_TOKEN: None,
        # Booking flow (set during availability → book flow)
        SessionKey.SELECTED_FACILITY_ID: None,
        SessionKey.SELECTED_DATE: None,
        SessionKey.SELECTED_COURT_ID: None,
        SessionKey.SELECTED_START_TIME: None,
        SessionKey.SELECTED_DURATION: None,
        SessionKey.ACTIVE_HOLD_ID: None,
        SessionKey.STRIPE_SESSION_ID: None,
        # UI transient
        SessionKey.AUTH_SUCCESS_MESSAGE: None,
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


_init_session_state()


# ── Determine Auth State for Navigation ─────────────────────
# We read directly from session_state here (no Supabase calls).
# The actual token validation happens inside each page via load_session_from_state().
# This keeps app.py fast — it just decides which nav items to show.

def _get_role() -> str:
    profile = st.session_state.get(SessionKey.PROFILE)
    if profile and isinstance(profile, dict):
        return profile.get("role", "player")
    return "player"


_is_logged_in: bool = bool(
    st.session_state.get(SessionKey.USER)
    and st.session_state.get(SessionKey.ACCESS_TOKEN)
)
_role: str = _get_role()
_is_admin: bool = _role in ("facility_admin", "super_admin")


# ── Page Definitions ─────────────────────────────────────────
# Using st.Page with explicit titles and icons.
# 'default=True' marks the page that loads when visiting the root URL.

home_page = st.Page(
    "pages/home.py",
    title="Home",
    icon="🏠",
    default=True,
)
login_page = st.Page(
    "pages/login.py",
    title="Login / Sign Up",
    icon="🔑",
)
availability_page = st.Page(
    "pages/availability.py",
    title="Book a Court",
    icon="🎾",
)
my_bookings_page = st.Page(
    "pages/my_bookings.py",
    title="My Bookings",
    icon="📋",
)
book_page = st.Page(
    "pages/book.py",
    title="Complete Booking",
    icon="✅",
)
payment_page = st.Page(
    "pages/payment_success.py",
    title="Payment",
    icon="💳",
    url_path="payment-success",
)
profile_page = st.Page(
    "pages/profile.py",
    title="My Profile",
    icon="👤",
)

# Admin pages
admin_dashboard_page = st.Page(
    "pages/admin/dashboard.py",
    title="Dashboard",
    icon="📊",
)
admin_bookings_page = st.Page(
    "pages/admin/bookings_mgmt.py",
    title="Manage Bookings",
    icon="📅",
)
admin_config_page = st.Page(
    "pages/admin/config.py",
    title="Configuration",
    icon="⚙️",
)
admin_metrics_page = st.Page(
    "pages/admin/metrics.py",
    title="Revenue & Metrics",
    icon="💰",
)


# ── Build Navigation ─────────────────────────────────────────
# Navigation structure changes based on auth state and role.
# payment_success is always included (Stripe redirects there regardless of nav state).

def _build_nav():
    # book_page and payment_page are flow-only pages: they must be registered in
    # st.navigation so st.switch_page can reach them, but we hide them from the
    # sidebar visually via CSS (.sp-hidden-nav class rule in custom.css).
    if not _is_logged_in:
        # Unauthenticated: home + login only
        nav_pages = {
            "": [home_page],
            "Account": [login_page],
            # Flow pages must be registered even when logged out (Stripe redirect)
            "  ": [book_page, payment_page],
        }
    elif _is_admin:
        # Admin: full set including admin section
        nav_pages = {
            "": [home_page],
            "Booking": [availability_page, my_bookings_page, book_page, payment_page],
            "Account": [profile_page],
            "Admin": [
                admin_dashboard_page,
                admin_bookings_page,
                admin_config_page,
                admin_metrics_page,
            ],
        }
    else:
        # Regular player
        nav_pages = {
            "": [home_page],
            "Booking": [availability_page, my_bookings_page, book_page, payment_page],
            "Account": [profile_page],
        }

    return nav_pages


_nav_pages = _build_nav()

# Build sidebar navigation with section headers
pg = st.navigation(_nav_pages)

# ── Sidebar Branding ─────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div style="padding:1rem 0 0.5rem;text-align:center">
            <div style="
                display:inline-flex;align-items:center;justify-content:center;
                width:48px;height:48px;border-radius:14px;
                background:linear-gradient(135deg,#0ea5e9,#8b5cf6);
                font-size:1.5rem;margin-bottom:0.5rem;
                box-shadow:0 4px 14px rgba(14,165,233,0.4);
            ">🏓</div>
            <div style="font-weight:800;font-size:1.15rem;color:#f1f5f9;
                        letter-spacing:0.02em;margin-top:0.25rem">
                Courtify
            </div>
            <div style="font-size:0.72rem;color:rgba(255,255,255,0.4);
                        margin-top:0.1rem;letter-spacing:0.05em;text-transform:uppercase">
                Court Booking
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── Run Selected Page ────────────────────────────────────────
pg.run()
