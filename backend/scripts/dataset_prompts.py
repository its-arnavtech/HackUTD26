"""Prompt sets for the A21 synthetic dataset generator.

Two prompt sets that share nothing but the taxonomy:

- `train_v1` feeds the train and validation splits. It frames the task as writing
  training data and varies the *writer* (who sends the text).
- `test_v1` feeds the test split only. It frames the task as quiz cards for a
  fraud-awareness class, varies the *recipient* instead of the writer, uses its
  own tone list, and adds brands that never appear in `train_v1`.

So the test split doesn't share the training prompts' style (POC_MVP 7.5 step 0).
Nothing here may be tuned by looking at test-split output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Fictional numbers only: the 555-01XX range is reserved for fiction.
SAFETY_RULES = (
    "All content is fictional. Never use a real person's name, address or account number. "
    "Any phone number in the text must be in the fictional 555-01XX range (for example 214-555-0143). "
    "Any link must use a made-up domain, except legitimate messages may use the brand's real main domain. "
    "Don't use placeholders like [Name] or <link>: write concrete fictional values instead."
)

# Formatted with str.format, so literal braces are doubled.
OUTPUT_FORMAT = (
    'Return only JSON: {{"messages": ["<text 1>", "<text 2>", ...]}} with exactly {n} strings. '
    "Each string is the SMS body only, without the sender."
)


@dataclass(frozen=True)
class PromptSet:
    name: str
    system: str
    user_template: str
    personas_scam: tuple[str, ...]
    personas_legit: tuple[str, ...]
    styles: tuple[str, ...]
    # category id -> brands to impersonate (scam) ; legit uses LEGIT_SUBTYPE_BRANDS
    brands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    legit_brands: dict[str, tuple[str, ...]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# train_v1: "write training data", varied writers
# ---------------------------------------------------------------------------

TRAIN_V1 = PromptSet(
    name="train_v1",
    system=(
        "You generate realistic synthetic SMS text messages for training a scam-detection classifier "
        "at a phone carrier. The messages must read exactly like texts people in the United States "
        "really receive, including the typos, abbreviations and formatting quirks of real senders. "
        + SAFETY_RULES
    ),
    user_template=(
        "Category: {category_label} ({label_kind}).\n"
        "What this category covers: {category_description}\n"
        "Angle for this batch: {subtype}.\n"
        "Claimed sender or brand: {brand}.\n"
        "Who writes it: {persona}.\n"
        "Style: {style}.\n"
        "Write {n} different messages. Vary the wording, structure, length (from about 40 to 300 "
        "characters) and details so no two read like the same template. "
        "{label_hint}\n" + OUTPUT_FORMAT
    ),
    personas_scam=(
        "an organized fraud ring copying the brand's official alert template closely",
        "a hurried scammer sending thousands of texts with minimal effort",
        "a scammer whose first language isn't English, with slightly odd grammar",
        "a careful scammer who avoids obvious red-flag words",
        "a scammer using a friendly, casual tone to lower suspicion",
        "a scammer creating panic with deadlines and threats",
    ),
    personas_legit=(
        "the company's automated notification system",
        "a company's customer-care team writing a short service text",
        "a small local business owner",
        "a friend or family member texting casually",
        "an office scheduler or coordinator",
    ),
    styles=(
        "plain sentences, no emoji",
        "brand prefix like 'BRAND:' at the start",
        "all caps for key words",
        "terse, like an automated system",
        "chatty with one emoji",
        "includes a reference or case number",
    ),
    brands={
        "bank_impersonation": ("Capital One", "Chase", "Bank of America", "Wells Fargo", "Citi", "U.S. Bank", "Navy Federal", "PNC"),
        "billing_scam": ("T-Mobile", "AT&T", "Verizon", "Xfinity", "Duke Energy", "Netflix", "Spotify"),
        "delivery_scam": ("USPS", "UPS", "FedEx", "DHL", "Amazon"),
        "account_security": ("Apple", "Amazon", "Microsoft", "Google", "T-Mobile", "PayPal", "Facebook"),
        "toll_government": ("E-ZPass", "SunPass", "TxTag", "NTTA", "the IRS", "the DMV"),
        "prize_refund": ("Walmart", "Costco", "Target", "Amazon", "Best Buy", "T-Mobile Tuesdays"),
        "job_offer": ("a staffing agency", "a LinkedIn recruiter", "Indeed", "an Amazon hiring partner", "no brand"),
        "conversation_lure": ("no brand",),
    },
    legit_brands={
        "bank": ("Capital One", "Chase", "Bank of America", "Wells Fargo", "Citi", "Navy Federal"),
        "carrier": ("T-Mobile", "AT&T", "Verizon", "Xfinity Mobile"),
        "otp": ("Capital One", "Google", "Microsoft", "Apple", "PayPal", "T-Mobile", "Venmo"),
        "delivery": ("USPS", "UPS", "FedEx", "Amazon"),
        "toll": ("E-ZPass", "SunPass", "TxTag", "NTTA"),
        "retail": ("Walmart", "Target", "Costco", "Best Buy", "CVS"),
        "recruiter": ("a recruiter from a mid-size company", "a hiring manager"),
        "appointment": ("a dental office", "Walgreens Pharmacy", "a doctor's office", "a car service center"),
        "community": ("a school district", "an employer", "a church group", "a city alert service"),
        "personal": ("a friend", "a family member", "a coworker"),
    },
)

# ---------------------------------------------------------------------------
# test_v1: "fraud-awareness quiz cards", varied recipients
# ---------------------------------------------------------------------------

TEST_V1 = PromptSet(
    name="test_v1",
    system=(
        "You are helping a fraud-awareness instructor build quiz cards. Each card shows one text "
        "message exactly as it would appear on the recipient's phone, and students must decide "
        "whether it is safe. Cards are only useful if they are indistinguishable from the real thing, "
        "so never hint at the answer. " + SAFETY_RULES
    ),
    user_template=(
        "Quiz topic: {category_label}. The correct answer for these cards is: {label_kind}.\n"
        "Background: {category_description}\n"
        "Scenario for these cards: {subtype}, sent as {brand}.\n"
        "The person receiving the text: {persona}.\n"
        "Tone of the text: {style}.\n"
        "Draft {n} cards, each a different realistic text. {label_hint}\n" + OUTPUT_FORMAT
    ),
    personas_scam=(
        "a retiree in Florida who banks online",
        "a college student with a part-time job",
        "a small-business owner who gets many texts a day",
        "a parent who shops online often",
        "a new immigrant still learning English",
        "a nurse working night shifts",
    ),
    personas_legit=(
        "a retiree in Florida who banks online",
        "a college student with a part-time job",
        "a parent who shops online often",
        "a commuter who drives on toll roads",
        "a nurse working night shifts",
    ),
    styles=(
        "formal and polite",
        "short and urgent",
        "warm and reassuring",
        "neutral, matter-of-fact",
        "slightly sloppy with a typo",
    ),
    brands={
        "bank_impersonation": ("Capital One", "Truist", "Discover", "American Express", "TD Bank", "Regions"),
        "billing_scam": ("T-Mobile", "Spectrum", "Cricket Wireless", "Hulu", "PG&E", "Norton"),
        "delivery_scam": ("USPS", "OnTrac", "Amazon", "Walmart delivery", "LaserShip"),
        "account_security": ("Netflix", "Instagram", "Venmo", "Coinbase", "Verizon", "Yahoo Mail"),
        "toll_government": ("FasTrak", "Illinois Tollway", "the Social Security Administration", "a county court", "the Texas DPS"),
        "prize_refund": ("Kroger", "Home Depot", "Starbucks", "an airline rewards program", "Publix"),
        "job_offer": ("a remote-work platform", "a recruiter on WhatsApp", "a marketing agency", "no brand"),
        "conversation_lure": ("no brand",),
    },
    legit_brands={
        "bank": ("Capital One", "Truist", "Discover", "American Express", "TD Bank"),
        "carrier": ("T-Mobile", "Spectrum Mobile", "Cricket Wireless", "Verizon"),
        "otp": ("Capital One", "Netflix", "Instagram", "Coinbase", "Uber"),
        "delivery": ("USPS", "OnTrac", "Amazon", "Walmart"),
        "toll": ("FasTrak", "Illinois Tollway", "E-ZPass"),
        "retail": ("Kroger", "Home Depot", "Starbucks", "Publix"),
        "recruiter": ("a university career office", "a recruiter at a hospital"),
        "appointment": ("CVS Pharmacy", "a pediatric clinic", "a hair salon", "a veterinarian"),
        "community": ("a homeowners association", "a library", "a youth sports league"),
        "personal": ("a neighbor", "a sibling", "a roommate"),
    },
)

PROMPT_SETS: dict[str, PromptSet] = {p.name: p for p in (TRAIN_V1, TEST_V1)}

# Each legit subtype in data/taxonomy.json maps to a brand pool above.
LEGIT_SUBTYPE_POOL: dict[str, str] = {
    "real-style bank transaction or balance alert": "bank",
    "real-style bank fraud check that asks only for a YES or NO reply": "bank",
    "carrier bill ready or autopay confirmation": "carrier",
    "carrier data usage or plan notice": "carrier",
    "one-time passcode with a do-not-share warning": "otp",
    "delivery update from a carrier or retailer": "delivery",
    "toll account statement or auto-replenish notice": "toll",
    "retail promotion or loyalty points update": "retail",
    "recruiter or interview scheduling message": "recruiter",
    "appointment or pharmacy reminder": "appointment",
    "school, work or community notice": "community",
    "personal message from a friend or family member": "personal",
}

SCAM_HINT = "Each message should contain the kind of lure this category uses (a link, a callback number, a reply request, or a request for money or a code)."
LEGIT_HINT = (
    "These are genuinely legitimate: they don't ask for passwords, card numbers or codes, and any link "
    "goes to the brand's real main domain. Many should look a lot like scam texts on the surface "
    "(alerts, amounts, deadlines, codes), because that's what makes them hard."
)
