"""Synthetic KYC / customer profile layer (Phase 1).

SAML-D has no customer data, so every account that needs investigating gets a
deterministic synthetic profile, generated from its account ID alone. No
transaction data is read: profiles are generated only for the IDs requested.

Determinism: each field is drawn from SHA-256 of "<salt>|<account_id>|<field>",
not Python's hash() (salted per process) or the random module (not guaranteed
stable across Python versions). The same ID gives the same profile on any
machine and run.

Assumptions (see docs/methodology.md):
- Account IDs are SAML-D integers (Sender_account / Receiver_account, BIGINT).
- Amounts are treated as GBP. The currency of SAML-D's Amount column is an
  open question in docs/eda_notes.md.
- Expected monthly credits = declared annual income or turnover band / 12.
- Accounts are opened before the first SAML-D transaction date (2022-10-07).
- About 3% of accounts are planted mismatches: profiles whose expected
  activity is deliberately far below typical SAML-D activity, for
  investigators to spot. They are flagged with planted_mismatch=True.
"""

import hashlib
import json
import sys
from datetime import date, timedelta

import pandas as pd

SALT = "tmqa-profile-v1"
DATASET_START = date(2022, 10, 7)  # first Date in SAML-D (docs/eda_notes.md)
EARLIEST_OPEN_DATE = date(2005, 1, 1)

PERSONAL = "Personal Banking"
BUSINESS = "Business Banking"
SEGMENTS = [(PERSONAL, 0.75), (BUSINESS, 0.25)]

# (label, annual low £, annual high £)
INCOME_BANDS = [
    ("£0–£10k", 0, 10_000),
    ("£10k–£25k", 10_000, 25_000),
    ("£25k–£40k", 25_000, 40_000),
    ("£40k–£60k", 40_000, 60_000),
    ("£60k–£100k", 60_000, 100_000),
    ("£100k–£250k", 100_000, 250_000),
]
TURNOVER_BANDS = [
    ("£0–£50k", 0, 50_000),
    ("£50k–£250k", 50_000, 250_000),
    ("£250k–£1m", 250_000, 1_000_000),
    ("£1m–£5m", 1_000_000, 5_000_000),
]

# occupation: (weight, allowed INCOME_BANDS indices)
OCCUPATIONS = {
    "Student": (6, [0]),
    "Unemployed": (3, [0]),
    "Retired": (10, [0, 1, 2]),
    "Care worker": (6, [1]),
    "Retail assistant": (8, [1]),
    "Nurse": (8, [2, 3]),
    "Teacher": (8, [2, 3]),
    "Electrician": (6, [2, 3]),
    "Civil servant": (8, [2, 3]),
    "Software engineer": (6, [3, 4]),
    "Doctor": (3, [4, 5]),
    "Solicitor": (3, [4, 5]),
    "Company director": (3, [4, 5]),
}
# sector: (weight, allowed TURNOVER_BANDS indices)
SECTORS = {
    "Café": (10, [0, 1]),
    "Hairdresser": (8, [0, 1]),
    "Retail shop": (10, [0, 1, 2]),
    "Restaurant": (8, [1, 2]),
    "IT consultancy": (8, [1, 2]),
    "Construction": (10, [1, 2, 3]),
    "Convenience store": (8, [1, 2]),
    "Car trader": (5, [1, 2]),
    "Import/Export": (5, [2, 3]),
    "Money service business": (2, [2, 3]),
}
# Higher inherent ML risk (cash-intensive or high-value, cross-border goods/cash).
HIGH_RISK_SECTORS = {"Convenience store", "Car trader", "Import/Export", "Money service business"}

RISK_RATINGS = ["Low", "Medium", "High"]
PEP_RATE = 0.01
ADVERSE_MEDIA_RATE = 0.02

PLANTED_RATE = 0.03
# Each type: the red flag an investigator should raise when the account shows
# material activity. The typical SAML-D transaction (median ~£6.1k) already
# exceeds these accounts' whole expected month.
PLANTED_TYPES = {
    "LOW_INCOME_PERSONAL": "Student declaring under £10k income; expected credits "
    "under £850/month, so material credits are inconsistent with profile.",
    "MICRO_BUSINESS": "Sole-trader hairdresser with under £50k turnover; "
    "expected credits under £4.2k/month, so high-value or cross-border flows "
    "are inconsistent with the business.",
    "NEW_ACCOUNT_LOW_EXPECTED": "Personal account opened within 90 days of the "
    "dataset start with under £10k declared income; typical money mule profile.",
}

FIELDS = [
    "account_id",
    "segment",
    "occupation_or_sector",
    "declared_income_or_turnover_band",
    "expected_monthly_credits_min_gbp",
    "expected_monthly_credits_max_gbp",
    "account_open_date",
    "customer_risk_rating",
    "pep_flag",
    "adverse_media_flag",
    "planted_mismatch",
    "planted_mismatch_type",
    "planted_mismatch_note",
]


def _unit(account_id: int, field: str) -> float:
    """Stable pseudo-random float in [0, 1) for one account and field."""
    digest = hashlib.sha256(f"{SALT}|{account_id}|{field}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _pick(u: float, weighted: list):
    """Pick from [(value, weight), ...] using u in [0, 1)."""
    total = sum(w for _, w in weighted)
    acc = 0.0
    for value, w in weighted:
        acc += w / total
        if u < acc:
            return value
    return weighted[-1][0]


def _open_date(u: float, start: date, end: date) -> date:
    return start + timedelta(days=int(u * (end - start).days))


def _risk_rating(segment, occupation_or_sector, open_date, pep, adverse_media) -> str:
    """Explainable additive score: 0 Low, 1-2 Medium, 3+ High."""
    score = 0
    score += 1 if segment == BUSINESS else 0
    score += 2 if occupation_or_sector in HIGH_RISK_SECTORS else 0
    score += 3 if pep else 0
    score += 2 if adverse_media else 0
    score += 1 if (DATASET_START - open_date).days < 365 else 0
    return "Low" if score == 0 else "Medium" if score <= 2 else "High"


def generate_profile(account_id) -> dict:
    """Return the deterministic synthetic profile for one account ID."""
    account_id = int(account_id)
    u = lambda field: _unit(account_id, field)  # noqa: E731

    planted = u("planted") < PLANTED_RATE
    planted_type = _pick(u("planted_type"), [(t, 1) for t in PLANTED_TYPES]) if planted else None

    if planted_type in ("LOW_INCOME_PERSONAL", "NEW_ACCOUNT_LOW_EXPECTED"):
        segment, occupation_or_sector, band = PERSONAL, "Student", INCOME_BANDS[0]
    elif planted_type == "MICRO_BUSINESS":
        segment, occupation_or_sector, band = BUSINESS, "Hairdresser", TURNOVER_BANDS[0]
    else:
        segment = _pick(u("segment"), SEGMENTS)
        options, bands = (OCCUPATIONS, INCOME_BANDS) if segment == PERSONAL else (SECTORS, TURNOVER_BANDS)
        occupation_or_sector = _pick(u("occupation"), [(k, w) for k, (w, _) in options.items()])
        band = bands[_pick(u("band"), [(i, 1) for i in options[occupation_or_sector][1]])]

    if planted_type == "NEW_ACCOUNT_LOW_EXPECTED":
        open_date = _open_date(u("open_date"), DATASET_START - timedelta(days=90), DATASET_START - timedelta(days=1))
    else:
        open_date = _open_date(u("open_date"), EARLIEST_OPEN_DATE, DATASET_START - timedelta(days=1))

    # Planted cases keep PEP/adverse media clear so the mismatch is the only signal.
    pep = not planted and u("pep") < PEP_RATE
    adverse_media = not planted and u("adverse_media") < ADVERSE_MEDIA_RATE

    label, low, high = band
    return {
        "account_id": account_id,
        "segment": segment,
        "occupation_or_sector": occupation_or_sector,
        "declared_income_or_turnover_band": label,
        "expected_monthly_credits_min_gbp": round(low / 12),
        "expected_monthly_credits_max_gbp": round(high / 12),
        "account_open_date": open_date,
        "customer_risk_rating": _risk_rating(segment, occupation_or_sector, open_date, pep, adverse_media),
        "pep_flag": pep,
        "adverse_media_flag": adverse_media,
        "planted_mismatch": planted,
        "planted_mismatch_type": planted_type,
        "planted_mismatch_note": PLANTED_TYPES.get(planted_type),
    }


def generate_profiles(account_ids) -> pd.DataFrame:
    """Profiles for the given account IDs (deduplicated, input order kept)."""
    ids = list(dict.fromkeys(int(a) for a in account_ids))
    return pd.DataFrame([generate_profile(a) for a in ids], columns=FIELDS)


if __name__ == "__main__":
    # Usage: python -m src.profiles <account_id> [<account_id> ...]
    sys.stdout.reconfigure(encoding="utf-8")  # band labels contain £ and –
    for arg in sys.argv[1:]:
        print(json.dumps(generate_profile(arg), default=str, ensure_ascii=False, indent=2))
