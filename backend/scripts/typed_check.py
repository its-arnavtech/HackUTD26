"""Run realistic typed messages (real companies, real-looking links) through the live pipeline.

    python -m scripts.typed_check          # about 2 minutes of live Nemotron calls

Prints category, verdict and whether it matches the expected answer. These are
hand-written synthetic demo messages, not the held-out test split.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.contracts import MessageIn
from app.pipeline import Pipeline

CASES: list[tuple[bool, str, str]] = [
    (True, "+18885550101", "Chase Alert: Your account has been locked due to suspicious activity. Verify your identity at chase-secure-verify.com within 24 hours."),
    (True, "+18885550102", "PayPal: You received $500.00. Claim it at paypal-claims-center.com before it expires today."),
    (True, "+18885550103", "Amazon: Your order is on hold because your payment failed. Update your card at amazon-billing-update.net to avoid cancellation."),
    (True, "+18885550104", "T-Mobile: Your bill of $85.40 is past due. Pay now at tmobile-payment-help.com to avoid service suspension tonight."),
    (True, "+18885550105", "Wells Fargo: We noticed a new sign-in. Reply with the 6-digit code we just sent you to confirm it was you."),
    (True, "+18885550106", "Apple ID: Your account will be disabled today. Restore access now at appleid-support-verify.com"),
    (True, "+18885550107", "UPS: Your package could not be delivered. Pay the $1.99 redelivery fee at ups-redelivery-fee.com"),
    (False, "227898", "Capital One: A purchase of $42.17 at H-E-B was made on your Venture card. If this wasn't you, call the number on the back of your card."),
    (False, "T-Mobile", "Free T-Mobile msg: Your bill of $85.00 is ready. AutoPay will charge your saved card on 11/15. Details in the T-Mobile app."),
]


def main() -> int:
    pipeline = Pipeline()
    pipeline.warm()
    right = 0
    for i, (is_scam, sender, text) in enumerate(CASES, 1):
        trail: list = []
        result = pipeline.run(f"typed_{i}", MessageIn(text=text, sender=sender, received_at=datetime.now(timezone.utc)), trail.append)
        ok = (result.verdict.value == "likely_scam") == is_scam and result.verdict.value != "unsure"
        right += ok
        tools = [t.tool.value for t in trail if t.kind.value == "tool" and t.tool]
        print(f"{i}. {'scam ' if is_scam else 'real '} -> {result.verdict.value:12} {result.confidence_words.value:12} {'OK' if ok else 'MISS'}  tools={tools}")
        print(f"     {result.reason[:150]}")
    print(f"\n{right}/{len(CASES)} right")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
