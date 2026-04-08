"""
Revenue & Utilization Metrics Page (Admin)
==========================================
Phase 6 — Coming soon.
Charts and KPIs for revenue tracking and court utilization.
"""

import streamlit as st
from components.auth_guard import require_admin, show_auth_status_sidebar

show_auth_status_sidebar()
require_admin()

st.markdown("## 💰 Revenue & Metrics")

st.info(
    "🚧 **Phase 6 — Coming Soon**\n\n"
    "Revenue and utilization analytics are being built. Check back soon!"
)

st.markdown(
    """
    **Planned metrics and charts:**
    - Total revenue (daily / weekly / monthly / custom range)
    - Revenue by sport type and court
    - Booking volume trends
    - Occupancy rate heatmap by court and time of day
    - Top customers by booking frequency
    - Cancellation and refund rate
    - Peak vs. off-peak usage breakdown
    """
)
