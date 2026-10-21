import hashlib
import os
import subprocess
import sys
from datetime import date

import pytest

from src.profiles import (
    BUSINESS,
    DATASET_START,
    EARLIEST_OPEN_DATE,
    FIELDS,
    INCOME_BANDS,
    OCCUPATIONS,
    PERSONAL,
    PLANTED_TYPES,
    RISK_RATINGS,
    SECTORS,
    TURNOVER_BANDS,
    generate_profile,
    generate_profiles,
)

# Real account IDs from the head of SAML-D (docs/eda_notes.md sample rows).
REAL_IDS = [8724731955, 2769355426, 1491989064, 8401255335]
SAMPLE_IDS = range(1_000_000_000, 1_000_005_000)


@pytest.fixture(scope="module")
def sample():
    return generate_profiles(SAMPLE_IDS)


# Determinism and reproducibility

def test_same_id_same_profile():
    for a in REAL_IDS:
        assert generate_profile(a) == generate_profile(a)


def test_int_and_str_ids_match():
    assert generate_profile(8724731955) == generate_profile("8724731955")


def test_different_ids_differ():
    assert generate_profile(REAL_IDS[0]) != generate_profile(REAL_IDS[1])


def test_reproducible_across_processes_with_different_hash_seeds():
    code = (
        "import hashlib; from src.profiles import generate_profile; "
        "print(hashlib.sha256(repr(generate_profile(8724731955)).encode()).hexdigest())"
    )
    outputs = set()
    for seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        outputs.add(result.stdout)
    assert len(outputs) == 1
    assert outputs.pop().strip() == hashlib.sha256(repr(generate_profile(8724731955)).encode()).hexdigest()


def test_pinned_profile_does_not_drift():
    # Guards against accidental changes to salt, tables or hashing.
    assert generate_profile(8724731955) == PINNED_8724731955


def test_order_independent_and_deduplicated():
    a = generate_profiles(REAL_IDS + REAL_IDS[:2])
    b = generate_profiles(list(reversed(REAL_IDS)))
    assert len(a) == len(REAL_IDS)
    assert a.set_index("account_id").sort_index().equals(b.set_index("account_id").sort_index())


# Required fields and valid values

def test_required_fields(sample):
    assert list(sample.columns) == FIELDS
    required = [f for f in FIELDS if not f.startswith("planted_mismatch_")]
    assert sample[required].notna().all().all()


def test_valid_values(sample):
    income = {b[0]: b for b in INCOME_BANDS}
    turnover = {b[0]: b for b in TURNOVER_BANDS}
    for p in sample.to_dict("records"):
        assert p["segment"] in (PERSONAL, BUSINESS)
        if p["segment"] == PERSONAL:
            assert p["occupation_or_sector"] in OCCUPATIONS
            label, low, high = income[p["declared_income_or_turnover_band"]]
        else:
            assert p["occupation_or_sector"] in SECTORS
            label, low, high = turnover[p["declared_income_or_turnover_band"]]
        assert p["expected_monthly_credits_min_gbp"] == round(low / 12)
        assert p["expected_monthly_credits_max_gbp"] == round(high / 12)
        assert EARLIEST_OPEN_DATE <= p["account_open_date"] < DATASET_START
        assert p["customer_risk_rating"] in RISK_RATINGS
        assert isinstance(p["pep_flag"], bool) and isinstance(p["adverse_media_flag"], bool)


def test_ordinary_profiles_use_band_allowed_for_occupation(sample):
    ordinary = sample[~sample["planted_mismatch"]]
    for p in ordinary.to_dict("records"):
        table, bands = (OCCUPATIONS, INCOME_BANDS) if p["segment"] == PERSONAL else (SECTORS, TURNOVER_BANDS)
        allowed = {bands[i][0] for i in table[p["occupation_or_sector"]][1]}
        assert p["declared_income_or_turnover_band"] in allowed


def test_pep_and_adverse_media_drive_high_risk(sample):
    assert (sample.loc[sample["pep_flag"], "customer_risk_rating"] == "High").all()
    assert sample["pep_flag"].any() and sample["adverse_media_flag"].any()


def test_rates_are_plausible(sample):
    assert 0.70 < (sample["segment"] == PERSONAL).mean() < 0.80
    assert 0.005 < sample["pep_flag"].mean() < 0.02
    assert 0.01 < sample["adverse_media_flag"].mean() < 0.03


# Deliberate mismatch (planted) cases

def test_planted_cases_are_a_small_flagged_minority(sample):
    rate = sample["planted_mismatch"].mean()
    assert 0.02 < rate < 0.04
    assert set(sample.loc[sample["planted_mismatch"], "planted_mismatch_type"]) == set(PLANTED_TYPES)


def test_planted_fields_only_set_on_planted_cases(sample):
    planted = sample[sample["planted_mismatch"]]
    ordinary = sample[~sample["planted_mismatch"]]
    assert planted[["planted_mismatch_type", "planted_mismatch_note"]].notna().all().all()
    assert ordinary[["planted_mismatch_type", "planted_mismatch_note"]].isna().all().all()


def test_planted_cases_have_low_expected_activity_and_clean_screening(sample):
    planted = sample[sample["planted_mismatch"]]
    # SAML-D median transaction is ~£6.1k (docs/eda_notes.md), so one typical
    # credit exceeds a whole expected month for these profiles.
    assert (planted["expected_monthly_credits_max_gbp"] < 6_100).all()
    assert not planted["pep_flag"].any() and not planted["adverse_media_flag"].any()


def test_planted_type_specifics(sample):
    for p in sample[sample["planted_mismatch"]].to_dict("records"):
        t = p["planted_mismatch_type"]
        if t == "LOW_INCOME_PERSONAL":
            assert (p["segment"], p["occupation_or_sector"]) == (PERSONAL, "Student")
            assert p["expected_monthly_credits_max_gbp"] <= 850
        elif t == "MICRO_BUSINESS":
            assert (p["segment"], p["occupation_or_sector"]) == (BUSINESS, "Hairdresser")
            assert p["declared_income_or_turnover_band"] == TURNOVER_BANDS[0][0]
        elif t == "NEW_ACCOUNT_LOW_EXPECTED":
            assert p["segment"] == PERSONAL
            assert 0 < (DATASET_START - p["account_open_date"]).days <= 90
            assert p["customer_risk_rating"] == "Medium"  # new account bumps risk


PINNED_8724731955 = {
    "account_id": 8724731955,
    "segment": "Personal Banking",
    "occupation_or_sector": "Nurse",
    "declared_income_or_turnover_band": "£40k–£60k",
    "expected_monthly_credits_min_gbp": 3333,
    "expected_monthly_credits_max_gbp": 5000,
    "account_open_date": date(2010, 10, 25),
    "customer_risk_rating": "Low",
    "pep_flag": False,
    "adverse_media_flag": False,
    "planted_mismatch": False,
    "planted_mismatch_type": None,
    "planted_mismatch_note": None,
}
