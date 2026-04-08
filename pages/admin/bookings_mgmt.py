"""
Admin Booking Management Page
===============================
Phase 6 — Coming soon.
Search, filter, and manage all bookings for the facility.
"""

import streamlit as st
from components.auth_guard import require_admin, show_auth_status_sidebar

show_auth_status_sidebar()
require_admin()

st.markdown("## 📅 Manage Bookings")

st.info(
    "🚧 **Phase 6 — Coming Soon**\n\n"
    "Booking management tools are being built. Check back soon!"
)

st.markdown(
    """
    **What you'll be able to do here:**
    - Search and filter bookings by user, court, date, status
    - View booking details and payment records
    - Manually confirm, cancel, or override bookings
    - Issue refunds (full or partial)
    - Block courts for maintenance or private events
    - Approve or deny full-day event inquiries
    - Export booking data to CSV
    """
)
