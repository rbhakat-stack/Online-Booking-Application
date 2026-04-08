"""
Supabase Client Factory
========================
Provides two client types:

1. get_client(access_token, refresh_token)
   - Uses the ANON key
   - Row Level Security IS enforced
   - Pass user tokens to make requests as that user (RLS checks their role)
   - Use for: all user-facing reads and writes

2. get_admin_client()
   - Uses the SERVICE ROLE key
   - Row Level Security is BYPASSED
   - Use ONLY for:
       • Payment verification → booking confirmation (Phase 4)
       • Profile creation on first login (can't insert own profile via RLS before it exists)
       • Audit log writes
       • Scheduled cleanup (expired holds, waitlist processing)
   - NEVER pass user-controlled values directly to admin client queries
     without sanitisation — this client has full DB access.

Both clients are created fresh per call (not cached as module singletons)
because Streamlit reruns the entire script on every interaction, making
a module-level singleton impractical for per-user JWT sessions.

The overhead of create_client() is negligible (it does not open a DB connection;
it only configures the HTTP client).
"""

from typing import Optional
from supabase import create_client, Client
from utils.config import get_config


def get_client(
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> Client:
    """
    Return a Supabase client scoped to the given user session.

    If access_token + refresh_token are provided, the client makes requests
    as that user, so Postgres RLS policies are applied with auth.uid() set
    to that user's UUID.

    If no tokens are provided, requests are made as the anonymous role
    (only public data is accessible per RLS).

    Args:
        access_token:  Supabase JWT access token from session state
        refresh_token: Supabase refresh token (used to restore expired sessions)
    """
    config = get_config()
    client: Client = create_client(config.supabase_url, config.supabase_anon_key)

    if access_token and refresh_token:
        try:
            # Sets auth headers so every subsequent DB/storage call includes the JWT.
            # This is what makes RLS work: auth.uid() in Postgres resolves to the
            # user whose token we set here.
            client.auth.set_session(access_token, refresh_token)
        except Exception:
            # If the session is expired/invalid, continue as anon.
            # The caller should handle this case (e.g., redirect to login).
            pass

    return client


def get_admin_client() -> Client:
    """
    Return a Supabase client using the service role key.

    ⚠️  SECURITY WARNING ⚠️
    This client bypasses ALL Row Level Security policies.
    Any query made with this client can read/write any row in any table.

    Rules for usage:
    - Only instantiate inside service-layer functions, never in page/component code
    - Never pass user-supplied strings directly into queries on this client
      without explicit sanitisation (use parameterised queries / .eq() etc.)
    - Do not log or expose the service role key anywhere
    """
    config = get_config()
    return create_client(config.supabase_url, config.supabase_service_role_key)


def get_session_client(session_state) -> Client:
    """
    Convenience wrapper: build a user-scoped client from Streamlit session_state.

    Usage in service methods:
        client = get_session_client(st.session_state)
        client.table("bookings").select("*").execute()

    Falls back to anonymous client if session tokens are not present.
    """
    access_token: Optional[str] = getattr(session_state, "access_token", None)
    refresh_token: Optional[str] = getattr(session_state, "refresh_token", None)
    return get_client(access_token, refresh_token)
