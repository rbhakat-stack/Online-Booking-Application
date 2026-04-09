"""
Revenue & Utilization Metrics (Admin)
=======================================
Analytics dashboard with:
  • Period selector (7d / 30d / 90d / custom)
  • Summary KPI cards (dark gradient style)
  • Daily revenue trend — line chart
  • Bookings by sport type — horizontal bar chart
  • Day-of-week booking distribution — bar chart
  • Hourly occupancy heatmap — plotly heatmap

All data fetched from Supabase via admin_service.
Charts rendered with Plotly using a consistent electric-sky / violet palette.
"""

import streamlit as st
from datetime import date, timedelta

import plotly.graph_objects as go
import plotly.express as px

from components.auth_guard import show_auth_status_sidebar, require_admin
from services.auth_service import get_auth_service
from services.admin_service import (
    get_summary_metrics,
    get_revenue_by_day,
    get_booking_stats_by_sport,
    get_hourly_occupancy,
)
from db.supabase_client import get_admin_client
from db.queries import get_admin_facilities, get_active_facilities
from utils.constants import SPORT_ICONS

# Chart palette — sky blue to violet gradient family
_PALETTE = ["#0ea5e9", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899"]
_CHART_BG = "rgba(0,0,0,0)"
_CHART_FONT = dict(family="Inter, Segoe UI, system-ui", color="#0f172a", size=12)
_DAYS_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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
        st.error("No facilities assigned.")
        return

    facility_map = {f["id"]: f for f in facilities}
    saved_fac = st.session_state.get("_admin_facility_id") or list(facility_map.keys())[0]
    if saved_fac not in facility_map:
        saved_fac = list(facility_map.keys())[0]

    # ── Page header ───────────────────────────────────────────
    col_hdr, col_fac = st.columns([3, 2])
    with col_hdr:
        st.markdown(
            """
            <div class="admin-page-header">
                <div>
                    <div class="header-title">💰 Revenue & Metrics</div>
                    <div class="header-subtitle">Booking analytics and performance insights</div>
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
            key="metrics_fac",
            label_visibility="collapsed",
        )
        st.session_state["_admin_facility_id"] = fac_id

    # ── Period selector ───────────────────────────────────────
    st.markdown(
        "<div class='admin-section-header'>📆 Time Period</div>",
        unsafe_allow_html=True,
    )
    period_col, custom_col1, custom_col2 = st.columns([2, 2, 2])
    with period_col:
        period = st.selectbox(
            "Period",
            ["Last 7 days", "Last 30 days", "Last 90 days", "Custom"],
            key="metrics_period",
            label_visibility="collapsed",
        )

    today = date.today()
    if period == "Last 7 days":
        start_date, end_date = today - timedelta(days=6), today
    elif period == "Last 30 days":
        start_date, end_date = today - timedelta(days=29), today
    elif period == "Last 90 days":
        start_date, end_date = today - timedelta(days=89), today
    else:
        with custom_col1:
            start_date = st.date_input("From", value=today - timedelta(days=29),
                                       key="metrics_from")
        with custom_col2:
            end_date = st.date_input("To", value=today, key="metrics_to")

    start_str = start_date.isoformat()
    end_str   = end_date.isoformat()

    # ── Load all metrics ──────────────────────────────────────
    with st.spinner("Loading analytics…"):
        summary     = get_summary_metrics(fac_id, start_str, end_str)
        daily_rev   = get_revenue_by_day(fac_id, start_str, end_str)
        by_sport    = get_booking_stats_by_sport(fac_id, start_str, end_str)
        hourly_occ  = get_hourly_occupancy(fac_id, start_str, end_str)

    # ── Summary KPI cards ─────────────────────────────────────
    st.markdown(
        "<div class='admin-section-header'>📊 Summary</div>",
        unsafe_allow_html=True,
    )

    kpis = [
        ("💰", f"${summary['total_revenue']:,.0f}", "Total Revenue", "confirmed bookings", "up"),
        ("🗓️", f"{summary['booking_count']}", "Bookings", f"avg ${summary['avg_booking_value']:.0f} each", "neu"),
        ("⏱", f"{summary['total_hours_booked']:.0f}h", "Court Hours Sold", "in selected period", "neu"),
        ("❌", f"{summary['cancellation_rate']}%", "Cancellation Rate",
         f"{summary['cancellation_count']} cancelled",
         "down" if summary['cancellation_rate'] > 15 else "neu"),
    ]

    kcols = st.columns(4)
    for col, (icon, value, label, delta, dtype) in zip(kcols, kpis):
        with col:
            st.markdown(
                f"""
                <div class="admin-metric-card">
                    <div class="metric-icon">{icon}</div>
                    <div class="metric-value">{value}</div>
                    <div class="metric-label">{label}</div>
                    <div class="metric-delta {dtype}">{delta}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Revenue Trend ─────────────────────────────────────────
    st.markdown(
        "<div class='admin-section-header'>📈 Daily Revenue</div>",
        unsafe_allow_html=True,
    )

    if daily_rev:
        dates    = [d["date"] for d in daily_rev]
        revenues = [d["revenue"] for d in daily_rev]
        bookings = [d["bookings"] for d in daily_rev]

        fig_rev = go.Figure()
        fig_rev.add_trace(go.Scatter(
            x=dates, y=revenues,
            mode="lines+markers",
            name="Revenue",
            line=dict(color="#0ea5e9", width=2.5),
            marker=dict(size=6, color="#0ea5e9"),
            fill="tozeroy",
            fillcolor="rgba(14,165,233,0.08)",
            hovertemplate="<b>%{x}</b><br>Revenue: $%{y:,.2f}<extra></extra>",
        ))
        fig_rev.add_trace(go.Bar(
            x=dates, y=bookings,
            name="Bookings",
            yaxis="y2",
            marker_color="rgba(139,92,246,0.25)",
            hovertemplate="<b>%{x}</b><br>Bookings: %{y}<extra></extra>",
        ))
        fig_rev.update_layout(
            paper_bgcolor=_CHART_BG,
            plot_bgcolor=_CHART_BG,
            font=_CHART_FONT,
            height=320,
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(showgrid=False, tickangle=-30),
            yaxis=dict(
                showgrid=True, gridcolor="#f1f5f9",
                tickformat="$,.0f", title="Revenue",
            ),
            yaxis2=dict(
                overlaying="y", side="right",
                showgrid=False, title="Bookings",
            ),
            hovermode="x unified",
        )
        st.plotly_chart(fig_rev, use_container_width=True)
    else:
        st.info("No revenue data for this period.")

    # ── Sport Breakdown + Day of Week ─────────────────────────
    scol, dcol = st.columns(2)

    with scol:
        st.markdown(
            "<div class='admin-section-header'>🏅 Bookings by Sport</div>",
            unsafe_allow_html=True,
        )
        if by_sport:
            sport_labels = [
                f"{SPORT_ICONS.get(s['sport_type'], '🏟️')} {s['sport_type'].title()}"
                for s in by_sport
            ]
            sport_counts = [s["bookings"] for s in by_sport]
            sport_rev    = [s["revenue"] for s in by_sport]

            fig_sport = go.Figure()
            fig_sport.add_trace(go.Bar(
                y=sport_labels, x=sport_counts,
                orientation="h",
                marker_color=_PALETTE[:len(by_sport)],
                text=[f"${r:.0f}" for r in sport_rev],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>Bookings: %{x}<br>Revenue: $%{text}<extra></extra>",
            ))
            fig_sport.update_layout(
                paper_bgcolor=_CHART_BG,
                plot_bgcolor=_CHART_BG,
                font=_CHART_FONT,
                height=280,
                margin=dict(l=0, r=40, t=10, b=0),
                xaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
                yaxis=dict(showgrid=False),
                showlegend=False,
            )
            st.plotly_chart(fig_sport, use_container_width=True)
        else:
            st.info("No data.")

    with dcol:
        st.markdown(
            "<div class='admin-section-header'>📅 Bookings by Day of Week</div>",
            unsafe_allow_html=True,
        )
        if daily_rev:
            # Aggregate by day of week from daily_rev
            from datetime import datetime
            dow_counts = [0] * 7
            dow_revenue = [0.0] * 7
            for d in daily_rev:
                try:
                    dow = datetime.strptime(d["date"], "%Y-%m-%d").weekday()
                    dow_counts[dow] += d["bookings"]
                    dow_revenue[dow] += d["revenue"]
                except ValueError:
                    pass

            fig_dow = go.Figure()
            fig_dow.add_trace(go.Bar(
                x=_DAYS_LABELS, y=dow_counts,
                marker_color=[
                    "#0ea5e9" if d < 5 else "#8b5cf6"
                    for d in range(7)
                ],
                hovertemplate="<b>%{x}</b><br>Bookings: %{y}<extra></extra>",
            ))
            fig_dow.update_layout(
                paper_bgcolor=_CHART_BG,
                plot_bgcolor=_CHART_BG,
                font=_CHART_FONT,
                height=280,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
                showlegend=False,
            )
            st.plotly_chart(fig_dow, use_container_width=True)
        else:
            st.info("No data.")

    # ── Hourly Occupancy Heatmap ──────────────────────────────
    st.markdown(
        "<div class='admin-section-header'>🔥 Peak Hours Heatmap</div>",
        unsafe_allow_html=True,
    )
    st.caption("Darker = more bookings. Weekday vs. weekend patterns visible across rows.")

    if hourly_occ:
        # Build 7×17 matrix (days × hours 6–22)
        hours_range = list(range(6, 23))
        z_matrix = []
        for day in range(7):
            row = []
            for hour in hours_range:
                entry = next(
                    (e["count"] for e in hourly_occ if e["day"] == day and e["hour"] == hour), 0
                )
                row.append(entry)
            z_matrix.append(row)

        hour_labels = [
            f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"
            for h in hours_range
        ]

        fig_heat = go.Figure(data=go.Heatmap(
            z=z_matrix,
            x=hour_labels,
            y=_DAYS_LABELS,
            colorscale=[
                [0.0,  "#f8fafc"],
                [0.2,  "#bae6fd"],
                [0.5,  "#0ea5e9"],
                [0.8,  "#8b5cf6"],
                [1.0,  "#1e1b4b"],
            ],
            showscale=True,
            hovertemplate="<b>%{y} %{x}</b><br>Bookings: %{z}<extra></extra>",
            xgap=2,
            ygap=2,
        ))
        fig_heat.update_layout(
            paper_bgcolor=_CHART_BG,
            plot_bgcolor=_CHART_BG,
            font=_CHART_FONT,
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(side="top"),
        )
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("No occupancy data for this period.")


render()
