"""
Home Page — SportsPlex Landing Page
=====================================
Public page (no auth required).
Sections:
  1. Hero — gradient headline, live stat badges, dual CTA
  2. Sports Grid — sport cards with colored accent borders
  3. How It Works — numbered steps with connector treatment
  4. Why Us — trust differentiators
  5. Locations — live data from Supabase
  6. Pricing — tiered price cards
  7. Footer
"""

import streamlit as st
from components.auth_guard import show_auth_status_sidebar
from services.auth_service import get_auth_service
from db.supabase_client import get_client
from utils.config import get_config

config = get_config()
auth_service = get_auth_service()

# Per-sport accent colors (distinct, harmonious with sky/violet palette)
_SPORT_CONFIG = {
    "Pickleball":  {"icon": "🏓", "color": "#0ea5e9", "light": "#e0f2fe",
                    "desc": "America's fastest-growing sport. Indoor & outdoor courts for all levels."},
    "Badminton":   {"icon": "🏸", "color": "#8b5cf6", "light": "#ede9fe",
                    "desc": "Professional courts with feather & synthetic shuttles available."},
    "Tennis":      {"icon": "🎾", "color": "#10b981", "light": "#d1fae5",
                    "desc": "Premium indoor and outdoor courts for casual play and tournaments."},
    "Karate":      {"icon": "🥋", "color": "#f59e0b", "light": "#fef3c7",
                    "desc": "Dedicated studio space for martial arts and self-defence training."},
}


def render():
    auth_service.load_session_from_state()
    show_auth_status_sidebar()

    is_logged_in = auth_service.is_authenticated()

    _render_hero(is_logged_in)
    _render_sports_grid()
    _render_how_it_works()
    _render_why_us()
    _render_facilities()
    _render_pricing()
    _render_footer()


# ── 1. Hero ───────────────────────────────────────────────────

def _render_hero(is_logged_in: bool):
    st.html(
        """
        <div style="
            background:linear-gradient(135deg,#0f172a 0%,#1e293b 60%,#0c2340 100%);
            border-radius:24px;padding:4rem 2rem 3.5rem;text-align:center;
            margin-bottom:0.5rem;position:relative;overflow:hidden;">

            <div style="position:absolute;top:-60px;left:10%;width:300px;height:300px;
                        border-radius:50%;background:rgba(14,165,233,0.08);filter:blur(60px)"></div>
            <div style="position:absolute;bottom:-80px;right:10%;width:350px;height:350px;
                        border-radius:50%;background:rgba(139,92,246,0.08);filter:blur(80px)"></div>

            <div style="display:inline-block;background:rgba(14,165,233,0.15);
                        border:1px solid rgba(14,165,233,0.3);border-radius:999px;
                        padding:0.3rem 1rem;font-size:0.8rem;font-weight:600;
                        color:#38bdf8;letter-spacing:0.06em;margin-bottom:1.5rem">
                🏓 SPORTS COURT BOOKING PLATFORM
            </div>

            <h1 style="font-size:3rem;font-weight:900;line-height:1.1;margin:0 0 1rem;
                       background:linear-gradient(135deg,#f1f5f9 30%,#38bdf8 70%,#a78bfa 100%);
                       -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                       background-clip:text;">
                Reserve Your Court.<br>Play Your Game.
            </h1>

            <p style="font-size:1.15rem;color:#94a3b8;max-width:540px;
                      margin:0 auto 2.5rem;line-height:1.6">
                Real-time availability, instant confirmation, and secure payments —
                all in one place. No phone calls. No waiting.
            </p>

            <div style="display:flex;justify-content:center;gap:1rem;flex-wrap:wrap;
                        margin-bottom:2.5rem">
                <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
                            border-radius:999px;padding:0.4rem 1.1rem;font-size:0.82rem;color:#e2e8f0">
                    ⚡ Instant Confirmation
                </div>
                <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
                            border-radius:999px;padding:0.4rem 1.1rem;font-size:0.82rem;color:#e2e8f0">
                    🔒 Secure Stripe Payments
                </div>
                <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
                            border-radius:999px;padding:0.4rem 1.1rem;font-size:0.82rem;color:#e2e8f0">
                    ↩️ Free Cancellation (24h)
                </div>
            </div>
        </div>
        """
    )

    # CTA buttons — outside the HTML so Streamlit renders them
    col1, col2, col3, col4, col5 = st.columns([2, 1.5, 0.5, 1.5, 2])
    with col2:
        if is_logged_in:
            if st.button("📅 Book a Court", type="primary", use_container_width=True):
                st.switch_page("pages/availability.py")
        else:
            if st.button("🚀 Get Started Free", type="primary", use_container_width=True):
                st.switch_page("pages/login.py")
    with col4:
        if is_logged_in:
            if st.button("📋 My Bookings", use_container_width=True):
                st.switch_page("pages/my_bookings.py")
        else:
            if st.button("🔑 Sign In", use_container_width=True):
                st.switch_page("pages/login.py")

    st.markdown("<br>", unsafe_allow_html=True)


# ── 2. Sports Grid ────────────────────────────────────────────

def _render_sports_grid():
    st.markdown(
        "<div class='admin-section-header' style='font-size:1.1rem'>🏅 Sports We Offer</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(len(_SPORT_CONFIG))
    for col, (sport, cfg) in zip(cols, _SPORT_CONFIG.items()):
        with col:
            st.markdown(
                f"""
                <div style="
                    background:#ffffff;
                    border-radius:16px;
                    padding:1.75rem 1.25rem;
                    text-align:center;
                    border:1px solid #e2e8f0;
                    border-top:4px solid {cfg['color']};
                    box-shadow:0 2px 8px rgba(0,0,0,0.04);
                    transition:transform 0.2s,box-shadow 0.2s;
                    height:100%;
                ">
                    <div style="
                        display:inline-flex;align-items:center;justify-content:center;
                        width:56px;height:56px;border-radius:14px;
                        background:{cfg['light']};font-size:1.75rem;
                        margin-bottom:1rem;
                    ">{cfg['icon']}</div>
                    <h4 style="margin:0 0 0.4rem;color:#0f172a;font-weight:700">{sport}</h4>
                    <p style="font-size:0.82rem;color:#64748b;margin:0;line-height:1.5">
                        {cfg['desc']}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── 3. How It Works ───────────────────────────────────────────

def _render_how_it_works():
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        "<div class='admin-section-header' style='font-size:1.1rem'>📋 How It Works</div>",
        unsafe_allow_html=True,
    )

    steps = [
        ("#0ea5e9", "01", "Create Account",
         "Sign up with your email in under a minute. No credit card required upfront."),
        ("#8b5cf6", "02", "Browse Availability",
         "See real-time court availability. Filter by sport, date, and duration."),
        ("#10b981", "03", "Pay Securely",
         "Stripe-powered checkout. Your card is never stored on our servers."),
        ("#f59e0b", "04", "Show Up & Play",
         "Your booking is confirmed instantly. Just show up — your court is waiting."),
    ]

    cols = st.columns(len(steps))
    for col, (color, num, title, desc) in zip(cols, steps):
        with col:
            st.markdown(
                f"""
                <div style="text-align:center;padding:1.25rem 0.75rem;position:relative">
                    <div style="
                        display:inline-flex;align-items:center;justify-content:center;
                        width:52px;height:52px;border-radius:50%;
                        background:{color};color:#fff;
                        font-size:1.1rem;font-weight:900;
                        margin-bottom:1rem;
                        box-shadow:0 4px 14px {color}55;
                    ">{num}</div>
                    <h4 style="color:#0f172a;font-weight:700;margin:0 0 0.4rem">{title}</h4>
                    <p style="color:#64748b;font-size:0.83rem;line-height:1.55;margin:0">{desc}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── 4. Why Us ─────────────────────────────────────────────────

def _render_why_us():
    st.markdown("<br>", unsafe_allow_html=True)
    st.html(
        """
        <div style="background:linear-gradient(135deg,#f0f9ff 0%,#faf5ff 100%);
                    border-radius:20px;padding:2.5rem 2rem;border:1px solid #e2e8f0;
                    margin-bottom:0.5rem;">
            <div style="text-align:center;margin-bottom:2rem">
                <div style="font-size:0.8rem;font-weight:700;letter-spacing:0.1em;
                            color:#0ea5e9;text-transform:uppercase;margin-bottom:0.5rem">
                    Why SportsPlex?
                </div>
                <h2 style="font-size:1.6rem;font-weight:800;color:#0f172a;margin:0">
                    Built for players, run by courts
                </h2>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem">
                <div style="text-align:center;padding:1rem">
                    <div style="font-size:2rem;margin-bottom:0.5rem">⚡</div>
                    <div style="font-weight:700;color:#0f172a;margin-bottom:0.3rem">Instant Confirmation</div>
                    <div style="font-size:0.83rem;color:#64748b">No back-and-forth emails. Book a slot and get confirmed in seconds.</div>
                </div>
                <div style="text-align:center;padding:1rem">
                    <div style="font-size:2rem;margin-bottom:0.5rem">🔒</div>
                    <div style="font-weight:700;color:#0f172a;margin-bottom:0.3rem">Secure Payments</div>
                    <div style="font-size:0.83rem;color:#64748b">Stripe-powered checkout with bank-level encryption. No card stored with us.</div>
                </div>
                <div style="text-align:center;padding:1rem">
                    <div style="font-size:2rem;margin-bottom:0.5rem">↩️</div>
                    <div style="font-weight:700;color:#0f172a;margin-bottom:0.3rem">Flexible Cancellation</div>
                    <div style="font-size:0.83rem;color:#64748b">Cancel up to 24 hours before for a full refund. No questions asked.</div>
                </div>
            </div>
        </div>
        """
    )


# ── 5. Locations ──────────────────────────────────────────────

def _render_facilities():
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        "<div class='admin-section-header' style='font-size:1.1rem'>📍 Our Locations</div>",
        unsafe_allow_html=True,
    )

    try:
        client = get_client()
        resp = client.table("facilities").select(
            "name, address, city, state, phone, email"
        ).eq("is_active", True).order("name").execute()
        facilities = resp.data or []
    except Exception:
        facilities = []

    if not facilities:
        st.info("Facility information coming soon. Check back shortly!")
        return

    cols = st.columns(min(len(facilities), 3))
    for col, fac in zip(cols, facilities[:3]):
        addr = ", ".join(filter(None, [fac.get("city"), fac.get("state")]))
        with col:
            st.markdown(
                f"""
                <div style="
                    background:#ffffff;
                    border-radius:14px;
                    padding:1.5rem;
                    border:1px solid #e2e8f0;
                    border-left:4px solid #0ea5e9;
                    box-shadow:0 2px 8px rgba(0,0,0,0.04);
                ">
                    <div style="font-size:1.3rem;margin-bottom:0.5rem">🏟️</div>
                    <div style="font-weight:700;color:#0f172a;font-size:1rem;margin-bottom:0.5rem">
                        {fac['name']}
                    </div>
                    {"<div style='font-size:0.82rem;color:#64748b;margin-bottom:0.3rem'>📍 " + addr + "</div>" if addr else ""}
                    {"<div style='font-size:0.82rem;color:#64748b'>📞 " + fac.get('phone','') + "</div>" if fac.get('phone') else ""}
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── 6. Pricing ────────────────────────────────────────────────

def _render_pricing():
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        "<div class='admin-section-header' style='font-size:1.1rem'>💰 Pricing at a Glance</div>",
        unsafe_allow_html=True,
    )

    tiers = [
        ("#10b981", "#d1fae5", "🌤️", "Off-Peak",
         "Weekdays before 5 PM", "From $20", "/hr",
         "Best value for flexible players"),
        ("#0ea5e9", "#e0f2fe", "🌆", "Peak Hours",
         "Weekdays 5–10 PM", "From $35", "/hr",
         "Most popular — book early"),
        ("#8b5cf6", "#ede9fe", "☀️", "Weekends",
         "All day Sat & Sun", "From $40", "/hr",
         "Weekend warriors welcome"),
    ]

    cols = st.columns(3)
    for col, (color, light, icon, label, desc, price, unit, note) in zip(cols, tiers):
        with col:
            st.markdown(
                f"""
                <div style="
                    background:#fff;
                    border-radius:16px;
                    padding:1.75rem 1.5rem;
                    border:1px solid #e2e8f0;
                    border-top:4px solid {color};
                    text-align:center;
                    box-shadow:0 2px 8px rgba(0,0,0,0.04);
                ">
                    <div style="
                        display:inline-flex;align-items:center;justify-content:center;
                        width:48px;height:48px;border-radius:12px;
                        background:{light};font-size:1.4rem;margin-bottom:1rem;
                    ">{icon}</div>
                    <div style="font-weight:700;color:#0f172a;font-size:1rem">{label}</div>
                    <div style="font-size:0.8rem;color:#64748b;margin:0.25rem 0 1rem">{desc}</div>
                    <div style="font-size:2rem;font-weight:900;color:{color};line-height:1">
                        {price}<span style="font-size:1rem;font-weight:500;color:#64748b">{unit}</span>
                    </div>
                    <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem;
                                font-style:italic">{note}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.caption(
        "Prices vary by sport type and membership level. "
        "Full-day event pricing available on request. "
        "Premium & Corporate members receive 10–25% off."
    )


# ── 7. Footer ─────────────────────────────────────────────────

def _render_footer():
    st.markdown("<br>", unsafe_allow_html=True)
    current_year = 2025
    st.markdown(
        f"""
        <div style="
            text-align:center;
            padding:2rem 0 1rem;
            border-top:1px solid #e2e8f0;
            margin-top:1rem;
        ">
            <div style="font-size:1.3rem;margin-bottom:0.3rem">🏓</div>
            <div style="font-weight:700;color:#0f172a;margin-bottom:0.2rem">
                {config.app_name}
            </div>
            <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:0.75rem">
                Built with Streamlit &amp; Supabase · Payments by Stripe
            </div>
            <div style="font-size:0.78rem;color:#94a3b8">
                © {current_year} {config.app_name} &nbsp;·&nbsp;
                <a href="#" style="color:#0ea5e9;text-decoration:none">Privacy Policy</a>
                &nbsp;·&nbsp;
                <a href="#" style="color:#0ea5e9;text-decoration:none">Terms of Service</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


render()
