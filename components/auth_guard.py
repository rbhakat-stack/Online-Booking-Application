"""
Auth Guard & Navigation Components
=====================================
Reusable functions called at the top of protected pages.

Pattern:
    # In any protected page:
    from components.auth_guard import require_auth, show_auth_status_sidebar

    show_auth_status_sidebar()    # Always call this (adds logout button to sidebar)
    require_auth()                # Stops execution if not logged in
    require_admin()               # Stops execution if not admin

All require_* functions call st.stop() on failure, which halts the rest of the
page's script execution — just like Streamlit's own experimental_singleton guards.
"""

import streamlit as st
from typing import Optional


def show_auth_status_sidebar() -> None:
    """
    Render user info + logout button in the sidebar.
    Call this at the top of every page (auth or not).

    Shows:
    - Logged in: user's name, email, role badge, logout button
    - Not logged in: Login/Sign Up button
    """
    # Import here to avoid circular imports at module level
    from services.auth_service import get_auth_service
    auth_service = get_auth_service()

    with st.sidebar:
        st.markdown("---")

        if auth_service.is_authenticated():
            profile = auth_service.get_current_profile()
            user = auth_service.get_current_user()

            if profile:
                name = profile.get("full_name", "User")
                email = user.email if user else ""
                role = profile.get("role", "player")

                st.markdown(f"**{name}**")
                st.caption(email)

                # Role badge
                role_colors = {
                    "player": "gray",
                    "facility_admin": "blue",
                    "super_admin": "red",
                }
                role_label = role.replace("_", " ").title()
                st.badge(role_label, color=role_colors.get(role, "gray"))

                # Waiver warning
                if not profile.get("waiver_accepted"):
                    st.warning("⚠️ Waiver not accepted", icon="⚠️")

            if st.button("Log Out", use_container_width=True, key="sidebar_logout_btn"):
                access_token = st.session_state.get("access_token")
                auth_service.sign_out(access_token)
                auth_service.clear_session_state()
                st.rerun()
        else:
            if st.button(
                "Log In / Sign Up",
                use_container_width=True,
                type="primary",
                key="sidebar_login_btn",
            ):
                st.switch_page("pages/login.py")


def require_auth(
    message: str = "Please log in to access this page.",
    show_login_button: bool = True,
) -> bool:
    """
    Ensure the user is authenticated. If not, display a message and stop.

    Call this at the top of any protected page, AFTER show_auth_status_sidebar().

    Args:
        message: Message to display if not authenticated.
        show_login_button: Whether to show a "Go to Login" button.

    Returns:
        True if authenticated (script continues).
        Never returns False — calls st.stop() instead.
    """
    from services.auth_service import get_auth_service
    auth_service = get_auth_service()

    # Try to restore/refresh session from stored tokens
    if auth_service.load_session_from_state():
        return True

    # Not authenticated
    st.warning(message)
    if show_login_button:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("Log In / Sign Up", type="primary", use_container_width=True):
                st.switch_page("pages/login.py")
    st.stop()


def require_admin(
    message: str = "You don't have permission to access this page.",
) -> bool:
    """
    Ensure the user is authenticated AND has admin or super_admin role.
    Calls require_auth() first.

    Returns:
        True if user is an admin.
    """
    require_auth()

    from services.auth_service import get_auth_service
    auth_service = get_auth_service()

    if not auth_service.is_admin():
        st.error(f"🔒 {message}")
        st.stop()

    return True


def require_super_admin(
    message: str = "Super admin access is required for this page.",
) -> bool:
    """
    Ensure the user is authenticated AND has the super_admin role.
    """
    require_auth()

    from services.auth_service import get_auth_service
    auth_service = get_auth_service()

    if not auth_service.is_super_admin():
        st.error(f"🔒 {message}")
        st.stop()

    return True


def require_waiver() -> bool:
    """
    Check that the current user has accepted the waiver.
    Redirect to profile page if not.
    Call this on booking pages AFTER require_auth().

    Returns:
        True if waiver is accepted.
    """
    from services.auth_service import get_auth_service
    auth_service = get_auth_service()

    profile = auth_service.get_current_profile()
    if not profile:
        st.error("Could not load your profile. Please try logging out and back in.")
        st.stop()

    if profile.get("waiver_accepted"):
        return True

    st.warning(
        "⚠️ **You must accept our Terms & Liability Waiver before making a booking.**"
    )
    st.markdown(
        "This is a one-time step. Please visit your Profile page to accept the waiver."
    )
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("Go to My Profile", type="primary", use_container_width=True):
            st.switch_page("pages/profile.py")
    st.stop()


def get_current_facility_id() -> Optional[str]:
    """
    Return the facility_id currently selected in session_state.
    Facility selection is set on the availability page and persists
    through the booking flow.
    """
    return st.session_state.get("selected_facility_id")
