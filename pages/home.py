"""
Home Page — SportsPlex Landing Page
=====================================
Public page (no auth required).
Shows facility overview, sports offered, how-it-works, and CTAs.
Pulls live facility data from Supabase if available.
"""

import streamlit as st
from components.auth_guard import show_auth_status_sidebar
from services.auth_service import get_auth_service
from db.supabase_client import get_client
from utils.config import get_config

config = get_config()
auth_service = get_auth_service()


def render():
    # Attempt to restore session (non-blocking — home page works without auth)
    auth_service.load_session_from_state()
    show_auth_status_sidebar()

    is_logged_in = auth_service.is_authenticated()
    profile = auth_service.get_current_profile()

    _render_hero(is_logged_in)
    _render_sports_grid()
    _render_how_it_works()
    _render_facilities()
    _render_pricing_overview()
    _render_footer()


# ── Sections ─────────────────────────────────────────────────

def _render_hero(is_logged_in: bool):
    st.markdown(
        f"""
        <div class="hero-section">
            <h1>🏓 {config.app_name}</h1>
            <p class="subtitle">Reserve your court. Play your game. No hassle.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if is_logged_in:
            if st.button("📅 Book a Court", type="primary", use_container_width=True):
                st.switch_page("pages/availability.py")
        else:
            if st.button("🚀 Get Started Free", type="primary", use_container_width=True):
                st.switch_page("pages/login.py")


def _render_sports_grid():
    st.markdown("---")
    st.markdown("### 🏅 Sports We Offer")

    sports = [
        ("🏓", "Pickleball", "America's fastest-growing sport. Indoor courts for all skill levels."),
        ("🏸", "Badminton",  "Professional courts with feather & synthetic shuttles available."),
        ("🎾", "Tennis",     "Indoor and outdoor courts for casual play and competition."),
        ("🥋", "Karate",     "Dedicated studio space for martial arts and self-defence training."),
    ]

    cols = st.columns(len(sports))
    for col, (icon, name, desc) in zip(cols, sports):
        with col:
            st.markdown(
                f"""
                <div class="sport-card">
                    <div style="font-size:2.5rem;margin-bottom:0.5rem">{icon}</div>
                    <h4 style="margin:0;color:#1a1a2e">{name}</h4>
                    <p style="font-size:0.82rem;color:#6b7280;margin-top:0.4rem">{desc}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_how_it_works():
    st.markdown("---")
    st.markdown("### 📋 How It Works")

    steps = [
        ("1️⃣", "Create Account",   "Sign up in seconds with your email address."),
        ("2️⃣", "Find a Slot",       "Browse real-time availability and pick your time."),
        ("3️⃣", "Pay Securely",      "Fast, secure checkout powered by Stripe."),
        ("4️⃣", "Show Up & Play",    "Just show up — your court is ready and waiting."),
    ]

    cols = st.columns(len(steps))
    for col, (num, title, desc) in zip(cols, steps):
        with col:
            st.markdown(
                f"""
                <div class="step-card">
                    <div class="step-icon">{num}</div>
                    <h4>{title}</h4>
                    <p>{desc}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_facilities():
    st.markdown("---")
    st.markdown("### 📍 Our Locations")

    try:
        client = get_client()        # No auth needed — RLS allows public read on active facilities
        resp = client.table("facilities").select(
            "name, address, city, state, phone"
        ).eq("is_active", True).order("name").execute()
        facilities = resp.data or []
    except Exception:
        facilities = []

    if not facilities:
        st.info("Facility information coming soon. Check back shortly!")
        return

    for fac in facilities:
        addr = ", ".join(filter(None, [fac.get("address"), fac.get("city"), fac.get("state")]))
        st.markdown(
            f"""
            <div style="
                background:#f0f7ff;
                border-left:4px solid #4361ee;
                border-radius:10px;
                padding:1rem 1.5rem;
                margin-bottom:0.75rem;
            ">
                <strong style="color:#1a1a2e;font-size:1rem">{fac['name']}</strong><br>
                <span style="color:#6b7280;font-size:0.875rem">📍 {addr}</span>
                {"<br><span style='color:#6b7280;font-size:0.875rem'>📞 " + fac['phone'] + "</span>" if fac.get('phone') else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_pricing_overview():
    st.markdown("---")
    st.markdown("### 💰 Pricing at a Glance")

    col1, col2, col3 = st.columns(3)
    pricing_items = [
        ("🌤️", "Off-Peak",   "Weekdays before 5 PM",             "From $20/hr"),
        ("🌆", "Peak Hours",  "Weekdays 5–10 PM",                 "From $35/hr"),
        ("☀️", "Weekends",   "All day Saturday & Sunday",         "From $40/hr"),
    ]
    for col, (icon, label, desc, price) in zip([col1, col2, col3], pricing_items):
        with col:
            st.markdown(
                f"""
                <div class="metric-card">
                    <div style="font-size:2rem">{icon}</div>
                    <div style="font-weight:700;color:#1a1a2e;margin-top:0.5rem">{label}</div>
                    <div style="font-size:0.8rem;color:#6b7280">{desc}</div>
                    <div style="font-size:1.3rem;font-weight:800;color:#4361ee;margin-top:0.5rem">{price}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.caption(
        "Full-day event pricing is available on request. "
        "Prices vary by sport type. Membership discounts available."
    )


def _render_footer():
    st.markdown(
        f"""
        <div class="app-footer">
            © 2025 {config.app_name} · Built with Streamlit & Supabase ·
            <a href="#" style="color:#4361ee;text-decoration:none">Privacy Policy</a> ·
            <a href="#" style="color:#4361ee;text-decoration:none">Terms of Service</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


render()
