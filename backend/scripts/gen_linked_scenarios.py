"""Seeded synthetic data for the linked-scenario gaps (no model calls).

Writes, under ``data/generated/``:

- ``messages_multiclass.jsonl`` — DATA_SPEC 3.1 shape plus taxonomy labels
- ``campaigns.jsonl`` — campaign variants
- ``urls.jsonl`` — link rows with an RDAP stub
- ``linked_scenarios.jsonl`` — message, click, baseline, and post events
- ``telecom_events.jsonl`` — carrier events in the canonical schema
- ``nessie_export/<scenario_id>.json`` — DATA_SPEC section 6 objects
- ``SYNTHETIC_LINKED_README.md`` — datasheet
- ``synthetic_linked_manifest.json`` — seed and counts

The A21 files (``messages.jsonl``, ``splits.json``, ``handwritten.jsonl``,
``meta.jsonl``, ``quality_report.json``, ``README.md``) are not touched.

Run from ``backend/``::

    python -m scripts.gen_linked_scenarios

Seed ``20261108``. Template set A feeds train and validation. Template set B
feeds test. No template, URL, or sender is shared between those sets.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

SEED = 20261108
GENERATOR = "scripts.gen_linked_scenarios"
MODEL = "none (deterministic seeded templates, no LLM API)"
WARNING = "synthetic only — not real customer data"

OUT_DIR = DATA_DIR / "generated"
EXPORT_DIR = OUT_DIR / "nessie_export"
SCHEMA_PATH = OUT_DIR / "payment_schema.json"

CENTRAL = timezone(timedelta(hours=-6))
AS_OF = datetime(2026, 11, 8, 9, 14, tzinfo=CENTRAL)

TAXONOMY = [
    "bank_impersonation",
    "billing_scam",
    "delivery_scam",
    "account_security",
    "toll_government",
    "prize_refund",
    "job_offer",
    "conversation_lure",
    "legit",
]
SCAM_TAXONOMY = [c for c in TAXONOMY if c != "legit"]

PER_CATEGORY = 200
COUNT_A = 170  # train 140 + validation 30
COUNT_B = 30
TRAIN_N = 140
VAL_N = 30

TELECOM_TYPES = {
    "sim_change",
    "esim_transfer",
    "port_out_request",
    "plan_change",
    "device_add",
    "bill_amount_change",
    "autopay_change",
}
KNOWN_BILLER = "Northline Mobile"
UNKNOWN_PAYEE = "Unknown Payee"

# Reserved 555-01xx lines (exchange 555, line 01xx): 0100–0199, partitioned.
LINES_A = list(range(100, 140))
LINES_B = list(range(140, 170))
LINES_CAMP = list(range(170, 185))
LINES_SCN_A = list(range(185, 192))
LINES_SCN_B = list(range(192, 200))

FIRST_NAMES = ["Alex", "Jordan", "Riley", "Casey", "Quinn", "Avery", "Drew", "Skyler", "Rowan", "Parker"]
LAST_NAMES = ["Sample", "Example", "North", "Demo", "Placeholder"]

BRANDS: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "bank_impersonation": {
        "A": [("Wells Fargo", "wellsfargo", "we11sfargo"), ("Harbor Mutual", "harbor", "harb0r")],
        "B": [("Chase", "chase", "chase-secure"), ("Pine Summit Bank", "pinesummit", "p1ne-summit")],
    },
    "billing_scam": {
        "A": [("T-Mobile", "tmobile", "tm0bile"), ("Northline Mobile", "northline", "n0rthline")],
        "B": [("Verizon", "verizon", "veriz0n"), ("Ridgewave Wireless", "ridgewave", "r1dgewave")],
    },
    "delivery_scam": {
        "A": [("USPS", "usps", "usps-hold"), ("Parcel Lane", "parcellane", "parcel-1ane")],
        "B": [("FedEx", "fedex", "fedex-fee"), ("Crate Route", "crateroute", "crate-r0ute")],
    },
    "account_security": {
        "A": [("Apple", "apple", "app1e"), ("Amazon", "amazon", "amaz0n")],
        "B": [("Google", "google", "goog1e"), ("Kipper Cloud", "kipper", "k1pper")],
    },
    "toll_government": {
        "A": [("SunPass", "sunpass", "sunpass-pay"), ("Cedar Tollway", "cedartoll", "cedar-t0ll")],
        "B": [("TxTag", "txtag", "txtag-fee"), ("Lake County Toll", "laketoll", "lake-t0ll")],
    },
    "prize_refund": {
        "A": [("PayPal", "paypal", "paypaI"), ("Brightcart Rewards", "brightcart", "bright-cart")],
        "B": [("Walmart", "walmart", "wa1mart"), ("Maple Rewards", "maple", "map1e-rewards")],
    },
    "job_offer": {
        "A": [("Fieldstone Tasks", "fieldstone", "f1eldstone"), ("Indeed", "indeed", "1ndeed")],
        "B": [("Hearthside Hire", "hearthside", "hearth-s1de"), ("LinkedIn", "linkedin", "l1nkedin")],
    },
    "conversation_lure": {
        "A": [("a family contact", "family", "family")],
        "B": [("an old coworker", "coworker", "coworker")],
    },
    "legit": {
        "A": [("Northline Mobile", "northline", "northline"), ("Parcel Lane", "parcellane", "parcellane"), ("Harbor Mutual", "harbor", "harbor"), ("Cedar Tollway", "cedartoll", "cedartoll")],
        "B": [("Ridgewave Wireless", "ridgewave", "ridgewave"), ("Crate Route", "crateroute", "crateroute"), ("Pine Summit Bank", "pinesummit", "pinesummit"), ("Lake County Toll", "laketoll", "laketoll")],
    },
}

LOOKALIKE_OF = {
    "Wells Fargo": "wellsfargo.com",
    "Chase": "chase.com",
    "Harbor Mutual": "harbor.example",
    "Pine Summit Bank": "pinesummit.example",
    "T-Mobile": "t-mobile.com",
    "Verizon": "verizon.com",
    "Northline Mobile": "northline.example",
    "Ridgewave Wireless": "ridgewave.example",
    "USPS": "usps.com",
    "FedEx": "fedex.com",
    "Parcel Lane": "parcellane.example",
    "Crate Route": "crateroute.example",
    "Apple": "apple.com",
    "Google": "google.com",
    "Amazon": "amazon.com",
    "Kipper Cloud": "kipper.example",
    "SunPass": "sunpass.com",
    "TxTag": "txtag.example",
    "Cedar Tollway": "cedartoll.example",
    "Lake County Toll": "laketoll.example",
    "PayPal": "paypal.com",
    "Walmart": "walmart.com",
    "Brightcart Rewards": "brightcart.example",
    "Maple Rewards": "maple.example",
    "Fieldstone Tasks": "fieldstone.example",
    "Hearthside Hire": "hearthside.example",
    "Indeed": "indeed.com",
    "LinkedIn": "linkedin.com",
}

CAMP_BRANDS = {
    "bank_impersonation": ["Wells Fargo", "Chase", "Harbor Mutual", "Capital One"],
    "billing_scam": ["T-Mobile", "Verizon", "Netflix", "Northline Mobile"],
    "delivery_scam": ["USPS", "FedEx", "UPS", "Parcel Lane"],
    "account_security": ["Apple", "Amazon", "Google", "Microsoft"],
    "toll_government": ["SunPass", "TxTag", "IRS", "Cedar Tollway"],
    "prize_refund": ["PayPal", "Walmart", "Target", "Brightcart Rewards"],
    "job_offer": ["Indeed", "LinkedIn", "Fieldstone Tasks", "Hearthside Hire"],
    "conversation_lure": ["a family contact", "an old coworker", "a neighbor", "a classmate"],
}
for _extra in ("Capital One", "Netflix", "UPS", "Microsoft", "IRS", "Target"):
    LOOKALIKE_OF.setdefault(
        _extra,
        {
            "Capital One": "capitalone.com",
            "Netflix": "netflix.com",
            "UPS": "ups.com",
            "Microsoft": "microsoft.com",
            "IRS": "irs.gov",
            "Target": "target.com",
        }[_extra],
    )

AMOUNTS = [18, 48, 64, 86, 129, 240]
DEADLINES = ["2 hours", "today", "tonight", "30 minutes", "by 9 PM"]


def _frame(text: str, sender: str, technique: str | None, subtype: str, **features: Any) -> dict[str, Any]:
    return {"text": text, "sender": sender, "technique": technique, "subtype": subtype, "features": features}


def _load_frames() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Hand-written frames. Set B never reuses a set A sentence."""
    A = "long_code"
    S = "short_code"
    N = "alphanumeric"
    E = "email"
    frames: dict[str, dict[str, list[dict[str, Any]]]] = {
        "bank_impersonation": {
            "A": [
                _frame("{brand} alert: a charge of {amount} needs a confirmation within {deadline}. Review: <URL_1>", A, "typosquat", "fraud_alert", threat="account_lock", requested_action="click_link_and_verify", asks_for=["login"]),
                _frame("{brand}: unusual sign-in for <PERSON>. The profile locks {deadline} unless you verify at <URL_1>", S, "homoglyph", "sign_in", threat="account_lock", requested_action="verify_account", asks_for=["login"]),
                _frame("From {brand} card services. A debit of {amount} was declined. Unlock the card here <URL_1>", N, "subdomain abuse", "card_declined", threat="account_lock", requested_action="click_link_and_verify", asks_for=["card_details"]),
                _frame("{brand} fraud desk closed case review. Confirm {amount} was yours: <URL_1> ({deadline})", E, "URL shortener", "fraud_alert", threat="account_lock", requested_action="click_link", asks_for=["login"]),
                _frame("{brand}: we placed a hold. Clear the {amount} hold before {deadline} at <URL_1>", A, "fresh registration", "hold", threat="account_lock", requested_action="click_link_and_verify", asks_for=["account_details"]),
                _frame("{brand} online banking: password help for <PERSON> expires {deadline}. Continue at <URL_1>", S, "typosquat", "password", threat="account_lock", requested_action="share_credentials", asks_for=["password"]),
                _frame("Notice, {brand} wire team. A transfer of {amount} is waiting. Approve it: <URL_1>", N, "homoglyph", "wire", threat="payment_penalty", requested_action="click_link_and_verify", asks_for=["login"]),
                _frame("{brand}: your debit card ending <ACCOUNT_DIGITS> is frozen. Restore access <URL_1>", E, "subdomain abuse", "card_frozen", threat="account_lock", requested_action="click_link", asks_for=["card_details"]),
            ],
            "B": [
                _frame("Security note from {brand}. Was {amount} you? The review link closes {deadline}: <URL_1>", A, "typosquat", "fraud_alert", threat="account_lock", requested_action="click_link_and_verify", asks_for=["login"]),
                _frame("{brand} locked a session after a new device signed in. Reopen it at <URL_1> before {deadline}", S, "homoglyph", "sign_in", threat="account_lock", requested_action="verify_account", asks_for=["password"]),
                _frame("{brand} card freeze on ending <ACCOUNT_DIGITS>. Lift the freeze: <URL_1>", N, "URL shortener", "card_frozen", threat="account_lock", requested_action="click_link", asks_for=["card_details"]),
                _frame("Hello from {brand} payments. Outgoing {amount} needs an ok by {deadline}. <URL_1>", E, "fresh registration", "wire", threat="payment_penalty", requested_action="click_link_and_verify", asks_for=["account_details"]),
            ],
        },
        "billing_scam": {
            "A": [
                _frame("{brand}: autopay failed. Service stops in {deadline} unless {amount} is paid at <URL_1>", A, "typosquat", "autopay_failed", threat="service_suspension", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand} billing: the {amount} invoice is overdue. Avoid suspension {deadline}: <URL_1>", S, "homoglyph", "overdue", threat="service_suspension", requested_action="make_payment", asks_for=["payment"]),
                _frame("Past due notice, {brand}. Update the card for {amount} here <URL_1> ({deadline})", N, "subdomain abuse", "card_update", threat="service_suspension", requested_action="click_link_and_pay", asks_for=["card_details"]),
                _frame("{brand} final notice before shutoff. Balance {amount}. Pay <URL_1>", E, "URL shortener", "shutoff", threat="service_suspension", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand}: a refund of {amount} is larger than the bill. Send the difference back via <URL_1>", A, "fresh registration", "overpayment", threat="payment_penalty", requested_action="make_payment", asks_for=["payment"]),
                _frame("{brand} account {deadline}: mobile line disconnects over {amount}. Restore <URL_1>", S, "typosquat", "disconnect", threat="service_suspension", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("Your {brand} plan renewal for {amount} did not clear. Fix the method: <URL_1>", N, "homoglyph", "renewal", threat="service_suspension", requested_action="click_link", asks_for=["card_details"]),
                _frame("{brand} utilities desk. Shutoff for {amount} is scheduled {deadline}. Portal: <URL_1>", E, "subdomain abuse", "utility", threat="service_suspension", requested_action="click_link_and_pay", asks_for=["payment"]),
            ],
            "B": [
                _frame("{brand} could not draft {amount}. Keep the line on by {deadline} using <URL_1>", A, "typosquat", "autopay_failed", threat="service_suspension", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("Balance reminder ({brand}). {amount} must post {deadline} or calls stop. <URL_1>", S, "homoglyph", "overdue", threat="service_suspension", requested_action="make_payment", asks_for=["payment"]),
                _frame("{brand} says the card on file expired. New card form: <URL_1>", N, "URL shortener", "card_update", threat="service_suspension", requested_action="click_link", asks_for=["card_details"]),
                _frame("Overpaid invoice at {brand} by {amount}. Return it before {deadline}: <URL_1>", E, "fresh registration", "overpayment", threat="payment_penalty", requested_action="make_payment", asks_for=["payment"]),
            ],
        },
        "delivery_scam": {
            "A": [
                _frame("{brand}: delivery held. Address incomplete for <PERSON>. Update by {deadline}: <URL_1>", A, "typosquat", "address", threat="payment_penalty", requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} customs fee {amount} is due {deadline} or the parcel returns. Pay <URL_1>", S, "homoglyph", "customs_fee", threat="payment_penalty", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("Missed drop from {brand}. Redelivery window closes {deadline}. Schedule: <URL_1>", N, "subdomain abuse", "redelivery", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} warehouse hold. Release fee {amount}: <URL_1>", E, "URL shortener", "warehouse", threat="payment_penalty", requested_action="click_link_and_pay", asks_for=["card_details"]),
                _frame("{brand}: we need a delivery photo id for <PERSON> before {deadline}. Upload <URL_1>", A, "fresh registration", "photo_id", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Parcel {brand} ref <ACCOUNT_DIGITS> is waiting. {amount} storage starts {deadline}. <URL_1>", S, "typosquat", "storage", threat="payment_penalty", requested_action="make_payment", asks_for=["payment"]),
                _frame("{brand} driver could not access the door. Pick a new slot: <URL_1>", N, "homoglyph", "reschedule", threat=None, requested_action="click_link", asks_for=[]),
                _frame("Final hold notice, {brand}. Claim {amount} package {deadline} at <URL_1>", E, "subdomain abuse", "final_hold", threat="payment_penalty", requested_action="click_link_and_pay", asks_for=["payment"]),
            ],
            "B": [
                _frame("{brand} left a door tag. Confirm the street for <PERSON> before {deadline}: <URL_1>", A, "typosquat", "address", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Import charge {amount} on a {brand} parcel. Settle {deadline} or it is refused. <URL_1>", S, "homoglyph", "customs_fee", threat="payment_penalty", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand} route delay. Choose another day here <URL_1>", N, "URL shortener", "reschedule", threat=None, requested_action="click_link", asks_for=[]),
                _frame("Storage on {brand} tracking <ACCOUNT_DIGITS> hits {amount} {deadline}. Release form <URL_1>", E, "fresh registration", "storage", threat="payment_penalty", requested_action="make_payment", asks_for=["card_details"]),
            ],
        },
        "account_security": {
            "A": [
                _frame("{brand}: a new device is on the account of <PERSON>. If this was not you, secure it {deadline}: <URL_1>", A, "typosquat", "new_device", threat="account_lock", requested_action="verify_account", asks_for=["password"]),
                _frame("{brand} password reset just started. Cancel by {deadline} at <URL_1> if you did not ask.", S, "homoglyph", "password_reset", threat="account_lock", requested_action="click_link", asks_for=["password"]),
                _frame("{brand} needs the code we sent, reply not required, open <URL_1> and enter it to stop a SIM change.", N, "subdomain abuse", "sim_warning", threat="account_lock", requested_action="share_credentials", asks_for=["one_time_code"]),
                _frame("Your {brand} profile will be disabled {deadline}. Keep it: <URL_1>", E, "URL shortener", "disable", threat="account_deletion", requested_action="click_link_and_verify", asks_for=["login"]),
                _frame("{brand}: unusual order for {amount}. Cancel the order here <URL_1>", A, "fresh registration", "odd_order", threat="payment_penalty", requested_action="click_link", asks_for=["login"]),
                _frame("{brand} support: text the one-time code back so we can lock the SIM. Portal <URL_1>", S, "typosquat", "otp_reply", threat="account_lock", requested_action="reply_with_code", asks_for=["one_time_code"]),
                _frame("Sign-in from a new city on {brand}. Approve <PERSON> or deny: <URL_1> ({deadline})", N, "homoglyph", "new_city", threat="account_lock", requested_action="verify_account", asks_for=["login"]),
                _frame("{brand} ID check expires {deadline}. Upload a photo of the card: <URL_1>", E, "subdomain abuse", "id_check", threat="account_deletion", requested_action="click_link", asks_for=["personal_information"]),
            ],
            "B": [
                _frame("{brand} spotted a login <PERSON> does not usually make. Review the session {deadline}: <URL_1>", A, "typosquat", "new_device", threat="account_lock", requested_action="verify_account", asks_for=["login"]),
                _frame("Reset link for {brand} is live. Shut it down if you did not request one: <URL_1>", S, "homoglyph", "password_reset", threat="account_lock", requested_action="click_link", asks_for=["password"]),
                _frame("{brand}: to stop the number port, send us the code and then confirm at <URL_1>", N, "URL shortener", "otp_reply", threat="account_lock", requested_action="reply_with_code", asks_for=["one_time_code"]),
                _frame("{brand} will erase the profile {deadline} over a failed check. Appeal form <URL_1>", E, "fresh registration", "disable", threat="account_deletion", requested_action="click_link_and_verify", asks_for=["personal_information"]),
            ],
        },
        "toll_government": {
            "A": [
                _frame("{brand}: unpaid toll {amount} plus a late fee. Pay before {deadline} or the bill goes to collections. <URL_1>", A, "typosquat", "unpaid_toll", threat="legal_action", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand} toll invoice for <PERSON> is open. Amount {amount}. Portal <URL_1>", S, "homoglyph", "invoice", threat="payment_penalty", requested_action="make_payment", asks_for=["payment"]),
                _frame("Tax refund of {amount} is on hold at {brand}. Claim by {deadline}: <URL_1>", N, "subdomain abuse", "tax_refund", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand}: license suspension starts {deadline} over {amount}. Hearing link <URL_1>", E, "URL shortener", "license", threat="legal_action", requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} benefits deposit of {amount} failed verification. Confirm <URL_1>", A, "fresh registration", "benefits", threat="payment_penalty", requested_action="verify_account", asks_for=["account_details"]),
                _frame("Court fine {amount} ({brand}). Pay {deadline} to avoid a warrant notice. <URL_1>", S, "typosquat", "fine", threat="legal_action", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand} DMV copy: registration for <PERSON> lapses {deadline}. Renew <URL_1>", N, "homoglyph", "registration", threat="legal_action", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("Toll camera {brand} captured a plate. Fee {amount} is ready: <URL_1>", E, "subdomain abuse", "camera", threat="payment_penalty", requested_action="make_payment", asks_for=["card_details"]),
            ],
            "B": [
                _frame("A {brand} toll posted for {amount}. The courtesy window ends {deadline}. Pay at <URL_1>", A, "typosquat", "unpaid_toll", threat="payment_penalty", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand} has a refund of {amount} under <PERSON>. Identity step: <URL_1>", S, "homoglyph", "tax_refund", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Suspension warning ({brand}). Registration fee {amount} due {deadline}. <URL_1>", N, "URL shortener", "license", threat="legal_action", requested_action="click_link_and_pay", asks_for=["payment"]),
                _frame("{brand} notice: a civil fee of {amount} is in queue. Review the docket copy <URL_1>", E, "fresh registration", "fine", threat="legal_action", requested_action="click_link", asks_for=["personal_information"]),
            ],
        },
        "prize_refund": {
            "A": [
                _frame("{brand}: <PERSON> was picked for a {amount} reward. Claim it {deadline} at <URL_1>", A, "typosquat", "prize", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Points at {brand} worth {amount} expire {deadline}. Redeem: <URL_1>", S, "homoglyph", "points", threat="payment_penalty", requested_action="click_link", asks_for=["login"]),
                _frame("{brand} gift card of {amount} is ready after a two-question form. <URL_1>", N, "subdomain abuse", "gift_card", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Unclaimed refund {amount} from {brand}. Last day {deadline}: <URL_1>", E, "URL shortener", "refund", threat=None, requested_action="click_link", asks_for=["account_details"]),
                _frame("{brand} loyalty bonus posted. Move {amount} to a card here <URL_1>", A, "fresh registration", "bonus", threat=None, requested_action="click_link_and_verify", asks_for=["card_details"]),
                _frame("Winner desk, {brand}. <PERSON> must confirm shipping {deadline} or the prize is released. <URL_1>", S, "typosquat", "shipping", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand}: survey finished. The {amount} card code is behind <URL_1>", N, "homoglyph", "survey", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Rebate of {amount} approved by {brand}. Choose direct deposit: <URL_1>", E, "subdomain abuse", "rebate", threat=None, requested_action="click_link", asks_for=["account_details"]),
            ],
            "B": [
                _frame("Good news from {brand}. A drawing left {amount} in <PERSON>'s name until {deadline}. <URL_1>", A, "typosquat", "prize", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} rewards lapse {deadline}. Cash-out page for {amount}: <URL_1>", S, "homoglyph", "points", threat="payment_penalty", requested_action="click_link", asks_for=["login"]),
                _frame("{brand} stored a {amount} return that was never sent. Deposit choice <URL_1>", N, "URL shortener", "refund", threat=None, requested_action="click_link", asks_for=["account_details"]),
                _frame("Your {brand} bonus code for {amount} is unlocked {deadline}. Open <URL_1>", E, "fresh registration", "bonus", threat=None, requested_action="click_link", asks_for=["card_details"]),
            ],
        },
        "job_offer": {
            "A": [
                _frame("{brand}: paid remote tasks, {amount} a day. <PERSON> can start {deadline}. Details <URL_1>", A, "typosquat", "task_job", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Recruiter at {brand}. Continue the hiring chat off SMS: <URL_1> (today only, {deadline})", S, "homoglyph", "chat_app", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} pays {amount} per review. The kit ships after you enroll at <URL_1>", N, "subdomain abuse", "review_job", threat=None, requested_action="click_link", asks_for=["account_details"]),
                _frame("Investment seat at {brand} for {amount}. Read the sheet before {deadline}: <URL_1>", E, "URL shortener", "investment", threat=None, requested_action="click_link", asks_for=["payment"]),
                _frame("{brand} mystery shop: buy then expense {amount}. Sign the form <URL_1>", A, "fresh registration", "mystery_shop", threat=None, requested_action="click_link", asks_for=["payment"]),
                _frame("Hello <PERSON>, {brand} has a reship role. Equipment list is at <URL_1>", S, "typosquat", "reship", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} payroll onboarding needs a deposit sample of {amount}. Portal <URL_1>", N, "homoglyph", "onboarding", threat=None, requested_action="click_link", asks_for=["account_details"]),
                _frame("Daily pay from {brand} starts {deadline} once <PERSON> accepts. <URL_1>", E, "subdomain abuse", "daily_pay", threat=None, requested_action="click_link", asks_for=["personal_information"]),
            ],
            "B": [
                _frame("{brand} is hiring for evening tasks paid at {amount}. The post closes {deadline}: <URL_1>", A, "typosquat", "task_job", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("A {brand} sourcer wants to move this thread. Join here <URL_1>", S, "homoglyph", "chat_app", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("{brand} will reimburse a starter purchase of {amount} after the trial. Opt in <URL_1>", N, "URL shortener", "mystery_shop", threat=None, requested_action="click_link", asks_for=["payment"]),
                _frame("Offer letter host ({brand}). <PERSON>, read it before {deadline}. <URL_1>", E, "fresh registration", "onboarding", threat=None, requested_action="click_link", asks_for=["account_details"]),
            ],
        },
        "conversation_lure": {
            "A": [
                _frame("Hey, is this <PERSON>? I think I have the wrong number, sorry.", A, None, "wrong_number", threat=None, requested_action=None, asks_for=[]),
                _frame("It's <PERSON>. New number. Can you send {amount} for the deposit, I get paid {deadline}? <URL_1>", S, "typosquat", "relative", threat=None, requested_action="make_payment", asks_for=["payment"]),
                _frame("<PERSON> here, phone broke. Stuck and need {amount} tonight. I can pay you back. <URL_1>", N, "homoglyph", "stuck", threat=None, requested_action="make_payment", asks_for=["payment"]),
                _frame("Hi <PERSON>, long time. I am nearby {deadline} and would love to say hello. <URL_1>", E, "URL shortener", "romance", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Wrong number maybe, but you seem kind. Save me? It's <PERSON>.", A, None, "wrong_number_soft", threat=None, requested_action=None, asks_for=[]),
                _frame("<PERSON> from the old building. I changed phones. Are you still at the same place? <URL_1>", S, "fresh registration", "acquaintance", threat=None, requested_action="click_link", asks_for=["personal_information"]),
                _frame("Mom's phone died. This is <PERSON> texting for her. She needs {amount} for the pharmacy {deadline}.", N, None, "family_money", threat=None, requested_action="make_payment", asks_for=["payment"]),
                _frame("Hey it's <PERSON>, traveling and the card failed. Can you cover {amount}? I'll zelle back. <URL_1>", E, "subdomain abuse", "travel", threat=None, requested_action="make_payment", asks_for=["payment"]),
            ],
            "B": [
                _frame("Sorry <PERSON>, I was trying to reach my cousin. Did I miss a digit?", A, None, "wrong_number", threat=None, requested_action=None, asks_for=[]),
                _frame("This is <PERSON> on a borrowed phone. The fare is {amount} and I am short. <URL_1>", S, "typosquat", "relative", threat=None, requested_action="make_payment", asks_for=["payment"]),
                _frame("<PERSON> from college. My flight voucher is stuck, {amount}, can you look at <URL_1> {deadline}?", N, "homoglyph", "stuck", threat=None, requested_action="click_link", asks_for=["payment"]),
                _frame("Hi, <PERSON> gave me your number years ago. I am in town {deadline}. Photo: <URL_1>", E, "fresh registration", "romance", threat=None, requested_action="click_link", asks_for=["personal_information"]),
            ],
        },
        "legit": {
            "A": [
                _frame("{brand}: your bill of {amount} is ready. Autopay runs on the due date. View it at <URL_1>", S, None, "carrier_bill", threat=None, requested_action="open_official_app", asks_for=[]),
                _frame("{brand} autopay confirmation. We will draft {amount} for the mobile bill. No reply is needed.", S, None, "carrier_autopay", threat=None, requested_action=None, asks_for=[]),
                _frame("{brand}: your sign-in code is <ACCOUNT_DIGITS>. {brand} will never ask you to share this code.", S, None, "otp", threat=None, requested_action=None, asks_for=[]),
                _frame("Use <ACCOUNT_DIGITS> to finish signing in to {brand}. If you did not ask for a code, ignore this text.", A, None, "otp_warning", threat=None, requested_action=None, asks_for=[]),
                _frame("{brand}: your package is out for delivery today. Track it at <URL_1>", S, None, "delivery", threat=None, requested_action="open_official_app", asks_for=[]),
                _frame("{brand}: shipped. Estimated arrival {deadline}. Details at <URL_1>", N, None, "delivery_shipped", threat=None, requested_action=None, asks_for=[]),
                _frame("{brand}: did you send {amount}? Reply YES or NO. We will not ask you to tap a link.", S, None, "bank_yes_no", threat=None, requested_action="reply", asks_for=[]),
                _frame("{brand}: toll balance replenished by {amount}. Statement: <URL_1>", E, None, "toll_statement", threat=None, requested_action="open_official_app", asks_for=[]),
            ],
            "B": [
                _frame("Reminder from {brand}. The {amount} bill posts {deadline}. You are enrolled in autopay. Details: <URL_1>", S, None, "carrier_bill", threat=None, requested_action="open_official_app", asks_for=[]),
                _frame("{brand} security code <ACCOUNT_DIGITS>. Do not tell anyone this code, including someone who claims to work here.", A, None, "otp", threat=None, requested_action=None, asks_for=[]),
                _frame("Update from {brand}: the driver is two stops away. Follow the map at <URL_1>", S, None, "delivery", threat=None, requested_action="open_official_app", asks_for=[]),
                _frame("{brand} account note: a debit of {amount} posted. Open the official app to see it. This text has no link.", N, None, "bank_posted", threat=None, requested_action="open_official_app", asks_for=[]),
            ],
        },
    }
    return frames


FRAMES = _load_frames()

CAMP_FRAMES = [
    "{brand}: payment of {amount} did not clear. Fix it within {deadline} at <URL_1>.",
    "{brand} notice. {amount} is past due and service pauses {deadline}. Use <URL_1>.",
    "Action for {brand}: {amount} needs a card update {deadline}. <URL_1>",
    "{brand} account alert for <PERSON>. Review {amount} here <URL_1> ({deadline}).",
    "Reminder ({brand}). The {amount} step closes {deadline}. Open <URL_1>.",
    "{brand} desk: we still show {amount} open. Resolve {deadline}: <URL_1>",
    "Quick note from {brand}. {amount} / due {deadline}. Link <URL_1>",
    "{brand} case for <PERSON> includes {amount}. Respond {deadline} via <URL_1>",
    "Do this today, {brand} says. {amount} by {deadline}. <URL_1>",
    "{brand}: hold placed around {amount}. Release form <URL_1> ({deadline})",
    "Billing copy, {brand}. Amount {amount}. Window ends {deadline}. <URL_1>",
    "{brand} verification on a {amount} item expires {deadline}. <URL_1>",
    "Please look, {brand} flagged {amount} for <PERSON>. {deadline}: <URL_1>",
    "{brand} follow-up. Nothing posted for {amount}. Try <URL_1> before {deadline}",
    "Last ping from {brand} about {amount}. {deadline} remains. <URL_1>",
]


def skeleton(frame: str) -> str:
    text = frame
    for token in ("{brand}", "{amount}", "{deadline}", "<URL_1>", "<PERSON>", "<ACCOUNT_DIGITS>"):
        text = text.replace(token, " ")
    text = text.lower()
    text = re.sub(r"[^a-z ]+", " ", text)
    return " ".join(text.split())


def e164(line: int) -> str:
    """``line`` is 100–199, meaning fictional numbers 555-0100 through 555-0199."""
    if not 100 <= line <= 199:
        raise ValueError(line)
    return f"+1555555{line:04d}"


def phone_hash(number: str) -> str:
    digest = hashlib.sha256(f"sentinel-synthetic:{SEED}:{number}".encode()).hexdigest()[:8]
    return f"<PHONE_HASH_{digest}>"


def to_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_z(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso_central(moment: datetime) -> str:
    return moment.astimezone(CENTRAL).isoformat(timespec="seconds")


def homoglyph(slug: str) -> str:
    table = {"o": "ο", "a": "а", "e": "е", "i": "і", "s": "ѕ"}
    for char, replacement in table.items():
        if char in slug:
            return slug.replace(char, replacement, 1)
    return "ı" + slug


def _sender(set_name: str, kind: str, category: str, index: int) -> dict[str, Any]:
    if kind == "long_code":
        pool = {"A": LINES_A, "B": LINES_B, "C": LINES_CAMP, "SA": LINES_SCN_A, "SB": LINES_SCN_B}[set_name]
        number = e164(pool[index % len(pool)])
        return {"type": "long_code", "value": phone_hash(number), "raw": number}
    if kind == "short_code":
        base = {"A": 56000, "B": 56400, "C": 57000, "SA": 58000, "SB": 58400}[set_name]
        return {"type": "short_code", "value": str(base + index), "raw": str(base + index)}
    if kind == "alphanumeric":
        prefix = {"A": "IDA", "B": "IDB", "C": "IDC", "SA": "ISA", "SB": "ISB"}[set_name]
        value = f"{prefix}{category[:4].upper()}{index:02d}"
        return {"type": "alphanumeric", "value": value, "raw": value}
    local = {"A": "a", "B": "b", "C": "c", "SA": "sa", "SB": "sb"}[set_name]
    host = {"A": "notice.example", "B": "alert.example", "C": "camp.example", "SA": "scn-a.example", "SB": "scn-b.example"}[set_name]
    value = f"{local}{index:02d}-{category[:4]}@{host}"
    return {"type": "email", "value": value, "raw": value}


def _fill(frame: str, brand: str, amount: int, deadline: str) -> str:
    return (
        frame.replace("{brand}", brand)
        .replace("{amount}", f"${amount}")
        .replace("{deadline}", deadline)
    )


def _features(frame: dict[str, Any], amount: int, deadline: str) -> dict[str, Any]:
    raw = frame["features"]
    money = float(amount) if "{amount}" in frame["text"] else None
    urgency = deadline if "{deadline}" in frame["text"] else None
    return {
        "urgency_deadline": raw.get("urgency_deadline", urgency),
        "threat": raw.get("threat"),
        "requested_action": raw.get("requested_action"),
        "asks_for": list(raw.get("asks_for") or []),
        "money_amount_claimed": money,
    }


def _classifier(category: str, score: float) -> dict[str, Any]:
    others = [item for item in TAXONOMY if item != category]
    top3 = [[category, score], [others[0], 0.04], [others[1], 0.02]]
    return {
        "category": category,
        "score": score,
        "top3": top3,
        "baseline_score": round(score - 0.11, 2),
    }


def _link(set_name: str, category: str, index: int, technique: str | None, brand: tuple[str, str, str]) -> dict[str, Any] | None:
    display, slug, typo = brand
    if technique is None:
        if "<URL_1>" not in FRAMES[category][set_name][index]["text"]:
            return None
        domain = f"{slug}.example"
        url = f"https://{domain}/account"
        return {
            "url": url,
            "host": domain,
            "registered_domain": domain,
            "technique": None,
            "label": "legit",
            "is_shortener": False,
            "brand_term": None,
            "official": True,
            "lookalike_of": LOOKALIKE_OF.get(display),
        }
    token = f"{set_name.lower()}-{category[:4]}-{index}"
    if technique == "typosquat":
        domain = f"{typo}-{token}.test"
        host, registered, url = domain, domain, f"https://{domain}/pay"
    elif technique == "homoglyph":
        domain = f"{homoglyph(slug)}-{token}.test"
        host, registered, url = domain, domain, f"https://{domain}/pay"
    elif technique == "subdomain abuse":
        registered = f"{token}.test"
        host = f"{slug}.{registered}"
        domain = registered
        url = f"https://{host}/pay"
    elif technique == "URL shortener":
        registered = f"short-{set_name.lower()}.test"
        host = registered
        domain = registered
        url = f"https://{registered}/{token}"
    else:
        domain = f"new-{typo}-{token}.test"
        host, registered, url = domain, domain, f"https://{domain}/start"
    term = None
    if technique in {"typosquat", "subdomain abuse"}:
        term = slug
    return {
        "url": url,
        "host": host,
        "registered_domain": registered,
        "technique": technique,
        "label": "phishing",
        "is_shortener": technique == "URL shortener",
        "brand_term": term,
        "official": False,
        "lookalike_of": LOOKALIKE_OF.get(display),
    }


def _message_record(
    *,
    message_id: str,
    category: str,
    set_name: str,
    split: str,
    template_id: str,
    frame: dict[str, Any],
    brand: tuple[str, str, str],
    link: dict[str, Any] | None,
    sender: dict[str, Any],
    amount: int,
    deadline: str,
    received: datetime,
    score: float,
) -> dict[str, Any]:
    text = _fill(frame["text"], brand[0], amount, deadline)
    if link is None and "<URL_1>" in text:
        raise RuntimeError(f"{template_id} has a URL slot but no link")
    if link is not None and "<URL_1>" not in text:
        raise RuntimeError(f"{template_id} has a link but the text has no URL slot")
    urls = []
    if link is not None:
        urls.append(
            {
                "id": "URL_1",
                "registered_domain": link["registered_domain"],
                "is_shortener": link["is_shortener"],
                "brand_term_in_domain": link["brand_term"],
                "is_official_brand_domain": link["official"],
            }
        )
    claimed = None if category == "conversation_lure" else brand[0]
    return {
        "message_id": message_id,
        "mode": "check",
        "received_at": iso_central(received),
        "sender": {"type": sender["type"], "value": sender["value"], "claimed_brand": claimed},
        "text_redacted": text,
        "urls": urls,
        "features": _features(frame, amount, deadline),
        "classifier": _classifier(category, score),
        "customer_context": {
            "linked_bank": category != "conversation_lure",
            "linked_institutions": ["Harbor Mutual"],
        },
        "taxonomy_id": category,
        "is_scam": category != "legit",
        "template_id": template_id,
        "template_set": set_name,
        "template_skeleton": skeleton(frame["text"]),
        "split": split,
        "subtype": frame["subtype"],
        "source_url": None if link is None else link["url"],
        "source_host": None if link is None else link["host"],
        "link_technique": None if link is None else link["technique"],
        "link_label": None if link is None else link["label"],
        "lookalike_of": None if link is None else link["lookalike_of"],
    }


def _legit_brand(set_name: str, subtype: str) -> tuple[str, str, str]:
    brands = BRANDS["legit"][set_name]
    if subtype.startswith("delivery"):
        return brands[1]
    if subtype.startswith("bank"):
        return brands[2]
    if subtype.startswith("toll"):
        return brands[3]
    return brands[0]


def build_messages() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in TAXONOMY:
        for set_name, count, split_of in (
            ("A", COUNT_A, lambda n: "train" if n < TRAIN_N else "validation"),
            ("B", COUNT_B, lambda n: "test"),
        ):
            bank = FRAMES[category][set_name]
            for n in range(count):
                frame = bank[n % len(bank)]
                pattern = n % len(bank)
                if category == "legit":
                    brand = _legit_brand(set_name, frame["subtype"])
                else:
                    brand = BRANDS[category][set_name][pattern % len(BRANDS[category][set_name])]
                amount = AMOUNTS[n % len(AMOUNTS)]
                deadline = DEADLINES[n % len(DEADLINES)]
                rng = random.Random(f"{SEED}:when:{set_name}:{category}:{n}")
                received = datetime(2026, 9, 1, tzinfo=CENTRAL) + timedelta(days=rng.randrange(60))
                received = received.replace(hour=8 + rng.randrange(12), minute=rng.randrange(60))
                link = _link(set_name, category, pattern, frame["technique"], brand)
                sender = _sender(set_name, frame["sender"], category, pattern)
                score = 0.9 if category == "legit" else 0.86
                rows.append(
                    _message_record(
                        message_id=f"mc_{set_name}_{category}_{n:04d}",
                        category=category,
                        set_name=set_name,
                        split=split_of(n),
                        template_id=f"tmpl_{set_name}_{category}_{pattern:02d}",
                        frame=frame,
                        brand=brand,
                        link=link,
                        sender=sender,
                        amount=amount,
                        deadline=deadline,
                        received=received,
                        score=score,
                    )
                )
    return rows


def _camp_domain(camp_index: int, variant: int, technique: str, slug: str) -> dict[str, Any]:
    # The brief's example lookalike. T-Mobile's first variant uses it; campaign 0 is a bank.
    if slug == "tmobile" and variant == 0:
        domain = "tm0bile-billing.test"
        return {"url": f"https://{domain}/pay", "host": domain, "registered_domain": domain, "technique": "typosquat"}
    token = f"c{camp_index:02d}v{variant:02d}"
    if technique == "typosquat":
        domain = f"{slug}-{token}.test"
        return {"url": f"https://{domain}/go", "host": domain, "registered_domain": domain, "technique": technique}
    if technique == "homoglyph":
        domain = f"{homoglyph(slug)}-{token}.test"
        return {"url": f"https://{domain}/go", "host": domain, "registered_domain": domain, "technique": technique}
    if technique == "subdomain abuse":
        registered = f"pay-{token}.test"
        host = f"{slug}.{registered}"
        return {"url": f"https://{host}/go", "host": host, "registered_domain": registered, "technique": technique}
    if technique == "URL shortener":
        registered = "short-c.test"
        return {"url": f"https://{registered}/{token}", "host": registered, "registered_domain": registered, "technique": technique}
    domain = f"fresh-{slug}-{token}.test"
    return {"url": f"https://{domain}/go", "host": domain, "registered_domain": domain, "technique": "fresh registration"}


def build_campaigns() -> list[dict[str, Any]]:
    techs = ["typosquat", "homoglyph", "subdomain abuse", "URL shortener", "fresh registration"]
    kinds = ["long_code", "short_code", "alphanumeric", "email"]
    rows: list[dict[str, Any]] = []
    camp_index = 0
    for category in SCAM_TAXONOMY:
        for brand_name in CAMP_BRANDS[category]:
            variant_count = 5 + (camp_index % 11)  # 5..15
            campaign_id = f"camp_{camp_index + 1:03d}"
            template_id = f"camp_tmpl_{camp_index + 1:03d}"
            slug = re.sub(r"[^a-z0-9]+", "", brand_name.lower())[:12] or "brand"
            for variant in range(variant_count):
                technique = techs[variant % len(techs)]
                kind = kinds[variant % len(kinds)]
                sender = _sender("C", kind, category, camp_index * 20 + variant)
                amount = AMOUNTS[variant % len(AMOUNTS)]
                deadline = DEADLINES[variant % len(DEADLINES)]
                text = _fill(CAMP_FRAMES[variant], brand_name, amount, deadline)
                link = _camp_domain(camp_index, variant, technique, slug)
                rows.append(
                    {
                        "campaign_id": campaign_id,
                        "taxonomy_id": category,
                        "variant_index": variant,
                        "variant_count": variant_count,
                        "template_id": template_id,
                        "template_set": "A",
                        "template_skeleton": skeleton(CAMP_FRAMES[variant]),
                        "sender": {"type": sender["type"], "value": sender["value"], "claimed_brand": None if category == "conversation_lure" else brand_name},
                        "text_redacted": text,
                        "url": link["url"],
                        "domain": link["registered_domain"],
                        "host": link["host"],
                        "technique": link["technique"],
                        "lookalike_of": LOOKALIKE_OF.get(brand_name),
                        "amount": amount,
                    }
                )
            camp_index += 1
    if camp_index < 30:
        raise RuntimeError(f"expected at least 30 campaigns, built {camp_index}")
    return rows


def _device(customer_id: str, new: bool = False, os_name: str = "ios") -> dict[str, Any]:
    return {
        "device_id": f"dev_{customer_id}",
        "new_device": new,
        "os": os_name,
        "ip_geo": {"country": "US", "region": "TX"},
        "session_id": f"ses_{customer_id}",
    }


def _auth(method: str = "biometric", otp: bool = False, success: bool = True) -> dict[str, Any]:
    return {"method": method, "otp_sent": otp, "success": success}


def _labels(is_fraud: bool, fraud_type: str | None, message_id: str | None) -> dict[str, Any]:
    return {
        "is_fraud": is_fraud,
        "fraud_type": fraud_type if is_fraud else None,
        "linked_message_id": message_id if is_fraud else None,
    }


class _Ledger:
    def __init__(self, scenario_index: int, customer_id: str) -> None:
        self.scenario_index = scenario_index
        self.customer_id = customer_id
        self.n = 0
        self.balance = {"checking": 420_000, "credit_card": 64_000, "carrier_account": 0, "savings": 80_000}

    def event(self, when: datetime, **fields: Any) -> dict[str, Any]:
        account_type = fields["account_type"]
        amount = int(fields["amount_minor"])
        direction = fields["direction"]
        if account_type == "credit_card" and direction == "debit":
            self.balance[account_type] += amount
        elif direction == "debit":
            self.balance[account_type] = self.balance.get(account_type, 0) - amount
        elif direction == "credit":
            self.balance[account_type] = self.balance.get(account_type, 0) + amount
        event_id = f"evt_{self.scenario_index:04d}_{self.n:03d}"
        self.n += 1
        bill = fields.get("bill")
        return {
            "event_id": event_id,
            "event_type": fields["event_type"],
            "timestamp": to_z(when),
            "customer_id": self.customer_id,
            "account_id": fields["account_id"],
            "account_type": account_type,
            "counterparty_id": fields.get("counterparty_id"),
            "counterparty_name": fields.get("counterparty_name"),
            "counterparty_type": fields.get("counterparty_type"),
            "counterparty_first_seen": fields.get("counterparty_first_seen"),
            "amount_minor": amount,
            "currency": "USD",
            "direction": direction,
            "channel": fields["channel"],
            "merchant_category": fields.get("merchant_category"),
            "recurring": bool(fields.get("recurring", False)),
            "recurrence_id": fields.get("recurrence_id"),
            "bill": bill,
            "device": fields.get("device") or _device(self.customer_id),
            "auth": fields.get("auth") or _auth(),
            "status": fields.get("status", "completed"),
            "balance_after_minor": self.balance.get(account_type),
            "source_system": "synthetic",
            "source_ref": event_id,
            "labels": fields["labels"],
        }


def _party(kind: str) -> tuple[str, str, str, str | None]:
    table = {
        "grocery": ("mer_grocery", "Demo Grocery", "merchant", "5411"),
        "coffee": ("mer_coffee", "Demo Coffee", "merchant", "5814"),
        "fuel": ("mer_fuel", "Demo Fuel", "merchant", "5541"),
        "northline": ("biller_northline", KNOWN_BILLER, "biller", "4814"),
        "unknown": ("mer_unknown_payee", UNKNOWN_PAYEE, "unknown", "4829"),
        "parcel": ("mer_parcel_hold", "Parcel Hold Desk", "merchant", "4215"),
        "toll": ("biller_cedar_collections", "Cedar Toll Collections", "biller", "4784"),
        "refund": ("mer_refund_desk", "Refund Desk", "unknown", "4829"),
        "job_in": ("mer_fieldstone_payroll", "Fieldstone Payroll", "person", "7399"),
        "job_out": ("mer_task_wallet", "Task Wallet", "unknown", "4829"),
        "prize": ("mer_reward_kiosk", "Reward Kiosk", "merchant", "5947"),
        "harbor_payee": ("mer_harbor_payee", "Harbor Payee", "person", "4829"),
        "port": ("mer_port_desk", "Port Desk", "unknown", "4829"),
    }
    return table[kind]


def _bill_obj(scenario_index: int, suffix: str, payee_id: str, status: str, amount: int, due: str, autopay: bool) -> dict[str, Any]:
    return {
        "biller_id": payee_id,
        "bill_id": f"bill_{scenario_index:04d}_{suffix}",
        "due_date": due,
        "status": status,
        "autopay": autopay,
        "amount_due_minor": amount,
    }


def _baseline(ledger: _Ledger, message_at: datetime, scenario_index: int, accounts: dict[str, str]) -> list[dict[str, Any]]:
    days = 30 + (scenario_index % 31)
    # Hour 12 is after the 09:14 message clock, so step back one extra day
    # and the covered span stays inside 30–60 days.
    start = (message_at - timedelta(days=days + 1)).replace(hour=12, minute=0, second=0, microsecond=0)
    grocery = [6400, 5800, 7100, 4900]
    coffee = [550, 640, 600]
    fuel = [4200, 3900, 4500]
    events: list[dict[str, Any]] = []
    labels = _labels(False, None, None)
    device = _device(ledger.customer_id)
    for day in range(days):
        moment = start + timedelta(days=day)
        if moment >= message_at:
            break
        if day % 4 == 0:
            pid, name, ptype, mcc = _party("grocery")
            events.append(ledger.event(moment, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=False, amount_minor=grocery[day % 4], direction="debit", channel="card_present", merchant_category=mcc, device=device, labels=labels))
        if day % 3 == 1:
            moment = moment.replace(hour=8)
            pid, name, ptype, mcc = _party("coffee")
            events.append(ledger.event(moment, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=False, amount_minor=coffee[day % 3], direction="debit", channel="card_present", merchant_category=mcc, device=device, labels=labels))
        if day % 7 == 2:
            moment = moment.replace(hour=18)
            pid, name, ptype, mcc = _party("fuel")
            events.append(ledger.event(moment, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=False, amount_minor=fuel[day % 3], direction="debit", channel="card_present", merchant_category=mcc, device=device, labels=labels))
        if day == 3:
            pid, name, ptype, mcc = _party("northline")
            due = (moment + timedelta(days=9)).date().isoformat()
            events.append(ledger.event(moment.replace(hour=9), event_type="bill_issued", account_id=accounts["checking"], account_type="checking", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=False, amount_minor=8640, direction="none", channel="bill_pay", merchant_category=mcc, recurring=True, recurrence_id=f"rec_{ledger.customer_id}_nl", bill=_bill_obj(scenario_index, "issued", pid, "pending", 8640, due, True), device=device, labels=labels))
        if day == 6:
            events.append(ledger.event(moment.replace(hour=11), event_type="plan_change", account_id=accounts["carrier"], account_type="carrier_account", counterparty_id="biller_northline", counterparty_name=KNOWN_BILLER, counterparty_type="biller", counterparty_first_seen=False, amount_minor=0, direction="none", channel="carrier_billing", merchant_category="4814", device=device, auth=_auth("password"), labels=labels))
        if day == 9:
            events.append(ledger.event(moment.replace(hour=11, minute=5), event_type="bill_amount_change", account_id=accounts["carrier"], account_type="carrier_account", counterparty_id="biller_northline", counterparty_name=KNOWN_BILLER, counterparty_type="biller", counterparty_first_seen=False, amount_minor=8640, direction="none", channel="carrier_billing", merchant_category="4814", recurring=True, recurrence_id=f"rec_{ledger.customer_id}_nl", bill=_bill_obj(scenario_index, "amt", "biller_northline", "pending", 8640, moment.date().isoformat(), True), device=device, labels=labels))
        if day == 11:
            if scenario_index % 2 == 0:
                events.append(ledger.event(moment.replace(hour=15), event_type="autopay_change", account_id=accounts["checking"], account_type="checking", counterparty_id="biller_northline", counterparty_name=KNOWN_BILLER, counterparty_type="biller", counterparty_first_seen=False, amount_minor=0, direction="none", channel="bill_pay", merchant_category="4814", device=device, labels=labels))
            else:
                old = _device(ledger.customer_id, new=False)
                events.append(ledger.event(moment.replace(hour=15), event_type="device_add", account_id=accounts["checking"], account_type="checking", counterparty_id=None, counterparty_name=None, counterparty_type=None, counterparty_first_seen=None, amount_minor=0, direction="none", channel="carrier_billing", merchant_category=None, device=old, labels=labels))
        if day == 14:
            events.append(ledger.event(moment.replace(hour=16), event_type="withdrawal", account_id=accounts["checking"], account_type="checking", counterparty_id="bank_demo_atm", counterparty_name="Demo ATM", counterparty_type="bank", counterparty_first_seen=False, amount_minor=4000, direction="debit", channel="atm", merchant_category="6011", device=device, labels=labels))
        if day == 16:
            pid, name, ptype, mcc = _party("northline")
            due = moment.date().isoformat()
            events.append(ledger.event(moment.replace(hour=10), event_type="bill_payment", account_id=accounts["checking"], account_type="checking", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=False, amount_minor=8640, direction="debit", channel="bill_pay", merchant_category=mcc, recurring=True, recurrence_id=f"rec_{ledger.customer_id}_nl", bill=_bill_obj(scenario_index, "paidbase", pid, "paid", 8640, due, True), device=device, labels=labels))
        if day == 20:
            events.append(ledger.event(moment.replace(hour=7, minute=40), event_type="login", account_id=accounts["checking"], account_type="checking", counterparty_id=None, counterparty_name=None, counterparty_type=None, counterparty_first_seen=None, amount_minor=0, direction="none", channel="carrier_billing", merchant_category=None, device=device, auth=_auth("biometric"), labels=labels))
    if not events:
        raise RuntimeError("baseline produced no events")
    span = (message_at - start).days
    if span < 30 or span > 60:
        raise RuntimeError(f"baseline span {span} days is outside 30-60")
    return events


def _debit(ledger: _Ledger, when: datetime, party: str, amount: int, *, event_type: str, account_id: str, account_type: str, channel: str, first_seen: bool, fraud: bool, fraud_type: str, message_id: str, bill: dict | None = None, device: dict | None = None, auth: dict | None = None, recurring: bool = False) -> dict[str, Any]:
    pid, name, ptype, mcc = _party(party)
    return ledger.event(
        when,
        event_type=event_type,
        account_id=account_id,
        account_type=account_type,
        counterparty_id=pid,
        counterparty_name=name,
        counterparty_type=ptype,
        counterparty_first_seen=first_seen,
        amount_minor=amount,
        direction="debit" if event_type != "deposit" else "credit",
        channel=channel,
        merchant_category=mcc,
        recurring=recurring,
        recurrence_id=f"rec_{ledger.customer_id}_nl" if recurring else None,
        bill=bill,
        device=device,
        auth=auth,
        labels=_labels(fraud, fraud_type, message_id),
    )


def _post(kind: str, ledger: _Ledger, message_at: datetime, scenario_index: int, accounts: dict[str, str], message_id: str, fraud_type: str) -> list[dict[str, Any]]:
    fraud = True
    out: list[dict[str, Any]] = []
    if kind == "billing_unknown_payee":
        pid, name, ptype, mcc = _party("unknown")
        out.append(ledger.event(message_at + timedelta(minutes=6), event_type="payee_added", account_id=accounts["checking"], account_type="checking", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=True, amount_minor=0, direction="none", channel="bill_pay", merchant_category=mcc, labels=_labels(True, fraud_type, message_id)))
        due = message_at.date().isoformat()
        out.append(_debit(ledger, message_at + timedelta(minutes=12), "unknown", 90_000, event_type="bill_payment", account_id=accounts["checking"], account_type="checking", channel="bill_pay", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id, bill=_bill_obj(scenario_index, "unk", pid, "paid", 90_000, due, False)))
    elif kind == "delivery_cnp":
        out.append(_debit(ledger, message_at + timedelta(minutes=18), "parcel", 38_900, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", channel="card_not_present", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id))
    elif kind == "carrier_takeover":
        sim_type = ["sim_change", "esim_transfer", "port_out_request"][scenario_index % 3]
        new_dev = _device(ledger.customer_id + "_new", new=True, os_name="android")
        out.append(ledger.event(message_at + timedelta(minutes=7), event_type="device_add", account_id=accounts["carrier"], account_type="carrier_account", counterparty_id=None, counterparty_name=None, counterparty_type=None, counterparty_first_seen=None, amount_minor=0, direction="none", channel="carrier_billing", merchant_category=None, device=new_dev, auth=_auth("otp", otp=True), labels=_labels(True, fraud_type, message_id)))
        out.append(ledger.event(message_at + timedelta(minutes=8), event_type=sim_type, account_id=accounts["carrier"], account_type="carrier_account", counterparty_id="dealer_example", counterparty_name="Example Dealer", counterparty_type="biller", counterparty_first_seen=True, amount_minor=0, direction="none", channel="carrier_billing", merchant_category="4814", device=new_dev, auth=_auth("otp", otp=True), labels=_labels(True, fraud_type, message_id)))
        out.append(ledger.event(message_at + timedelta(minutes=12), event_type="password_reset", account_id=accounts["checking"], account_type="checking", counterparty_id=None, counterparty_name=None, counterparty_type=None, counterparty_first_seen=None, amount_minor=0, direction="none", channel="carrier_billing", merchant_category=None, device=new_dev, auth=_auth("password", otp=True, success=True), labels=_labels(True, fraud_type, message_id)))
        out.append(_debit(ledger, message_at + timedelta(minutes=20), "port", 250_000, event_type="transfer_out", account_id=accounts["checking"], account_type="checking", channel="wire", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id, device=new_dev, auth=_auth("password", otp=True)))
    elif kind == "toll_payment":
        pid, _, _, _ = _party("toll")
        due = message_at.date().isoformat()
        out.append(_debit(ledger, message_at + timedelta(minutes=16), "toll", 1_260, event_type="bill_payment", account_id=accounts["checking"], account_type="checking", channel="bill_pay", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id, bill=_bill_obj(scenario_index, "toll", pid, "paid", 1_260, due, False)))
    elif kind == "refund_overpay":
        out.append(_debit(ledger, message_at + timedelta(minutes=15), "refund", 18_600, event_type="transfer_out", account_id=accounts["checking"], account_type="checking", channel="ach", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id))
    elif kind == "job_deposit":
        pid, name, ptype, mcc = _party("job_in")
        out.append(ledger.event(message_at + timedelta(minutes=40), event_type="deposit", account_id=accounts["checking"], account_type="checking", counterparty_id=pid, counterparty_name=name, counterparty_type=ptype, counterparty_first_seen=True, amount_minor=180_000, direction="credit", channel="ach", merchant_category=mcc, labels=_labels(True, fraud_type, message_id)))
        out.append(_debit(ledger, message_at + timedelta(minutes=70), "job_out", 180_000, event_type="transfer_out", account_id=accounts["checking"], account_type="checking", channel="wire", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id))
    elif kind == "known_biller_spike":
        pid, _, _, _ = _party("northline")
        due = message_at.date().isoformat()
        out.append(_debit(ledger, message_at + timedelta(minutes=25), "northline", 68_000, event_type="bill_payment", account_id=accounts["checking"], account_type="checking", channel="gift_card", first_seen=False, fraud=fraud, fraud_type=fraud_type, message_id=message_id, bill=_bill_obj(scenario_index, "spike", pid, "paid", 68_000, due, False)))
    elif kind == "prize_giftcard":
        out.append(_debit(ledger, message_at + timedelta(minutes=22), "prize", 25_000, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", channel="gift_card", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id))
    elif kind == "delayed_bank":
        out.append(_debit(ledger, message_at + timedelta(days=5, minutes=10), "harbor_payee", 6_000, event_type="transfer_out", account_id=accounts["checking"], account_type="checking", channel="bill_pay", first_seen=True, fraud=fraud, fraud_type=fraud_type, message_id=message_id))
    elif kind == "scary_quiet":
        out.append(_debit(ledger, message_at + timedelta(hours=30), "coffee", 600, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", channel="card_present", first_seen=False, fraud=False, fraud_type="", message_id=message_id))
    elif kind == "scary_near":
        out.append(_debit(ledger, message_at + timedelta(minutes=90), "coffee", 600, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", channel="card_present", first_seen=False, fraud=False, fraud_type="", message_id=message_id))
    elif kind == "scary_device":
        new_dev = _device(ledger.customer_id + "_phone", new=True)
        out.append(ledger.event(message_at + timedelta(minutes=20), event_type="device_add", account_id=accounts["checking"], account_type="checking", counterparty_id=None, counterparty_name=None, counterparty_type=None, counterparty_first_seen=None, amount_minor=0, direction="none", channel="carrier_billing", merchant_category=None, device=new_dev, labels=_labels(False, None, None)))
        out.append(_debit(ledger, message_at + timedelta(minutes=40), "coffee", 600, event_type="purchase", account_id=accounts["credit"], account_type="credit_card", channel="card_present", first_seen=False, fraud=False, fraud_type="", message_id=message_id, device=new_dev))
    elif kind == "legit_soon":
        pid, _, _, _ = _party("northline")
        due = message_at.date().isoformat()
        out.append(_debit(ledger, message_at + timedelta(minutes=40), "northline", 8640, event_type="bill_payment", account_id=accounts["checking"], account_type="checking", channel="bill_pay", first_seen=False, fraud=False, fraud_type="", message_id=message_id, recurring=True, bill=_bill_obj(scenario_index, "ontime", pid, "paid", 8640, due, True)))
    elif kind == "legit_later":
        pid, _, _, _ = _party("northline")
        due = (message_at + timedelta(days=1)).date().isoformat()
        out.append(_debit(ledger, message_at + timedelta(hours=26), "northline", 8640, event_type="bill_payment", account_id=accounts["checking"], account_type="checking", channel="bill_pay", first_seen=False, fraud=False, fraud_type="", message_id=message_id, recurring=True, bill=_bill_obj(scenario_index, "nextday", pid, "paid", 8640, due, True)))
    else:
        raise RuntimeError(kind)
    return out


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def compute_signals(message_at: datetime, baseline: list[dict[str, Any]], post: list[dict[str, Any]], known_payees: set[str]) -> dict[str, bool]:
    debits = [event for event in baseline if event["direction"] == "debit" and event["amount_minor"] > 0]
    median = _median([event["amount_minor"] for event in debits]) if debits else 0
    channels = {event["channel"] for event in debits}
    post_debits = [event for event in post if event["direction"] == "debit" and event["amount_minor"] > 0]
    sim_types = {"sim_change", "esim_transfer", "port_out_request", "device_add"}
    sim_times = [parse_z(event["timestamp"]) for event in post if event["event_type"] in sim_types and event["device"]["new_device"]]
    near_device = False
    for event in post_debits:
        paid_at = parse_z(event["timestamp"])
        if any(timedelta(0) <= paid_at - sim_at <= timedelta(minutes=60) for sim_at in sim_times):
            near_device = True
    return {
        "new_payee": any(event["counterparty_first_seen"] for event in post_debits) or any(event["event_type"] == "payee_added" for event in post),
        "amount_far_from_baseline": bool(median) and any(event["amount_minor"] >= 3 * median for event in post_debits),
        "channel_never_used": any(event["channel"] not in channels for event in post_debits),
        "bill_nonmatching_biller": any(event["event_type"] == "bill_payment" and event["counterparty_name"] not in known_payees for event in post),
        "new_device_or_sim_near_payment": near_device,
        "timing_near_message": any(timedelta(0) <= parse_z(event["timestamp"]) - message_at.astimezone(timezone.utc) <= timedelta(minutes=180) for event in post_debits),
    }


EXPLANATIONS = {
    "billing_unknown_payee": "A billing text was followed by a new payee named Unknown Payee and a bill payment far above the usual bill.",
    "delivery_cnp": "A delivery text was followed by a card-not-present purchase at a merchant the customer had not used.",
    "carrier_takeover": "A carrier takeover (SIM, eSIM, or port-out) was followed by a password reset and a wire out.",
    "toll_payment": "A toll text was followed by a small bill payment to a collector that is not the customer's biller.",
    "refund_overpay": "An overpayment text was followed by an outbound transfer to a new payee.",
    "job_deposit": "A job-offer text was followed by a check deposit and then an outbound transfer.",
    "known_biller_spike": "A billing text was followed by a gift-card payment to the real biller for many times the usual amount.",
    "prize_giftcard": "A prize text was followed by a gift-card purchase, a channel this customer had not used.",
    "delayed_bank": "A bank text was followed days later by a modest transfer to a new payee, outside the short timing window.",
    "scary_quiet": "The text looks alarming, and the only later activity is ordinary spending at a known coffee shop.",
    "scary_near": "The text looks alarming. A small coffee purchase at the usual shop happened soon after, with no new payee.",
    "scary_device": "The text looks alarming. A new phone was added and a usual coffee purchase followed. No money left the account to a new payee.",
    "legit_soon": "A real bill reminder was followed the same morning by an on-time payment to the biller already on the account.",
    "legit_later": "A real bill reminder was followed the next day by an on-time payment to the matching biller.",
}

KIND_TAXONOMY = {
    "billing_unknown_payee": "billing_scam",
    "delivery_cnp": "delivery_scam",
    "carrier_takeover": "account_security",
    "toll_payment": "toll_government",
    "refund_overpay": "prize_refund",
    "job_deposit": "job_offer",
    "known_biller_spike": "billing_scam",
    "prize_giftcard": "prize_refund",
    "delayed_bank": "bank_impersonation",
    "legit_soon": "legit",
    "legit_later": "legit",
}


def _scenario_plan() -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []

    def add(n: int, kind: str, fraud: bool, taxonomy: str | None = None) -> None:
        for copy in range(n):
            plan.append({"kind": kind, "fraud": fraud, "taxonomy": taxonomy or KIND_TAXONOMY[kind], "copy": copy})

    add(32, "billing_unknown_payee", True)
    add(32, "delivery_cnp", True)
    add(32, "carrier_takeover", True)
    add(24, "toll_payment", True)
    add(24, "refund_overpay", True)
    add(20, "job_deposit", True)
    add(12, "known_biller_spike", True)
    add(8, "prize_giftcard", True)
    add(8, "delayed_bank", True)
    scary = ["billing_scam", "delivery_scam", "bank_impersonation", "account_security", "toll_government", "prize_refund", "job_offer", "conversation_lure"]
    for copy in range(40):
        plan.append({"kind": "scary_quiet", "fraud": False, "taxonomy": scary[copy % len(scary)], "copy": copy})
    for copy in range(20):
        plan.append({"kind": "scary_near", "fraud": False, "taxonomy": scary[copy % len(scary)], "copy": copy})
    for copy in range(8):
        plan.append({"kind": "scary_device", "fraud": False, "taxonomy": scary[copy % len(scary)], "copy": copy})
    add(30, "legit_soon", False)
    add(30, "legit_later", False)
    return plan


def _campaign_message(variant: dict[str, Any], message_id: str, received: datetime) -> dict[str, Any]:
    category = variant["taxonomy_id"]
    return {
        "message_id": message_id,
        "mode": "check",
        "received_at": iso_central(received),
        "sender": variant["sender"],
        "text_redacted": variant["text_redacted"],
        "urls": [
            {
                "id": "URL_1",
                "registered_domain": variant["domain"],
                "is_shortener": variant["technique"] == "URL shortener",
                "brand_term_in_domain": None if variant["technique"] in {"URL shortener", "homoglyph"} else variant["domain"].split(".")[0][:12],
                "is_official_brand_domain": False,
            }
        ],
        "features": {
            "urgency_deadline": "today",
            "threat": "service_suspension" if category in {"billing_scam", "toll_government"} else "account_lock" if category in {"bank_impersonation", "account_security"} else None,
            "requested_action": "click_link_and_pay" if category in {"billing_scam", "toll_government"} else "click_link",
            "asks_for": ["payment"] if category in {"billing_scam", "toll_government", "job_offer"} else ["login"],
            "money_amount_claimed": float(variant["amount"]),
        },
        "classifier": _classifier(category, 0.88),
        "customer_context": {"linked_bank": True, "linked_institutions": ["Harbor Mutual"]},
        "template_id": variant["template_id"],
        "template_set": "A",
        "source_url": variant["url"],
    }


def _legit_scenario_message(scenario_index: int, message_id: str, received: datetime) -> dict[str, Any]:
    set_name = "A" if scenario_index % 2 == 0 else "B"
    pool = "SA" if set_name == "A" else "SB"
    brand = BRANDS["legit"][set_name][0]
    frame = FRAMES["legit"][set_name][0]
    sender = _sender(pool, "short_code", "legit", scenario_index)
    domain = f"scn-{set_name.lower()}-bill.example"
    url = f"https://{domain}/bill"
    text = _fill(frame["text"], brand[0], 86, "tomorrow")
    return {
        "message_id": message_id,
        "mode": "check",
        "received_at": iso_central(received),
        "sender": {"type": sender["type"], "value": sender["value"], "claimed_brand": brand[0]},
        "text_redacted": text,
        "urls": [{"id": "URL_1", "registered_domain": domain, "is_shortener": False, "brand_term_in_domain": None, "is_official_brand_domain": True}],
        "features": {"urgency_deadline": None, "threat": None, "requested_action": "open_official_app", "asks_for": [], "money_amount_claimed": 86.0},
        "classifier": _classifier("legit", 0.93),
        "customer_context": {"linked_bank": True, "linked_institutions": ["Harbor Mutual"]},
        "template_id": f"scn_legit_{set_name}",
        "template_set": set_name,
        "source_url": url,
    }


def _click(kind: str, message_at: datetime, url: str | None) -> dict[str, Any] | None:
    if url is None or kind in {"scary_quiet", "legit_soon", "legit_later"}:
        return None
    entered = kind in {"billing_unknown_payee", "carrier_takeover", "known_biller_spike", "delivery_cnp", "refund_overpay"}
    return {
        "clicked": True,
        "ts": to_z(message_at + timedelta(minutes=4)),
        "url": url,
        "credential_entered": entered,
        "otp_shared": kind == "carrier_takeover",
    }


def build_scenarios(campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tax: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in campaigns:
        by_tax[row["taxonomy_id"]].append(row)
    scenarios: list[dict[str, Any]] = []
    for index, spec in enumerate(_scenario_plan()):
        customer_id = f"cust_{index:04d}"
        accounts = {
            "checking": f"acct_{index:04d}_chk",
            "credit": f"acct_{index:04d}_cc",
            "carrier": f"acct_{index:04d}_car",
        }
        message_at = AS_OF - timedelta(days=index % 5)
        message_id = f"scnmsg_{index:04d}"
        use_campaign = spec["fraud"] or spec["kind"].startswith("scary")
        campaign_id = None
        if use_campaign and not (spec["fraud"] and index % 7 == 0):
            pool = by_tax[spec["taxonomy"]]
            variant = pool[(index + spec["copy"]) % len(pool)]
            campaign_id = variant["campaign_id"]
            message = _campaign_message(variant, message_id, message_at)
        elif spec["kind"] in {"legit_soon", "legit_later"}:
            message = _legit_scenario_message(index, message_id, message_at)
        else:
            pool = by_tax[spec["taxonomy"]]
            variant = pool[index % len(pool)]
            message = _campaign_message(variant, message_id, message_at)
            campaign_id = None
        ledger = _Ledger(index, customer_id)
        baseline = _baseline(ledger, message_at, index, accounts)
        post = _post(spec["kind"], ledger, message_at, index, accounts, message_id, spec["kind"] if spec["fraud"] else "")
        known = {KNOWN_BILLER}
        signals = compute_signals(message_at, baseline, post, known)
        fraud_events = [event for event in post if event["labels"]["is_fraud"]]
        if spec["fraud"] and not fraud_events:
            raise RuntimeError(f"{spec['kind']} produced no fraud event")
        if not spec["fraud"] and fraud_events:
            raise RuntimeError(f"{spec['kind']} labeled a benign event as fraud")
        first = fraud_events[0]["event_id"] if fraud_events else None
        first_name = FIRST_NAMES[index % len(FIRST_NAMES)]
        last_name = LAST_NAMES[(index // 10) % len(LAST_NAMES)]
        scenarios.append(
            {
                "scenario_id": f"scn_{index:04d}",
                "taxonomy_id": spec["taxonomy"],
                "campaign_id": campaign_id,
                "message": message,
                "click": _click(spec["kind"], message_at, message.get("source_url")),
                "customer": {
                    "customer_id": customer_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "accounts": [
                        {"account_id": accounts["checking"], "account_type": "checking", "nickname": "Everyday Checking"},
                        {"account_id": accounts["credit"], "account_type": "credit_card", "nickname": "Rewards Card"},
                        {"account_id": accounts["carrier"], "account_type": "carrier_account", "nickname": "Mobile Account"},
                    ],
                    "bills": [
                        {
                            "biller_id": "biller_northline",
                            "bill_id": f"bill_{index:04d}_nl",
                            "payee": KNOWN_BILLER,
                            "due_date": "2026-11-12",
                            "status": "pending",
                            "autopay": True,
                            "amount_due_minor": 8640,
                        }
                    ],
                },
                "baseline_events": baseline,
                "post_events": post,
                "ground_truth": {
                    "is_fraud": spec["fraud"],
                    "fraud_type": spec["kind"] if spec["fraud"] else None,
                    "first_fraud_event_id": first,
                    "explanation": EXPLANATIONS[spec["kind"]],
                    "signals": signals,
                },
            }
        )
    return scenarios


NESSIE_ACCOUNT_TYPE = {
    "checking": "Checking",
    "savings": "Savings",
    "credit_card": "Credit Card",
    "carrier_account": "Checking",
    "mobile_money": "Checking",
    "wallet": "Checking",
}
BILL_STATUS = {"paid": "completed", "pending": "pending", "overdue": "pending", "cancelled": "cancelled"}
PURCHASE_TYPES = {"purchase"}
TRANSFER_TYPES = {"transfer_out", "transfer_in", "deposit", "withdrawal", "refund"}
BILL_TYPES = {"bill_payment", "bill_issued"}


def nessie_export(scenario: dict[str, Any]) -> dict[str, Any]:
    """DATA_SPEC section 6 objects plus a manifest for times, accounts, and join keys.

    Live Nessie drops cents and stores no time of day. Amounts are whole dollars
    (truncated). ``at`` lives in the manifest, the same place ``nessie_seed.json``
    keeps purchase times and transfer payees.
    """
    customer = scenario["customer"]
    purchases: list[dict[str, Any]] = []
    transfers: list[dict[str, Any]] = []
    bills: list[dict[str, Any]] = []
    merchants: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    purchase_times: dict[str, str] = {}
    transfer_times: dict[str, str] = {}
    last_balance: dict[str, int] = {}
    for event in [*scenario["baseline_events"], *scenario["post_events"]]:
        last_balance[event["account_id"]] = event["balance_after_minor"]
        if event["counterparty_id"] and event["counterparty_type"] in {"merchant", "unknown", "biller", "person", "bank"}:
            merchants[event["counterparty_id"]] = {
                "_id": event["counterparty_id"],
                "name": event["counterparty_name"] or event["counterparty_id"],
                "category": event["merchant_category"] or "General",
            }
        truncated = (event["amount_minor"] // 100) * 100
        if event["event_type"] in PURCHASE_TYPES:
            purchase_id = f"pur_{event['event_id']}"
            purchases.append(
                {
                    "_id": purchase_id,
                    "merchant_id": event["counterparty_id"],
                    "purchase_date": event["timestamp"][:10],
                    "amount": event["amount_minor"] // 100,
                    "status": "completed" if event["status"] == "completed" else event["status"],
                    "description": event["counterparty_name"] or event["event_type"],
                }
            )
            purchase_times[purchase_id] = event["timestamp"]
            links.append({"event_id": event["event_id"], "object": "purchase", "object_id": purchase_id, "event_type": event["event_type"], "account_id": event["account_id"], "at": event["timestamp"], "amount_minor_truncated": truncated})
        elif event["event_type"] in TRANSFER_TYPES:
            transfer_id = f"xfr_{event['event_id']}"
            outbound = event["direction"] != "credit"
            transfers.append(
                {
                    "_id": transfer_id,
                    "payer_id": event["account_id"] if outbound else (event["counterparty_id"] or "external_payer"),
                    "payee_id": (event["counterparty_id"] or "external_payee") if outbound else event["account_id"],
                    "transaction_date": event["timestamp"][:10],
                    "amount": event["amount_minor"] // 100,
                    "status": "completed" if event["status"] == "completed" else event["status"],
                    "description": event["counterparty_name"] or event["event_type"],
                }
            )
            transfer_times[transfer_id] = event["timestamp"]
            links.append({"event_id": event["event_id"], "object": "transfer", "object_id": transfer_id, "event_type": event["event_type"], "account_id": event["account_id"], "at": event["timestamp"], "amount_minor_truncated": truncated})
        elif event["event_type"] in BILL_TYPES and event["bill"] is not None:
            bill_id = f"bil_{event['event_id']}"
            bills.append(
                {
                    "_id": bill_id,
                    "status": BILL_STATUS[event["bill"]["status"]],
                    "payee": event["counterparty_name"],
                    "nickname": event["counterparty_name"],
                    "payment_date": event["timestamp"][:10],
                    "recurring_date": int(event["bill"]["due_date"][8:10]),
                    "payment_amount": event["amount_minor"] // 100,
                }
            )
            links.append({"event_id": event["event_id"], "object": "bill", "object_id": bill_id, "event_type": event["event_type"], "account_id": event["account_id"], "at": event["timestamp"], "amount_minor_truncated": truncated, "bill_status": event["bill"]["status"]})
    nicknames = {item["account_id"]: item for item in customer["accounts"]}
    return {
        "_note": "Synthetic Nessie-shaped export for one linked scenario. Not live customer data. Do not post it to the demo seed.",
        "scenario_id": scenario["scenario_id"],
        "customers": [{"_id": customer["customer_id"], "first_name": customer["first_name"], "last_name": customer["last_name"]}],
        "accounts": [
            {
                "_id": item["account_id"],
                "type": NESSIE_ACCOUNT_TYPE[item["account_type"]],
                "nickname": item["nickname"],
                "balance": (last_balance.get(item["account_id"], 0) or 0) // 100,
                "customer_id": customer["customer_id"],
            }
            for item in customer["accounts"]
        ],
        "merchants": list(merchants.values()),
        "purchases": purchases,
        "transfers": transfers,
        "bills": bills,
        "manifest": {
            "purchase_times": purchase_times,
            "transfer_times": transfer_times,
            "links": links,
            "nessie_account_type_note": "carrier_account is exported as Nessie type Checking because Nessie has no carrier account type.",
        },
    }


def _rdap(technique: str | None, label: str) -> dict[str, Any]:
    if label == "legit":
        return {"found": True, "registered_at": "2014-03-15T00:00:00Z", "registrar": "Reserved Example Registry"}
    when = {
        "fresh registration": "2026-11-06T00:00:00Z",
        "typosquat": "2026-10-18T00:00:00Z",
        "homoglyph": "2026-09-02T00:00:00Z",
        "subdomain abuse": "2026-08-20T00:00:00Z",
        "URL shortener": "2016-04-01T00:00:00Z",
    }.get(technique or "", "2026-10-01T00:00:00Z")
    return {"found": True, "registered_at": when, "registrar": "Example Registrar LLC"}


def build_urls(messages: list[dict[str, Any]], campaigns: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def add(url: str, domain: str, host: str, label: str, technique: str | None, lookalike: str | None) -> None:
        if url in found:
            return
        found[url] = {
            "url": url,
            "domain": domain,
            "host": host,
            "label": label,
            "technique": technique,
            "lookalike_of": lookalike,
            "rdap": _rdap(technique, label),
        }

    for message in messages:
        if message["source_url"]:
            url_info = message["urls"][0]
            add(
                message["source_url"],
                url_info["registered_domain"],
                message["source_host"],
                message["link_label"],
                message["link_technique"],
                message["lookalike_of"],
            )
    for row in campaigns:
        add(row["url"], row["domain"], row["host"], "phishing", row["technique"], row["lookalike_of"])
    for scenario in scenarios:
        url = scenario["message"].get("source_url")
        if not url:
            continue
        info = scenario["message"]["urls"][0]
        label = "legit" if info["is_official_brand_domain"] else "phishing"
        technique = "URL shortener" if info["is_shortener"] else (None if label == "legit" else "typosquat")
        add(url, info["registered_domain"], info["registered_domain"], label, technique, None)
    for n in range(8):
        domain = f"missing-{n}.test"
        found[f"https://{domain}/gone"] = {
            "url": f"https://{domain}/gone",
            "domain": domain,
            "host": domain,
            "label": "phishing",
            "technique": "fresh registration",
            "lookalike_of": None,
            "rdap": {"found": False, "registered_at": None, "registrar": None},
        }
    # The message pass above stamps every non-official message URL as typosquat.
    # Campaign rows already carry the real technique and are inserted first only
    # if not already present. Re-apply campaign techniques, which are authoritative.
    for row in campaigns:
        found[row["url"]]["technique"] = row["technique"]
        found[row["url"]]["rdap"] = _rdap(row["technique"], "phishing")
        found[row["url"]]["lookalike_of"] = row["lookalike_of"]
    return [found[key] for key in sorted(found)]


def collect_telecom(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scenario in scenarios:
        for event in [*scenario["baseline_events"], *scenario["post_events"]]:
            if event["event_type"] in TELECOM_TYPES and event["event_id"] not in seen:
                seen.add(event["event_id"])
                rows.append(event)
    return rows


def _counts(messages: list[dict[str, Any]], campaigns: list[dict[str, Any]], scenarios: list[dict[str, Any]], urls: list[dict[str, Any]], telecom: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat = Counter(row["taxonomy_id"] for row in messages)
    by_split = Counter(row["split"] for row in messages)
    by_set = Counter(row["template_set"] for row in messages)
    subtypes = Counter(row["subtype"] for row in messages if row["taxonomy_id"] == "legit")
    fraud = sum(1 for row in scenarios if row["ground_truth"]["is_fraud"])
    signals = Counter()
    for row in scenarios:
        for name, value in row["ground_truth"]["signals"].items():
            signals[f"{name}:{value}"] += 1
    variants = Counter(row["campaign_id"] for row in campaigns)
    return {
        "seed": SEED,
        "generator": GENERATOR,
        "model": MODEL,
        "messages": len(messages),
        "per_category": {key: by_cat[key] for key in TAXONOMY},
        "per_split": dict(by_split),
        "per_template_set": dict(by_set),
        "legit_subtypes": dict(subtypes),
        "campaigns": len(variants),
        "campaign_variants": len(campaigns),
        "variants_per_campaign": {"min": min(variants.values()), "max": max(variants.values())},
        "urls": len(urls),
        "scenarios": len(scenarios),
        "scenarios_fraud": fraud,
        "scenarios_benign": len(scenarios) - fraud,
        "benign_share": round((len(scenarios) - fraud) / len(scenarios), 4),
        "telecom_events": len(telecom),
        "telecom_types": dict(Counter(row["event_type"] for row in telecom)),
        "signals": dict(signals),
    }


def render_readme(stats: dict[str, Any]) -> str:
    cat_rows = "\n".join(
        f"| `{key}` | {stats['per_category'][key]} |" for key in TAXONOMY
    )
    signal_rows = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(stats["signals"].items()))
    subtype_rows = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(stats["legit_subtypes"].items()))
    telecom_rows = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(stats["telecom_types"].items()))
    return f"""# Datasheet: synthetic linked scenarios

**{WARNING}**

This page describes the files added beside the A21 message set. It does not replace `data/generated/README.md` (that file is the A21 datasheet and was left in place).

## Purpose

Public SMS sets are binary or three-class, and none of them ties a text to a click and then to account activity. These files fill that gap so a Nemotron-style checker can be scored on:

- a 9-way taxonomy label
- campaign variants of one lure
- link technique and a synthetic RDAP record
- a 30–60 day canonical baseline plus the events after the text
- carrier events (SIM, port-out, eSIM, plan, device, bill amount, autopay)

The agent-facing signals, each present in some scenarios and absent in others, are: a new payee, an amount far from the baseline, a channel never used before, a bill paid to a biller that is not on the account, a new device or SIM change near a payment, and timing within three hours of the message.

## How it was made

| | |
| --- | --- |
| Generator | `backend/scripts/gen_linked_scenarios.py` (`python -m scripts.gen_linked_scenarios` from `backend/`) |
| Seed | `{stats['seed']}` |
| Model | {stats['model']} |
| Prompt path requested | `scripts/gen_linked_scenarios.py`. This repo keeps Python generators in `backend/scripts/` so they run as modules. |

Rebuild is exact: the script does not call a network or a model. `tests/test_synthetic_linked.py` rebuilds the blobs and compares them to the committed files.

## Template sets

Train and validation come from template set **A**. Test comes from template set **B**. The sets do not share a template id, a template skeleton, a URL, or a sender value. Validation may reuse set A templates; it is not a third prompt set. The split inside each category is 140 train / 30 validation / 30 test (70/15/15 of 200).

Campaigns are seeded only from set A wording and from senders and domains that are not in the multiclass file, so they are not a back door into the test split. The held-out test split of `messages_multiclass.jsonl` must not be used to train, tune, build blocklists, or seed campaigns.

## Counts

| Split | Messages |
| --- | --- |
| train | {stats['per_split'].get('train', 0)} |
| validation | {stats['per_split'].get('validation', 0)} |
| test | {stats['per_split'].get('test', 0)} |
| template set A | {stats['per_template_set'].get('A', 0)} |
| template set B | {stats['per_template_set'].get('B', 0)} |
| all messages | {stats['messages']} |

| Taxonomy id | Messages |
| --- | --- |
{cat_rows}

Legitimate subtypes (hard look-alikes included):

| Subtype | Messages |
| --- | --- |
{subtype_rows}

| Other file | Count |
| --- | --- |
| Campaigns | {stats['campaigns']} ({stats['campaign_variants']} variants, {stats['variants_per_campaign']['min']}–{stats['variants_per_campaign']['max']} each) |
| URLs | {stats['urls']} |
| Linked scenarios | {stats['scenarios']} ({stats['scenarios_fraud']} fraud, {stats['scenarios_benign']} benign, benign share {stats['benign_share']}) |
| Telecom events | {stats['telecom_events']} |
| Nessie exports | one JSON file per scenario under `nessie_export/` |

Telecom event types:

| event_type | Count |
| --- | --- |
{telecom_rows}

Signal coverage (`name:true/false` is the number of scenarios):

| Signal | Scenarios |
| --- | --- |
{signal_rows}

## Files

| File | What it is |
| --- | --- |
| `payment_schema.json` | JSON Schema for a canonical event |
| `schema_mappings/*.yaml` | Field maps for Nessie, PaySim, Sparkov, IBM AML, a generic card processor, and telecom billing |
| `messages_multiclass.jsonl` | One DATA_SPEC 3.1 message per line, plus `taxonomy_id`, `template_set`, `template_id`, `template_skeleton`, `split`, `subtype`, `source_url`, `is_scam` |
| `campaigns.jsonl` | One variant per line |
| `urls.jsonl` | `url`, `domain`, `label`, `technique`, `rdap` |
| `linked_scenarios.jsonl` | Message, optional click, customer, baseline events, post events, ground truth |
| `telecom_events.jsonl` | Canonical events whose type is a carrier code |
| `nessie_export/` | Customers, accounts, purchases, transfers, bills, merchants |

`source_url`, template ids, split, and `ground_truth` are supervision. They are not a Nemotron payload. Nemotron still receives only DATA_SPEC section 3. The `labels` object on an event is synthetic supervision and is never shown to a model.

## Mapping layer

`backend/app/adapters/mapping_loader.py` loads one YAML file by name (`load_mapping("paysim")`, `configure("nessie")`). A new source system is a new file, not a code change.

The brief's mapping table did not include a generic card processor. `generic_card_processor.yaml` is a card-auth layout (token, MCC, amount in cents, entry mode) so that column of the deliverable still has a file.

| canonical | Nessie | PaySim | Sparkov | IBM AML | telecom billing | generic card processor |
| --- | --- | --- | --- | --- | --- | --- |
| event_type | object type | type | purchase | Payment Format | event code | txn type |
| timestamp | purchase_date / transaction_date / payment_date | step hour offset | trans_date_trans_time | Timestamp | event_time | authorization_time |
| account_id | payer_id / account id | nameOrig | cc_num | Account | msisdn / account_no | card token |
| counterparty | merchant_id / payee_id | nameDest | merchant | Account.1 | biller / dealer | merchant id |
| amount_minor | amount × 100 | amount × 100 | amt × 100 | Amount Paid × 100 | charge × 100 | amount_cents |
| currency | USD default | null → USD | USD | Payment Currency | bill currency | currency code |
| merchant_category | merchant.category | null | category | null | "carrier" | MCC |
| bill.status | bill.status | — | — | — | bill status | — |
| balance_after | account.balance × 100 | newbalanceOrig × 100 | — | — | — | — |
| device | — | — | — | — | imei / sim_iccid | — |
| labels.is_fraud | seeded | isFraud | is_fraud | Is Laundering | seeded | is_fraud |

## Signal definitions

Computed in the generator and stored on `ground_truth.signals`:

- `new_payee`: a post-message debit whose counterparty is first seen, or a `payee_added` event
- `amount_far_from_baseline`: a post-message debit at least 3× the median baseline debit
- `channel_never_used`: a post-message debit whose channel is absent from baseline debits
- `bill_nonmatching_biller`: a `bill_payment` whose payee is not Northline Mobile (the only biller on these customers)
- `new_device_or_sim_near_payment`: `sim_change`, `esim_transfer`, `port_out_request`, or `device_add` with `new_device` true, at most 60 minutes before a post-message debit
- `timing_near_message`: a post-message debit within 180 minutes after the text

Baseline debits use `card_present`, `bill_pay`, and `atm` only, so card-not-present, wire, ACH, and gift card are new channels when they appear after the text.

## Nessie export

Objects use the field names in DATA_SPEC section 6. Purchases are whole dollars because live Nessie drops cents (`amount_minor // 100`). Dates are `YYYY-MM-DD`. The exact UTC time is `manifest.purchase_times` / `manifest.transfer_times`, matching how `data/nessie_seed.json` keeps times. `manifest.links` joins each object back to `event_id`. Applying `schema_mappings/nessie.yaml` recovers the event type, the truncated amount, and the calendar date.

`carrier_account` is exported as Nessie type `Checking` with nickname "Mobile Account". Nessie has no carrier account type.

## RDAP stub

`urls.jsonl` `rdap` is `{{found, registered_at, registrar}}`. `found` and `registered_at` match what `app.integrations.rdap.lookup_registration` stores. `registrar` is extra and is not sent anywhere. Phishing dates are recent except for the synthetic shortener, which is old. Legitimate `.example` domains are dated 2014. Eight `missing-N.test` rows use `found: false`, the same shape as a 404 fixture.

## How this complements public sets

See `docs/PUBLIC_DATASETS.md`.

| Public set | What it already covers | What these files add |
| --- | --- | --- |
| UCI SMS Spam (`ucirvine/sms_spam`) | Real binary spam/ham | 9-way labels and hard legitimate look-alikes (bills, OTPs, delivery) |
| Mendeley SMS Phishing | Ham/spam/smishing plus URL flags | Taxonomy ids and a click joined to account events |
| PhiUSIIL / phishing-url | Phishing vs legit URLs | Lookalikes only on `.test`, with technique and an RDAP stub |
| PaySim / Sparkov / IBM AML | Payment rows in their own columns | A canonical event plus a YAML map, and a message that precedes the payment |

## Conflicts and choices

- Datasheet file name is `SYNTHETIC_LINKED_README.md` so the A21 `README.md` stays intact.
- `event_type` includes `esim_transfer`, `plan_change`, and `bill_amount_change`. The brief's enum table omitted them and the telecom deliverable requires them.
- Message `received_at` uses the Central offset from DATA_SPEC 3.1. Canonical events use UTC `Z` as the schema asks.
- Classifier scores are fixed placeholders so the 3.1 shape is populated. They are not the output of Nemotron, DeepSeek, or the trained classifier.
- Phone numbers are the reserved range 555-0100 through 555-0199 (E.164 `+155555501xx`). Long-code senders are stored as `<PHONE_HASH_…>` from a seeded SHA-256, never as the raw number. Short codes in the 56000–58499 and 57000+ bands are fictional and are not the Capital One codes in `data/brands.json`.
- Domains are `.test` or `.example` only. `lookalike_of` names the real site being imitated (for example `t-mobile.com`). That string is a label, not a link in the message.
- Some bank texts contain the word "fraud" because real fraud alerts do. The word "scam" is not used.
- Every customer is named from a five-surname toy list (Sample, Example, North, Demo, Placeholder). There is no real person in this set.
- Bill-pay to **Unknown Payee** is a `bill_payment` in the canonical events and a Nessie bill plus merchant, not a Nessie transfer. DATA_SPEC section 6 notes that live transfers cannot name a receiver and that the demo's planted $900 is a purchase at Unknown Payee. The canonical event still says bill payment, which is the story under test. The export does not pretend the live API stored a payee on a transfer.

## Known biases

- One author, one seed, English only. Test set B uses different sentences, brands, domains, and senders, but the same generator.
- Amounts, merchants, and city are a handful of slots. A model can memorize "Demo Grocery" as safe.
- The 70/15/15 split is balanced on purpose. Real inboxes are not 8/9 scam.
- Baseline spending is the same shape for every customer, so "far from baseline" is easy if the amount is $250 or more and hard to miss.
- Carrier events are scripted next to the payment in takeover scenarios. A real SIM swap is rarer and messier.
- `labels.is_fraud` on an event is the answer key. Training or prompting on it would leak the label.

## Privacy

{WARNING}

No customer of any bank or carrier is described here. Names, numbers, and domains are reserved or invented. Nothing in this folder was retrieved from Nessie, RDAP, or a model.
"""


def _check(messages: list[dict[str, Any]], campaigns: list[dict[str, Any]], scenarios: list[dict[str, Any]], telecom: list[dict[str, Any]]) -> None:
    by_cat = Counter(m["taxonomy_id"] for m in messages)
    for category in TAXONOMY:
        if by_cat[category] < 150:
            raise RuntimeError(f"{category} has {by_cat[category]}")
    a_templates = {m["template_id"] for m in messages if m["template_set"] == "A"}
    b_templates = {m["template_id"] for m in messages if m["template_set"] == "B"}
    a_urls = {m["source_url"] for m in messages if m["template_set"] == "A" and m["source_url"]}
    b_urls = {m["source_url"] for m in messages if m["template_set"] == "B" and m["source_url"]}
    a_senders = {m["sender"]["value"] for m in messages if m["template_set"] == "A"}
    b_senders = {m["sender"]["value"] for m in messages if m["template_set"] == "B"}
    a_skel = {m["template_skeleton"] for m in messages if m["template_set"] == "A"}
    b_skel = {m["template_skeleton"] for m in messages if m["template_set"] == "B"}
    if a_templates & b_templates or a_urls & b_urls or a_senders & b_senders or a_skel & b_skel:
        raise RuntimeError("template, URL, sender, or skeleton leaked between sets")
    train_senders = {m["sender"]["value"] for m in messages if m["split"] == "train"}
    test_senders = {m["sender"]["value"] for m in messages if m["split"] == "test"}
    if train_senders & test_senders:
        raise RuntimeError("sender leaked from train into test")
    if len(scenarios) < 300:
        raise RuntimeError("too few scenarios")
    fraud = [s for s in scenarios if s["ground_truth"]["is_fraud"]]
    if not 0.35 <= (len(scenarios) - len(fraud)) / len(scenarios) <= 0.45:
        raise RuntimeError("benign share is not about 40%")
    for scenario in fraud:
        ids = {event["event_id"] for event in scenario["post_events"]}
        if scenario["ground_truth"]["first_fraud_event_id"] not in ids:
            raise RuntimeError(scenario["scenario_id"])
    present = {name for name in ("new_payee", "amount_far_from_baseline", "channel_never_used", "bill_nonmatching_biller", "new_device_or_sim_near_payment", "timing_near_message")}
    seen = {True: set(), False: set()}
    for scenario in scenarios:
        for name, value in scenario["ground_truth"]["signals"].items():
            seen[bool(value)].add(name)
    if seen[True] != present or seen[False] != present:
        raise RuntimeError(f"signal polarity incomplete: true={seen[True]} false={seen[False]}")
    if not TELECOM_TYPES <= {event["event_type"] for event in telecom}:
        raise RuntimeError("telecom file is missing an event type")
    legit_sub = Counter(m["subtype"] for m in messages if m["taxonomy_id"] == "legit")
    for subtype in ("carrier_bill", "otp", "delivery"):
        if legit_sub[subtype] < 20:
            raise RuntimeError(f"hard legit subtype {subtype} has {legit_sub[subtype]}")
    campaign_ids = {row["campaign_id"] for row in campaigns}
    if len(campaign_ids) < 30:
        raise RuntimeError("too few campaigns")
    camp_urls = {row["url"] for row in campaigns}
    msg_urls = {m["source_url"] for m in messages if m["source_url"]}
    camp_senders = {row["sender"]["value"] for row in campaigns}
    msg_senders = {m["sender"]["value"] for m in messages}
    if camp_urls & msg_urls or camp_senders & msg_senders:
        raise RuntimeError("campaign URL or sender collides with the multiclass file")
    per = Counter(row["campaign_id"] for row in campaigns)
    if any(not 5 <= n <= 15 for n in per.values()):
        raise RuntimeError("variant count out of range")


def _validate_events(scenarios: list[dict[str, Any]], telecom: list[dict[str, Any]]) -> None:
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for scenario in scenarios:
        for event in [*scenario["baseline_events"], *scenario["post_events"]]:
            errors = sorted(validator.iter_errors(event), key=lambda err: list(err.path))
            if errors:
                raise RuntimeError(f"{event['event_id']}: {errors[0].message}")
    for event in telecom:
        errors = sorted(validator.iter_errors(event), key=lambda err: list(err.path))
        if errors:
            raise RuntimeError(f"telecom {event['event_id']}: {errors[0].message}")


def build_dataset() -> dict[str, Any]:
    messages = build_messages()
    campaigns = build_campaigns()
    scenarios = build_scenarios(campaigns)
    urls = build_urls(messages, campaigns, scenarios)
    telecom = collect_telecom(scenarios)
    _check(messages, campaigns, scenarios, telecom)
    if SCHEMA_PATH.is_file():
        _validate_events(scenarios, telecom)
    stats = _counts(messages, campaigns, scenarios, urls, telecom)
    return {
        "messages": messages,
        "campaigns": campaigns,
        "urls": urls,
        "scenarios": scenarios,
        "telecom": telecom,
        "stats": stats,
    }


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)


def render_blobs(data: dict[str, Any] | None = None) -> dict[str, str]:
    """Relative path under ``data/generated/`` → file text, including a trailing newline."""
    data = data or build_dataset()
    blobs = {
        "messages_multiclass.jsonl": _jsonl(data["messages"]),
        "campaigns.jsonl": _jsonl(data["campaigns"]),
        "urls.jsonl": _jsonl(data["urls"]),
        "linked_scenarios.jsonl": _jsonl(data["scenarios"]),
        "telecom_events.jsonl": _jsonl(data["telecom"]),
        "synthetic_linked_manifest.json": json.dumps(data["stats"], indent=2, sort_keys=True) + "\n",
        "SYNTHETIC_LINKED_README.md": render_readme(data["stats"]),
    }
    for scenario in data["scenarios"]:
        export = nessie_export(scenario)
        blobs[f"nessie_export/{scenario['scenario_id']}.json"] = json.dumps(export, indent=2, sort_keys=True) + "\n"
    return blobs


def write_dataset(out_dir: Path = OUT_DIR) -> dict[str, Any]:
    data = build_dataset()
    blobs = render_blobs(data)
    for relative, text in blobs.items():
        path = out_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return data["stats"]


def main() -> None:
    stats = write_dataset()
    print(json.dumps({"warning": WARNING, **stats}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
