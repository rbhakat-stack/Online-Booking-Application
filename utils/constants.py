"""
Application-Wide Constants
===========================
Centralises all magic strings, enumerations, and default values.
Import from here instead of hardcoding strings in business logic.
"""

from typing import Final

# ── App ─────────────────────────────────────────────────────
APP_NAME: Final = "SportsPlex"
DEFAULT_TIMEZONE: Final = "America/New_York"
CURRENCY: Final = "usd"
CURRENCY_SYMBOL: Final = "$"

# ── Sports ──────────────────────────────────────────────────
SPORT_TYPES: Final = [
    "pickleball",
    "badminton",
    "tennis",
    "karate",
]

SPORT_ICONS: Final = {
    "pickleball": "🏓",
    "badminton":  "🏸",
    "tennis":     "🎾",
    "karate":     "🥋",
}

# ── Days of Week ─────────────────────────────────────────────
DAYS_OF_WEEK: Final = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]

WEEKDAY_NAMES: Final = ["monday", "tuesday", "wednesday", "thursday", "friday"]
WEEKEND_NAMES: Final = ["saturday", "sunday"]

# ── User Roles ───────────────────────────────────────────────
class UserRole:
    PLAYER: Final = "player"
    FACILITY_ADMIN: Final = "facility_admin"
    SUPER_ADMIN: Final = "super_admin"

    ADMIN_ROLES: Final = [FACILITY_ADMIN, SUPER_ADMIN]
    ALL_ROLES: Final = [PLAYER, FACILITY_ADMIN, SUPER_ADMIN]

# ── Membership Types ─────────────────────────────────────────
class MembershipType:
    NONE: Final = "none"
    BASIC: Final = "basic"
    PREMIUM: Final = "premium"
    CORPORATE: Final = "corporate"

    ALL: Final = [NONE, BASIC, PREMIUM, CORPORATE]

# ── Booking Status ───────────────────────────────────────────
class BookingStatus:
    HOLD: Final = "hold"
    PENDING_PAYMENT: Final = "pending_payment"
    CONFIRMED: Final = "confirmed"
    CANCELLED: Final = "cancelled"
    REFUNDED: Final = "refunded"
    BLOCKED: Final = "blocked"
    EXPIRED: Final = "expired"
    NO_SHOW: Final = "no_show"

    # Statuses that "occupy" a slot (used for conflict checking)
    CONFLICT_STATUSES: Final = ["hold", "pending_payment", "confirmed"]

    # Statuses visible to a regular user in "My Bookings"
    VISIBLE_STATUSES: Final = ["pending_payment", "confirmed", "cancelled", "refunded", "no_show"]

    # Display labels (for UI)
    LABELS: Final = {
        "hold": "⏳ Hold",
        "pending_payment": "💳 Pending Payment",
        "confirmed": "✅ Confirmed",
        "cancelled": "❌ Cancelled",
        "refunded": "💰 Refunded",
        "blocked": "🚫 Blocked",
        "expired": "⌛ Expired",
        "no_show": "👻 No Show",
    }

    # Badge colors for UI display
    COLORS: Final = {
        "hold": "orange",
        "pending_payment": "blue",
        "confirmed": "green",
        "cancelled": "red",
        "refunded": "violet",
        "blocked": "gray",
        "expired": "gray",
        "no_show": "red",
    }

# ── Booking Types ────────────────────────────────────────────
class BookingType:
    STANDARD: Final = "standard"
    FULL_DAY: Final = "full_day"
    EVENT: Final = "event"
    BLOCKED: Final = "blocked"

# ── Court Status ─────────────────────────────────────────────
class CourtStatus:
    ACTIVE: Final = "active"
    INACTIVE: Final = "inactive"
    MAINTENANCE: Final = "maintenance"

# ── Pricing Rule Types ───────────────────────────────────────
class PricingRuleType:
    BASE: Final = "base"
    PEAK: Final = "peak"
    OFF_PEAK: Final = "off_peak"
    WEEKEND: Final = "weekend"
    EVENT: Final = "event"
    MEMBERSHIP: Final = "membership"

# ── Refund Policy ────────────────────────────────────────────
class RefundPolicy:
    # Default thresholds (hours before booking start)
    FULL_REFUND_HOURS: Final = 24       # Full refund if cancelled > 24h before
    PARTIAL_REFUND_HOURS: Final = 12    # 50% refund if cancelled 12–24h before
    PARTIAL_REFUND_PCT: Final = 0.50    # 50%
    # < PARTIAL_REFUND_HOURS → no refund

# ── Hold Settings ────────────────────────────────────────────
HOLD_EXPIRY_MINUTES: Final = 10         # Default hold lifetime during Stripe checkout

# ── Booking Defaults ─────────────────────────────────────────
DEFAULT_MIN_BOOKING_MINUTES: Final = 60
DEFAULT_BOOKING_INCREMENT_MINUTES: Final = 30
DEFAULT_MAX_BOOKING_HOURS: Final = 4
DEFAULT_BOOKING_WINDOW_DAYS: Final = 30

# ── Pricing Defaults (used in seed) ─────────────────────────
DEFAULT_PEAK_START_TIME: Final = "17:00"    # 5:00 PM
DEFAULT_PEAK_END_TIME: Final = "22:00"      # 10:00 PM

# ── Payment Status ───────────────────────────────────────────
class PaymentStatus:
    PENDING: Final = "pending"
    COMPLETED: Final = "completed"
    FAILED: Final = "failed"
    REFUNDED: Final = "refunded"
    PARTIAL_REFUND: Final = "partial_refund"

# ── Inquiry Status ───────────────────────────────────────────
class InquiryStatus:
    PENDING: Final = "pending"
    APPROVED: Final = "approved"
    DENIED: Final = "denied"
    CANCELLED: Final = "cancelled"

# ── Closure Types ────────────────────────────────────────────
class ClosureType:
    ONE_TIME: Final = "one_time"
    RECURRING: Final = "recurring"

# ── Session State Keys ───────────────────────────────────────
# Centralised so we never mistype a key
class SessionKey:
    USER: Final = "user"
    SESSION: Final = "session"
    PROFILE: Final = "profile"
    ACCESS_TOKEN: Final = "access_token"
    REFRESH_TOKEN: Final = "refresh_token"
    # Booking flow
    SELECTED_FACILITY_ID: Final = "selected_facility_id"
    SELECTED_DATE: Final = "selected_date"
    SELECTED_COURT_ID: Final = "selected_court_id"
    SELECTED_START_TIME: Final = "selected_start_time"
    SELECTED_DURATION: Final = "selected_duration"
    ACTIVE_HOLD_ID: Final = "active_hold_id"
    STRIPE_SESSION_ID: Final = "stripe_session_id"
    # UI transient state
    AUTH_SUCCESS_MESSAGE: Final = "auth_success_message"
