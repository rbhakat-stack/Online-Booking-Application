"""
Pricing Summary Component
==========================
Renders a pricing breakdown card on the booking confirmation page.
"""

import streamlit as st


def render_pricing_summary(
    price_info: dict,
    show_policy: bool = True,
    cancellation_window_hours: int = 24,
    partial_refund_window_hours: int = 12,
) -> None:
    """
    Render the full pricing breakdown and (optionally) the refund policy.

    Args:
        price_info:                  Output of pricing_service.calculate_price()
        show_policy:                 Whether to show the cancellation policy below the total
        cancellation_window_hours:   Hours before which full refund is given
        partial_refund_window_hours: Hours before which partial refund is given
    """
    breakdown = price_info.get("breakdown", [])
    total = price_info.get("total_amount", 0.0)
    tax = price_info.get("tax_amount", 0.0)
    fee = price_info.get("fee_amount", 0.0)

    lines_html = ""
    for item in breakdown:
        amount = item["amount"]
        color = "#ef4444" if amount < 0 else "#1a1a2e"
        sign = "−" if amount < 0 else ""
        lines_html += (
            f"<div style='display:flex;justify-content:space-between;margin-bottom:0.3rem'>"
            f"<span style='color:#6b7280;font-size:0.9rem'>{item['description']}</span>"
            f"<span style='color:{color};font-weight:500'>{sign}${abs(amount):.2f}</span>"
            f"</div>"
        )

    # Tax and fee lines (shown as placeholders when 0)
    if tax > 0:
        lines_html += (
            f"<div style='display:flex;justify-content:space-between;margin-bottom:0.3rem'>"
            f"<span style='color:#6b7280;font-size:0.9rem'>Tax</span>"
            f"<span style='font-weight:500'>${tax:.2f}</span>"
            f"</div>"
        )
    if fee > 0:
        lines_html += (
            f"<div style='display:flex;justify-content:space-between;margin-bottom:0.3rem'>"
            f"<span style='color:#6b7280;font-size:0.9rem'>Booking fee</span>"
            f"<span style='font-weight:500'>${fee:.2f}</span>"
            f"</div>"
        )

    total_line = (
        f"<div style='display:flex;justify-content:space-between;"
        f"border-top:2px solid #0ea5e9;margin-top:0.75rem;padding-top:0.75rem'>"
        f"<span style='font-weight:700;font-size:1rem;color:#0f172a'>Total Due Today</span>"
        f"<span style='font-weight:800;font-size:1.2rem;color:#0ea5e9'>${total:.2f}</span>"
        f"</div>"
    )

    policy_html = ""
    if show_policy:
        partial_pct = 50
        policy_html = f"""
        <div style="margin-top:1rem;padding:0.75rem;background:#fffbeb;
                    border-radius:8px;border:1px solid #fde68a;font-size:0.8rem;color:#78716c">
            <strong>Cancellation Policy:</strong><br>
            ✓ &nbsp;Full refund if cancelled &gt; {cancellation_window_hours}h before start<br>
            ◑ &nbsp;{partial_pct}% refund if cancelled {partial_refund_window_hours}–{cancellation_window_hours}h before start<br>
            ✗ &nbsp;No refund within {partial_refund_window_hours}h of start time
        </div>
        """

    st.markdown(
        f"""
        <div style="
            background:linear-gradient(135deg,#f0f7ff,#f8f9ff);
            border-radius:12px;
            padding:1.25rem 1.5rem;
            border:1px solid #d0e0ff;
        ">
            <div style="font-weight:700;font-size:1rem;color:#1a1a2e;margin-bottom:0.75rem">
                💰 Price Breakdown
            </div>
            {lines_html}
            {total_line}
            {policy_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_compact_price(total_amount: float, rule_name: str = "") -> None:
    """Compact price chip used in availability slot grids."""
    rule_str = f" · {rule_name}" if rule_name else ""
    st.markdown(
        f"<span style='background:#e0f2fe;color:#0ea5e9;border-radius:999px;"
        f"padding:0.15rem 0.6rem;font-size:0.82rem;font-weight:600'>"
        f"${total_amount:.2f}{rule_str}</span>",
        unsafe_allow_html=True,
    )
