"""
Pricing Service
================
Determines the correct price for a booking based on configurable pricing rules
stored in the pricing_rules table.

Rule Matching Algorithm:
  1. Load all active pricing rules for the facility (ordered by priority DESC)
  2. For each rule, test applicability:
       a. Day-of-week: rule.applies_to_days is NULL  OR  date's day is in the array
       b. Time window:  rule.peak_start_time/end_time is NULL  OR  start_time is in [peak_start, peak_end)
       c. Sport type:   rule.sport_type is NULL  OR  matches court's sport_type
       d. Court:        rule.court_id is NULL  OR  matches the specific court_id
  3. The FIRST matching rule (highest priority) is used for base price
  4. Membership discounts are applied on top of the base price

Pricing is applied based on the booking START time. A session starting at
4:30 PM (off-peak) that ends at 6:30 PM (peak) is charged at the off-peak
rate. Pro-rated pricing is out of scope for MVP.

Default seeded pricing tiers (see seed.sql):
  priority  type       condition                    price/hr
  --------  ---------  ---------------------------  --------
  0         base       Catch-all                    $25
  10        off_peak   Mon–Fri, before 5 PM         $20
  15        weekend    Sat–Sun, all day              $40
  20        peak       Mon–Fri, 5 PM–10 PM           $35
  25        event      Full-day event               $45 (+ flat price_full_day)
"""

from datetime import date, time, datetime
from typing import Optional
from utils.time_utils import get_day_of_week_name, parse_time_str, format_duration


# ── Public API ────────────────────────────────────────────────

def calculate_price(
    pricing_rules: list[dict],
    booking_date: date,
    start_time: time,
    duration_minutes: int,
    sport_type: Optional[str] = None,
    court_id: Optional[str] = None,
    membership_type: str = "none",
    is_full_day: bool = False,
) -> dict:
    """
    Find the best matching pricing rule and calculate total cost.

    Args:
        pricing_rules:    Active rules for this facility, sorted by priority DESC
        booking_date:     Local date of the booking (for day-of-week lookup)
        start_time:       Local start time (determines peak/off-peak)
        duration_minutes: Total booking duration
        sport_type:       Court's sport type (for sport-specific rules)
        court_id:         Court UUID (for court-specific rules)
        membership_type:  User's membership level (for discount rules)
        is_full_day:      True for full-day / event bookings

    Returns:
        {
            "price_per_hour":  float,
            "hours":           float,
            "base_amount":     float,
            "discount_amount": float,
            "total_amount":    float,
            "rule_name":       str,
            "rule_type":       str,
            "breakdown":       list[dict],  # line items for display
        }
    """
    hours = duration_minutes / 60.0
    day_name = get_day_of_week_name(booking_date)

    # Find the best matching rule
    matched_rule = _find_matching_rule(
        pricing_rules=pricing_rules,
        day_name=day_name,
        start_time=start_time,
        sport_type=sport_type,
        court_id=court_id,
        is_full_day=is_full_day,
    )

    if matched_rule is None:
        # No rule configured — use a safe fallback
        return _fallback_pricing(hours, duration_minutes)

    # Determine base price
    if is_full_day and matched_rule.get("price_full_day") is not None:
        price_per_hour = float(matched_rule["price_full_day"]) / max(hours, 1)
        base_amount = float(matched_rule["price_full_day"])
    else:
        price_per_hour = float(matched_rule["price_per_hour"])
        base_amount = price_per_hour * hours

    # Apply membership discount
    discount_amount, discount_label = _apply_membership_discount(
        base_amount, membership_type
    )

    total_amount = max(0.0, base_amount - discount_amount)

    breakdown = [
        {
            "description": f"{matched_rule['name']} — {format_duration(duration_minutes)} @ ${price_per_hour:.2f}/hr",
            "amount": base_amount,
        }
    ]
    if discount_amount > 0:
        breakdown.append({
            "description": f"Membership discount ({discount_label})",
            "amount": -discount_amount,
        })

    return {
        "price_per_hour": price_per_hour,
        "hours": hours,
        "base_amount": round(base_amount, 2),
        "discount_amount": round(discount_amount, 2),
        "total_amount": round(total_amount, 2),
        "rule_name": matched_rule["name"],
        "rule_type": matched_rule["rule_type"],
        "breakdown": breakdown,
    }


def get_price_preview_for_day(
    pricing_rules: list[dict],
    booking_date: date,
    sport_type: Optional[str] = None,
) -> dict:
    """
    Return a quick preview of the applicable price tier for a day.
    Used on the availability page to show pricing at a glance.

    Returns:
        {"label": str, "price_per_hour": float, "rule_type": str}
    """
    day_name = get_day_of_week_name(booking_date)

    # Check weekend
    if day_name in ("saturday", "sunday"):
        rule = _find_matching_rule(pricing_rules, day_name, time(9, 0), sport_type, None, False)
    else:
        # Check peak (representative time: 6 PM)
        rule = _find_matching_rule(pricing_rules, day_name, time(18, 0), sport_type, None, False)

    if not rule:
        return {"label": "Standard", "price_per_hour": 0.0, "rule_type": "base"}

    return {
        "label": rule["name"],
        "price_per_hour": float(rule["price_per_hour"]),
        "rule_type": rule["rule_type"],
    }


def generate_duration_options(
    min_booking_minutes: int,
    max_booking_hours: int,
    booking_increment_minutes: int,
) -> list[dict]:
    """
    Generate the list of valid duration choices for the UI duration selector.

    Returns:
        [{"minutes": int, "label": str}, ...]

    Example (min=60, max=4, increment=30):
        60  → "1 hour"
        90  → "1.5 hours"
        120 → "2 hours"
        150 → "2.5 hours"
        180 → "3 hours"
        210 → "3.5 hours"
        240 → "4 hours"
    """
    options = []
    max_minutes = max_booking_hours * 60
    current = min_booking_minutes

    while current <= max_minutes:
        options.append({
            "minutes": current,
            "label": format_duration(current),
        })
        current += booking_increment_minutes

    return options


# ── Private Helpers ───────────────────────────────────────────

def _find_matching_rule(
    pricing_rules: list[dict],
    day_name: str,
    start_time: time,
    sport_type: Optional[str],
    court_id: Optional[str],
    is_full_day: bool,
) -> Optional[dict]:
    """
    Return the first rule (highest priority) that applies to the given parameters.
    pricing_rules must already be sorted by priority DESC.
    """
    for rule in pricing_rules:
        if not rule.get("is_active", True):
            continue

        # Full-day event matching
        if is_full_day and rule.get("rule_type") != "event":
            continue
        if not is_full_day and rule.get("rule_type") == "event":
            continue

        # Day of week filter
        applies_to_days = rule.get("applies_to_days")
        if applies_to_days and isinstance(applies_to_days, list):
            if day_name not in applies_to_days:
                continue

        # Time window filter (peak_start_time / peak_end_time)
        peak_start_str = rule.get("peak_start_time")
        peak_end_str = rule.get("peak_end_time")
        if peak_start_str and peak_end_str:
            peak_start = parse_time_str(str(peak_start_str))
            peak_end = parse_time_str(str(peak_end_str))
            if peak_start and peak_end:
                if not (peak_start <= start_time < peak_end):
                    continue
        elif peak_start_str and not peak_end_str:
            # Only start defined — treat as "at or after"
            peak_start = parse_time_str(str(peak_start_str))
            if peak_start and start_time < peak_start:
                continue
        elif peak_end_str and not peak_start_str:
            # Only end defined — treat as "before"
            peak_end = parse_time_str(str(peak_end_str))
            if peak_end and start_time >= peak_end:
                continue

        # Sport type filter
        rule_sport = rule.get("sport_type")
        if rule_sport and sport_type and rule_sport.lower() != sport_type.lower():
            continue

        # Court-specific filter
        rule_court = rule.get("court_id")
        if rule_court and court_id and str(rule_court) != str(court_id):
            continue

        # This rule matches — return it
        return rule

    return None


def _apply_membership_discount(
    base_amount: float,
    membership_type: str,
) -> tuple[float, str]:
    """
    Return (discount_amount, label) for the user's membership level.

    Discount rates (configurable in a future membership_discounts table):
      none      → 0%
      basic     → 10%
      premium   → 20%
      corporate → 25%
    """
    discounts = {
        "none":      (0.00, ""),
        "basic":     (0.10, "10% Basic member"),
        "premium":   (0.20, "20% Premium member"),
        "corporate": (0.25, "25% Corporate member"),
    }
    rate, label = discounts.get(membership_type, (0.0, ""))
    return round(base_amount * rate, 2), label


def _fallback_pricing(hours: float, duration_minutes: int) -> dict:
    """Used when no pricing rules are configured for the facility."""
    base_amount = 0.0
    return {
        "price_per_hour": 0.0,
        "hours": hours,
        "base_amount": base_amount,
        "discount_amount": 0.0,
        "total_amount": 0.0,
        "rule_name": "No pricing configured",
        "rule_type": "base",
        "breakdown": [
            {
                "description": "Contact facility for pricing",
                "amount": 0.0,
            }
        ],
    }
