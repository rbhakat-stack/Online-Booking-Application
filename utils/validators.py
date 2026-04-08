"""
Input Validators
================
All validation logic in one place.
Each function returns (is_valid: bool, error_message: str).
Empty error_message means valid.

These are used both in the service layer (server-side) and in page
components for immediate feedback. Never rely on client-side only.
"""

import re
from datetime import date, time, datetime, timedelta
from typing import Optional, Tuple


# ── Primitives ───────────────────────────────────────────────

def validate_email(email: str) -> Tuple[bool, str]:
    """Validate email format."""
    if not email or not email.strip():
        return False, "Email address is required."
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email.strip()):
        return False, "Please enter a valid email address."
    if len(email) > 254:
        return False, "Email address is too long."
    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    """
    Enforce password strength policy:
    - At least 8 characters
    - At least one uppercase letter
    - At least one digit
    """
    if not password:
        return False, "Password is required."
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number."
    return True, ""


def validate_name(name: str) -> Tuple[bool, str]:
    """Validate a person's full name."""
    if not name or not name.strip():
        return False, "Full name is required."
    cleaned = name.strip()
    if len(cleaned) < 2:
        return False, "Name must be at least 2 characters."
    if len(cleaned) > 100:
        return False, "Name must be fewer than 100 characters."
    # Allow letters, spaces, hyphens, apostrophes (international names)
    if not re.match(r"^[a-zA-ZÀ-ÿ '\-]+$", cleaned):
        return False, "Name contains invalid characters."
    return True, ""


def validate_phone(phone: str) -> Tuple[bool, str]:
    """Validate phone number (optional field — empty string is OK)."""
    if not phone or not phone.strip():
        return True, ""     # Phone is optional
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return False, "Phone number must have at least 10 digits."
    if len(digits) > 15:
        return False, "Phone number is too long."
    return True, ""


def sanitize_text(text: str, max_length: int = 1000) -> str:
    """Strip whitespace and truncate text to max_length."""
    if not text:
        return ""
    return text.strip()[:max_length]


# ── Booking Validation ───────────────────────────────────────

def validate_booking_date(
    booking_date: date,
    booking_window_days: int = 30,
) -> Tuple[bool, str]:
    """
    Ensure the booking date is:
    - Not in the past (allow today)
    - Within the allowed booking window
    """
    today = date.today()
    if booking_date < today:
        return False, "Booking date cannot be in the past."
    max_date = today + timedelta(days=booking_window_days)
    if booking_date > max_date:
        return False, (
            f"Bookings can only be made up to {booking_window_days} days in advance. "
            f"The latest available date is {max_date.strftime('%B %d, %Y')}."
        )
    return True, ""


def validate_booking_duration(
    duration_minutes: int,
    min_booking_minutes: int = 60,
    max_booking_hours: int = 4,
) -> Tuple[bool, str]:
    """Ensure the requested duration is within facility rules."""
    if duration_minutes < min_booking_minutes:
        return False, (
            f"Minimum booking duration is {min_booking_minutes} minutes "
            f"({min_booking_minutes // 60} hour{'s' if min_booking_minutes >= 120 else ''})."
        )
    max_minutes = max_booking_hours * 60
    if duration_minutes > max_minutes:
        return False, (
            f"Maximum booking duration is {max_booking_hours} hours."
        )
    return True, ""


def validate_time_slot(
    start_time: time,
    end_time: time,
    open_time: time,
    close_time: time,
) -> Tuple[bool, str]:
    """
    Ensure the requested slot fits within operating hours.
    All times are in facility-local timezone.
    """
    if start_time >= end_time:
        return False, "Start time must be before end time."
    if start_time < open_time:
        return False, f"Facility does not open until {open_time.strftime('%I:%M %p')}."
    if end_time > close_time:
        return False, f"Facility closes at {close_time.strftime('%I:%M %p')}. Please choose an earlier end time."
    return True, ""


def validate_promo_code(code: str) -> Tuple[bool, str]:
    """Basic format check for promo codes."""
    if not code or not code.strip():
        return False, "Promo code cannot be empty."
    cleaned = code.strip().upper()
    if len(cleaned) < 3 or len(cleaned) > 20:
        return False, "Promo code must be between 3 and 20 characters."
    if not re.match(r"^[A-Z0-9_\-]+$", cleaned):
        return False, "Promo code can only contain letters, numbers, hyphens, and underscores."
    return True, ""


def validate_notes(notes: str, max_length: int = 500) -> Tuple[bool, str]:
    """Validate optional booking notes."""
    if notes and len(notes) > max_length:
        return False, f"Notes must be fewer than {max_length} characters."
    return True, ""
