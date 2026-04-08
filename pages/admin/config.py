"""
Facility Configuration Page (Admin)
======================================
Phase 6 — Coming soon.
Admins configure operating hours, courts, pricing rules, closures, and booking rules.
"""

import streamlit as st
from components.auth_guard import require_admin, show_auth_status_sidebar

show_auth_status_sidebar()
require_admin()

st.markdown("## ⚙️ Facility Configuration")

st.info(
    "🚧 **Phase 6 — Coming Soon**\n\n"
    "The facility configuration panel is being built. Check back soon!"
)

st.markdown(
    """
    **Configuration sections planned:**
    - **Facility Setup** — name, timezone, contact info, active status
    - **Operating Hours** — open/close times per day of week
    - **Closures** — one-time and recurring blackout dates
    - **Courts** — add, edit, reorder, set status
    - **Booking Rules** — min/max duration, increment, hold expiry, cancellation windows
    - **Pricing Rules** — base, peak, off-peak, weekend, event rates
    - **Feature Flags** — waitlist, auto-assign court, event approval
    - **Audit Log** — full history of all configuration changes
    """
)
