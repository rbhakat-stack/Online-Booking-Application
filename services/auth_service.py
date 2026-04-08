"""
Authentication & Profile Service
==================================
Handles all authentication and user profile management.
Wraps Supabase Auth (gotrue) and the user_profiles table.

Auth flow overview:
1. sign_up   → Create Supabase auth user → send verification email
               → on first login, _ensure_profile_exists() creates the DB profile
2. sign_in   → Authenticate → load profile → return tokens for session_state
3. sign_out  → Revoke Supabase session → clear session_state
4. reset_pw  → Trigger Supabase magic-link password reset

Profile creation:
- Uses the ADMIN client (service role) for the initial INSERT because RLS
  requires the user's JWT to be active, but that's a chicken-and-egg problem
  on first login after email verification.
- Subsequent reads/writes use the USER client (anon key + user JWT) so RLS
  enforces that users can only touch their own profile.

Role enforcement:
- Roles are stored in user_profiles.role (NOT in Supabase JWT claims by default).
- We read the role from the profile on every sign-in and store it in session_state.
- Page-level guards (components/auth_guard.py) check session_state.profile.role.
- RLS helper functions (is_facility_admin, is_super_admin) in Postgres also read
  from user_profiles, so DB-level enforcement is independent of session_state.
"""

import logging
from typing import Optional

import streamlit as st
from gotrue.errors import AuthApiError

from db.supabase_client import get_client, get_admin_client
from db.queries import get_user_profile, upsert_user_profile
from utils.config import get_config
from utils.time_utils import now_utc
from utils.validators import validate_email, validate_password, validate_name, validate_phone

logger = logging.getLogger(__name__)


# ── Custom Exception ─────────────────────────────────────────

class AuthError(Exception):
    """
    Raised by AuthService when an operation fails.
    The message is safe to display directly to the user.
    """


# ── Service ──────────────────────────────────────────────────

class AuthService:
    """
    Stateless service — all persistent state lives in Supabase and
    Streamlit session_state. Each method is self-contained.
    """

    def __init__(self):
        self.config = get_config()

    # ── Sign Up ──────────────────────────────────────────────

    def sign_up(
        self,
        email: str,
        password: str,
        full_name: str,
        phone: Optional[str] = None,
    ) -> dict:
        """
        Register a new user.

        Steps:
        1. Validate inputs server-side (never trust only client-side validation)
        2. Call supabase.auth.sign_up() → triggers verification email
        3. If email confirmation is disabled in Supabase, create profile immediately
        4. Return result dict

        Returns:
            {
                "success": True,
                "message": str,
                "user": User | None,
                "session": Session | None,   # None if email confirm required
            }

        Raises:
            AuthError: with a user-safe message
        """
        self._validate_signup_inputs(email, password, full_name, phone)

        client = get_client()
        try:
            response = client.auth.sign_up({
                "email": email.strip().lower(),
                "password": password,
                "options": {
                    # Store profile fields in user metadata.
                    # _ensure_profile_exists() reads these on first login.
                    "data": {
                        "full_name": full_name.strip(),
                        "phone": phone.strip() if phone else "",
                        "role": "player",
                    },
                    # After email verification, Supabase redirects here.
                    "email_redirect_to": f"{self.config.app_url}/",
                },
            })

            if not response.user:
                raise AuthError("Sign up failed. Please try again.")

            # If email confirmation is DISABLED in Supabase (useful for dev),
            # a session is returned immediately — create profile now.
            if response.session:
                self._ensure_profile_exists(
                    response.user,
                    response.session.access_token,
                )

            return {
                "success": True,
                "message": (
                    "Account created! Please check your email to verify your address."
                    if not response.session
                    else "Account created! Welcome to SportsPlex."
                ),
                "user": response.user,
                "session": response.session,
            }

        except AuthApiError as e:
            raise AuthError(self._parse_auth_error(e))

    # ── Sign In ──────────────────────────────────────────────

    def sign_in(self, email: str, password: str) -> dict:
        """
        Authenticate with email + password.

        Returns:
            {
                "user": User,
                "session": Session,
                "profile": dict | None,
                "access_token": str,
                "refresh_token": str,
            }

        Raises:
            AuthError: with a user-safe message
        """
        if not email or not email.strip():
            raise AuthError("Email address is required.")
        if not password:
            raise AuthError("Password is required.")

        client = get_client()
        try:
            response = client.auth.sign_in_with_password({
                "email": email.strip().lower(),
                "password": password,
            })

            if not response.session:
                raise AuthError("Sign in failed. Please check your credentials.")

            # Ensure a profile row exists for this user (handles first-login-after-verify)
            profile = self._ensure_profile_exists(
                response.user,
                response.session.access_token,
            )

            return {
                "user": response.user,
                "session": response.session,
                "profile": profile,
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }

        except AuthApiError as e:
            raise AuthError(self._parse_auth_error(e))

    # ── Sign Out ─────────────────────────────────────────────

    def sign_out(self, access_token: Optional[str] = None) -> None:
        """
        Revoke the current Supabase session.
        Always succeeds from the caller's perspective — local state is cleared
        regardless of whether the server call succeeds.
        """
        try:
            client = get_client(access_token)
            client.auth.sign_out()
        except Exception as e:
            # Best-effort: always clear local state even if server revocation fails
            logger.warning(f"Sign-out server call failed (proceeding): {e}")

    # ── Password Reset ───────────────────────────────────────

    def reset_password(self, email: str) -> dict:
        """
        Send a password reset email via Supabase.

        Raises:
            AuthError: with a user-safe message
        """
        valid, error = validate_email(email)
        if not valid:
            raise AuthError(error)

        client = get_client()
        try:
            client.auth.reset_password_for_email(
                email.strip().lower(),
                {"redirect_to": f"{self.config.app_url}/"},
            )
            return {
                "success": True,
                "message": "Password reset email sent. Please check your inbox (and spam folder).",
            }
        except AuthApiError as e:
            raise AuthError(self._parse_auth_error(e))

    # ── Session Management ───────────────────────────────────

    def refresh_session(self, refresh_token: str) -> Optional[dict]:
        """
        Try to refresh an expired JWT using the refresh token.

        Returns:
            { "session": Session, "access_token": str, "refresh_token": str }
            or None if refresh fails (user must re-login).
        """
        try:
            client = get_client()
            response = client.auth.refresh_session(refresh_token)
            if response.session:
                return {
                    "session": response.session,
                    "access_token": response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                }
        except Exception as e:
            logger.debug(f"Session refresh failed: {e}")
        return None

    def validate_session(self, access_token: str) -> Optional[object]:
        """
        Validate an access token with Supabase and return the User object.
        Returns None if the token is invalid or expired.
        """
        try:
            client = get_client()
            response = client.auth.get_user(access_token)
            return response.user if response.user else None
        except Exception:
            return None

    def load_session_from_state(self) -> bool:
        """
        Called at the top of every page to restore and validate the session.

        Flow:
        1. Check if access_token is in session_state
        2. Validate token with Supabase
        3. If expired, try refreshing with refresh_token
        4. If refresh fails, clear state → user must re-login
        5. If profile not loaded, load it

        Returns:
            True if a valid session is active, False otherwise.
        """
        access_token = st.session_state.get("access_token")
        if not access_token:
            return False

        # Validate current token
        user = self.validate_session(access_token)
        if user:
            # Token valid — ensure profile is loaded
            if not st.session_state.get("profile"):
                profile = self.get_profile(str(user.id), access_token)
                st.session_state.profile = profile
            if not st.session_state.get("user"):
                st.session_state.user = user
            return True

        # Token expired — try refreshing
        refresh_token = st.session_state.get("refresh_token")
        if refresh_token:
            result = self.refresh_session(refresh_token)
            if result:
                st.session_state.access_token = result["access_token"]
                st.session_state.refresh_token = result["refresh_token"]
                st.session_state.session = result["session"]

                user = self.validate_session(result["access_token"])
                if user:
                    st.session_state.user = user
                    profile = self.get_profile(str(user.id), result["access_token"])
                    st.session_state.profile = profile
                    return True

        # Both token and refresh failed — clear state
        self.clear_session_state()
        return False

    def save_session_to_state(self, auth_result: dict) -> None:
        """Persist sign-in result to Streamlit session_state."""
        st.session_state.user = auth_result.get("user")
        st.session_state.session = auth_result.get("session")
        st.session_state.profile = auth_result.get("profile")
        st.session_state.access_token = auth_result.get("access_token")
        st.session_state.refresh_token = auth_result.get("refresh_token")

    def clear_session_state(self) -> None:
        """Clear all auth-related keys from session_state. Called on logout or expiry."""
        for key in ("user", "session", "profile", "access_token", "refresh_token"):
            st.session_state[key] = None

    # ── Convenience Accessors ────────────────────────────────

    def is_authenticated(self) -> bool:
        return bool(
            st.session_state.get("user")
            and st.session_state.get("access_token")
        )

    def get_current_user(self):
        return st.session_state.get("user")

    def get_current_profile(self) -> Optional[dict]:
        return st.session_state.get("profile")

    def get_current_role(self) -> str:
        profile = self.get_current_profile()
        return profile.get("role", "player") if profile else "player"

    def is_admin(self) -> bool:
        return self.get_current_role() in ("facility_admin", "super_admin")

    def is_super_admin(self) -> bool:
        return self.get_current_role() == "super_admin"

    # ── Profile Operations ───────────────────────────────────

    def get_profile(self, user_id: str, access_token: str) -> Optional[dict]:
        """Fetch a user's profile from user_profiles table."""
        try:
            client = get_client(access_token, st.session_state.get("refresh_token", ""))
            return get_user_profile(client, user_id)
        except Exception as e:
            logger.error(f"get_profile failed for {user_id}: {e}")
            return None

    def update_profile(
        self,
        user_id: str,
        access_token: str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
        membership_type: Optional[str] = None,
    ) -> dict:
        """
        Update one or more profile fields.

        Only the provided (non-None) fields are updated.
        Raises AuthError for invalid inputs.
        Returns the updated profile dict.
        """
        updates: dict = {}

        if full_name is not None:
            valid, error = validate_name(full_name)
            if not valid:
                raise AuthError(error)
            updates["full_name"] = full_name.strip()

        if phone is not None:
            valid, error = validate_phone(phone)
            if not valid:
                raise AuthError(error)
            updates["phone"] = phone.strip()

        if membership_type is not None:
            valid_types = ["none", "basic", "premium", "corporate"]
            if membership_type not in valid_types:
                raise AuthError(f"Invalid membership type.")
            updates["membership_type"] = membership_type

        if not updates:
            raise AuthError("No changes to save.")

        try:
            refresh_token = st.session_state.get("refresh_token", "")
            client = get_client(access_token, refresh_token)
            response = (
                client.table("user_profiles")
                .update(updates)
                .eq("id", user_id)
                .execute()
            )
            if response.data:
                return response.data[0]
            raise AuthError("Profile update failed — no data returned.")
        except AuthError:
            raise
        except Exception as e:
            logger.error(f"update_profile failed for {user_id}: {e}")
            raise AuthError("Failed to update profile. Please try again.")

    def accept_waiver(self, user_id: str, access_token: str) -> bool:
        """
        Record waiver acceptance with timestamp.
        Returns True on success, False on failure.
        """
        try:
            refresh_token = st.session_state.get("refresh_token", "")
            client = get_client(access_token, refresh_token)
            client.table("user_profiles").update({
                "waiver_accepted": True,
                "waiver_accepted_at": now_utc().isoformat(),
            }).eq("id", user_id).execute()
            return True
        except Exception as e:
            logger.error(f"accept_waiver failed for {user_id}: {e}")
            return False

    # ── Private Helpers ──────────────────────────────────────

    def _ensure_profile_exists(self, user, access_token: str) -> Optional[dict]:
        """
        Check if a user_profiles row exists; create it if not.

        Why admin client?
        The RLS INSERT policy for user_profiles requires user_id = auth.uid().
        On first login after email verification, the user's JWT is valid, so we
        could use the user client. However, using the admin client is simpler and
        avoids edge cases where the JWT claims haven't propagated to Postgres yet.

        This method is safe because:
        1. We hard-code the user_id from the auth response (not user input)
        2. The profile data comes from Supabase's own user.user_metadata
        3. The admin client is never exposed to the user
        """
        try:
            admin_client = get_admin_client()
            existing = get_user_profile(admin_client, str(user.id))

            if existing:
                return existing

            # Build profile from Supabase user metadata (set during sign_up)
            metadata = getattr(user, "user_metadata", {}) or {}
            profile_data = {
                "id": str(user.id),
                "email": user.email or "",
                "full_name": metadata.get("full_name") or (user.email or "User").split("@")[0],
                "phone": metadata.get("phone", ""),
                "role": metadata.get("role", "player"),
                "membership_type": "none",
                "waiver_accepted": False,
            }

            created = upsert_user_profile(admin_client, profile_data)
            return created

        except Exception as e:
            logger.error(f"_ensure_profile_exists failed for {user.id}: {e}")
            return None

    def _validate_signup_inputs(
        self,
        email: str,
        password: str,
        full_name: str,
        phone: Optional[str],
    ) -> None:
        """Validate all signup fields; raise AuthError on the first failure."""
        for validator, value, *_ in [
            (validate_email, email),
            (validate_password, password),
            (validate_name, full_name),
        ]:
            valid, error = validator(value)
            if not valid:
                raise AuthError(error)

        if phone:
            valid, error = validate_phone(phone)
            if not valid:
                raise AuthError(error)

    @staticmethod
    def _parse_auth_error(error: AuthApiError) -> str:
        """Translate Supabase auth error codes into user-friendly messages."""
        msg = str(error).lower()

        if "invalid login credentials" in msg or "invalid_credentials" in msg:
            return "Incorrect email or password. Please try again."
        if "email not confirmed" in msg:
            return "Please verify your email address before signing in."
        if "user already registered" in msg or "already exists" in msg:
            return "An account with this email already exists. Please sign in instead."
        if "weak" in msg and "password" in msg:
            return "Password is too weak. Please choose a stronger password."
        if "rate limit" in msg or "too many" in msg:
            return "Too many attempts. Please wait a moment before trying again."
        if "network" in msg or "timeout" in msg or "connection" in msg:
            return "Connection error. Please check your internet connection and try again."

        # Unexpected error — log it but show a generic message
        logger.error(f"Unhandled AuthApiError: {error}")
        return "An unexpected error occurred. Please try again."


# ── Singleton ────────────────────────────────────────────────

_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Return the module-level AuthService singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
