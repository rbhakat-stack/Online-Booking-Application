"""
Application Configuration
==========================
Loads all required environment variables at startup.
Raises a clear error if required variables are missing — fail fast is better
than a confusing runtime error deep in a service call.

Usage:
    from utils.config import get_config
    config = get_config()
    print(config.supabase_url)
"""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load .env file if it exists (local development).
# In production (Streamlit Community Cloud), vars are set in the Secrets UI.
load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # Stripe
    stripe_secret_key: str
    stripe_publishable_key: str
    stripe_webhook_secret: str          # Empty string in MVP (webhook not implemented)

    # App
    app_name: str
    app_env: str                        # "development" | "production"
    app_url: str                        # Public URL — used in Stripe return URLs
    default_timezone: str               # IANA timezone (e.g., "America/New_York")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


# Module-level singleton — config is loaded once per process
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """
    Return the application config singleton.
    Raises EnvironmentError if any required variable is missing.
    """
    global _config
    if _config is not None:
        return _config

    required = {
        "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": os.environ.get("SUPABASE_ANON_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "STRIPE_SECRET_KEY": os.environ.get("STRIPE_SECRET_KEY", ""),
        "STRIPE_PUBLISHABLE_KEY": os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}.\n"
            "Copy .env.example to .env and fill in your credentials."
        )

    _config = AppConfig(
        supabase_url=required["SUPABASE_URL"],
        supabase_anon_key=required["SUPABASE_ANON_KEY"],
        supabase_service_role_key=required["SUPABASE_SERVICE_ROLE_KEY"],
        stripe_secret_key=required["STRIPE_SECRET_KEY"],
        stripe_publishable_key=required["STRIPE_PUBLISHABLE_KEY"],
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        app_name=os.environ.get("APP_NAME", "SportsPlex"),
        app_env=os.environ.get("APP_ENV", "development"),
        app_url=os.environ.get("APP_URL", "http://localhost:8501"),
        default_timezone=os.environ.get("DEFAULT_TIMEZONE", "America/New_York"),
    )
    return _config
