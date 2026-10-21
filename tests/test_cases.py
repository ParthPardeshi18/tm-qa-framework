"""Phase 3 checks on the investigator-facing case templates in cases/.

These run against the generated files in data/processed and cases/. They never
open answer-key or evaluation files.
"""

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.case_prep import (
    CASE_FIELDS,
    CASE_FIELDS_V1,
    CASES_DIR,
    DISCLOSURE_FIELDS,
    INVESTIGATORS,
    JUDGEMENT_FIELDS,
    PROCESSED,
    V1_CASES,
    build_cases,
    is_completed,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_FILES = sorted(CASES_DIR.glob("CASE-*.yaml"))
DISPOSITIONS = {"CLOSE_NO_FURTHER_ACTION", "ESCALATE_L2", "ESCALATE_SAR"}

# Answer-key fields, label columns and SAML-D suspicious typology names (docs/eda_notes.md §4).
# "Structuring" is left out because it is also the TM01 scenario name.
FORBIDDEN = [
    "Is_laundering", "Laundering_type", "is_laundering", "laundering_type", "planted",
    "red_flags_missed", "planted_errors", "answer_key", "window_typologies",
    "Cash_Withdrawal", "Deposit-Send", "Smurfing", "Layered_Fan_In", "Layered_Fan_Out",
    "Stacked Bipartite", "Behavioural_Change_1", "Behavioural_Change_2", "Bipartite", "Cycle",
    "Fan_In", "Fan_Out", "Gather-Scatter", "Scatter-Gather", "Single_large", "Over-Invoicing",
    "true positive", "false positive",
]
KEY_FILES = ["alert_sample_key", "profiles_answer_key", "alert_evaluation"]

pytestmark = pytest.mark.skipif(not CASE_FILES, reason="run `python -m src.case_prep` first")


@pytest.fixture(scope="module")
def cases():
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in CASE_FILES]


@pytest.fixture(scope="module")
def sample():
    return pd.read_csv(PROCESSED / "alert_sample.csv")


def test_exactly_24_cases_with_unique_ids(cases):
    assert len(cases) == 24
    assert [c["case_id"] for c in cases] == [f"CASE-{i:03d}" for i in range(1, 25)]
    assert [p.stem for p in CASE_FILES] == [c["case_id"] for c in cases]


def test_every_case_references_a_sampled_alert_once(cases, sample):
    assert sorted(c["alert_id"] for c in cases) == sorted(sample["alert_id"])


def test_case_alert_facts_match_alerts_parquet(cases):
    alerts = pd.read_parquet(PROCESSED / "alerts.parquet").set_index("alert_id")
    for c in cases:
        a = alerts.loc[c["alert_id"]]
        assert c["account_id"] == a["account_id"]
        assert c["scenario"] == f"{a['scenario']} {a['scenario_name']}"
        assert c["alert_date"] == str(a["trigger_date"])


def investigator_fields(c):
    return JUDGEMENT_FIELDS + [f for f in DISCLOSURE_FIELDS if f in c]


def test_schema_by_template_version(cases):
    for c in cases:
        expected = CASE_FIELDS_V1 if c["case_id"] in V1_CASES else CASE_FIELDS
        assert list(c) == expected, c["case_id"]
        assert c["customer_summary"] and c["activity_reviewed"]


def test_uncompleted_cases_are_fully_blank(cases):
    # A case counts as completed once a disposition is recorded. Before that,
    # every investigator field must be null (no partial or pre-filled judgements).
    for c in cases:
        if c["disposition"] is None:
            for f in investigator_fields(c):
                assert c[f] is None, f"{c['case_id']}.{f} is filled but no disposition is recorded"


def _datetime(value, label):
    assert isinstance(value, str) and "T" in value, f"{label} must be an ISO 8601 date-time string"
    return datetime.fromisoformat(value)


def test_completed_cases_are_valid(cases):
    for c in cases:
        if c["disposition"] is None:
            continue
        cid = c["case_id"]
        assert c["disposition"] in DISPOSITIONS, cid
        # Case-handling dates: both recorded (valid, ordered) or both null where no
        # handling record exists (AI-simulated cases); never one without the other.
        if c["date_opened"] is not None or c["date_closed"] is not None:
            for k in ("date_opened", "date_closed"):
                assert isinstance(c[k], str), f"{cid}.{k} must be a YYYY-MM-DD string"
            alert, opened, closed = (date.fromisoformat(c[k]) for k in ("alert_date", "date_opened", "date_closed"))
            assert alert <= opened <= closed, f"{cid}: dates out of order"
        flags = c["red_flags_identified"]
        assert isinstance(flags, list) and flags and all(isinstance(x, str) and x.strip() for x in flags), cid
        for f in ("source_of_funds", "screening_adverse_media", "rationale", "escalation_decision"):
            assert isinstance(c[f], str) and c[f].strip(), f"{cid}.{f} is empty"
        # Disclosure fields (v2 only): either null (never estimated) or valid.
        if "suspicion_formed_at" in c:
            times = {f: _datetime(c[f], f"{cid}.{f}") for f in ("suspicion_formed_at", "internal_disclosure_at")
                     if c[f] is not None}
            if len(times) == 2:
                assert times["suspicion_formed_at"] <= times["internal_disclosure_at"], cid
            for f in ("disclosure_recipient", "referral_evidence"):
                assert c[f] is None or (isinstance(c[f], str) and c[f].strip()), f"{cid}.{f}"


def test_revised_cases_have_disclosure_fields_initially_blank(cases):
    revised = [c for c in cases if c["case_id"] not in V1_CASES]
    assert [c["case_id"] for c in revised] == [f"CASE-{i:03d}" for i in range(2, 25)]
    for c in revised:
        for f in DISCLOSURE_FIELDS:
            assert f in c, f"{c['case_id']} missing {f}"
            if c["disposition"] is None:
                assert c[f] is None, f"{c['case_id']}.{f} must start blank"


def test_case_001_is_completed_v1_case_and_protected_from_regeneration(cases):
    c = cases[0]
    assert c["case_id"] == "CASE-001" and c["disposition"] is not None
    assert not set(DISCLOSURE_FIELDS) & set(c)
    assert is_completed(CASES_DIR / "CASE-001.yaml")


def test_investigators_assigned_in_rotation(cases):
    assert [c["investigator"] for c in cases] == [INVESTIGATORS[i % 3] for i in range(24)]
    assert {i: sum(c["investigator"] == i for c in cases) for i in INVESTIGATORS} == dict.fromkeys(INVESTIGATORS, 8)


def test_evidence_matches_source_data(cases):
    # Re-derive every evidence block from the investigator-facing sources.
    expected = {c["case_id"]: c for c in build_cases()}
    for c in cases:
        assert c["evidence"] == yaml.safe_load(yaml.safe_dump(expected[c["case_id"]]["evidence"], allow_unicode=True))


def test_evidence_totals_reconcile_with_transactions(cases):
    txns = pd.read_parquet(PROCESSED / "txns_alerted.parquet")
    txns["Date"] = pd.to_datetime(txns["Date"]).dt.date.astype(str)
    for c in cases:
        ev, acct = c["evidence"], c["account_id"]
        rp, la = ev["review_period"], ev["lookback_activity"]
        p = txns[(txns["Date"] >= rp["start"]) & (txns["Date"] <= rp["end"])]
        cr, db = p[p["Receiver_account"] == acct], p[p["Sender_account"] == acct]
        assert la["credits_count"] == len(cr) and la["debits_count"] == len(db)
        assert la["credits_total"] == pytest.approx(cr["Amount"].sum(), abs=0.01)
        assert la["debits_total"] == pytest.approx(db["Amount"].sum(), abs=0.01)
        assert sum(b["credits_total"] for b in ev["credits_by_30_day_block"]) == pytest.approx(la["credits_total"], abs=0.05)
        assert ev["alert"]["window_start"] >= rp["start"]


def test_profile_in_case_matches_profiles_parquet(cases):
    profiles = pd.read_parquet(PROCESSED / "profiles.parquet").set_index("account_id")
    for c in cases:
        p = profiles.loc[c["account_id"]]
        cp = c["evidence"]["customer_profile"]
        assert set(cp) == set(profiles.columns)
        assert cp["occupation_or_sector"] == p["occupation_or_sector"]
        assert cp["customer_risk_rating"] == p["customer_risk_rating"]


def test_no_case_references_alerts_dated_after_the_case(cases):
    for c in cases:
        for o in c["evidence"]["other_alerts_on_account"]:
            assert o["trigger_date"] <= c["alert_date"], f"{c['case_id']} lists later alert {o['alert_id']}"
        for f in ("red_flags_identified", "rationale", "escalation_decision"):
            for later in ("TM02-01255", "TM02-00909", "TM03-02062", "TM05-00825"):
                assert later not in str(c[f]), f"{c['case_id']}.{f} references later alert {later}"


def test_build_evidence_excludes_future_alerts():
    # Regression for the look-ahead defect: past and same-day alerts are listed, later ones are not.
    from src.case_prep import build_evidence

    txns = pd.DataFrame([{
        "txn_id": 1, "Date": date(2023, 3, 1), "Time": "10:00:00", "Sender_account": 2, "Receiver_account": 1,
        "Amount": 100.0, "Payment_currency": "UK pounds", "Received_currency": "UK pounds",
        "Sender_bank_location": "UK", "Receiver_bank_location": "UK", "Payment_type": "ACH",
    }])
    alerts = pd.DataFrame({
        "alert_id": ["TM01-00001", "TM04-00001", "TM05-00001", "TM02-00001"],
        "scenario": ["TM01", "TM04", "TM05", "TM02"],
        "account_id": [1, 1, 1, 1],
        "trigger_date": [date(2023, 3, 10), date(2023, 2, 1), date(2023, 3, 10), date(2023, 3, 11)],
    })
    alert = {"alert_id": "TM01-00001", "account_id": 1, "trigger_date": "2023-03-10", "window_start": "2023-03-04",
             "trigger_value": 3.0, "trigger_detail": "test"}
    profile = {"segment": "Personal Banking", "account_open_date": date(2020, 1, 1)}
    ev = build_evidence(alert, profile, txns, alerts, [], 90)
    assert [o["alert_id"] for o in ev["other_alerts_on_account"]] == ["TM04-00001", "TM05-00001"]


def test_training_set_is_isolated_and_labelled():
    # Reads only the training copies, never training/answer_key/.
    trn = sorted((ROOT / "training" / "seeded_cases").glob("TRN-*.yaml"))
    if not trn:
        pytest.skip("training set not generated")
    assert [p.stem for p in trn] == [f"TRN-{i:02d}" for i in range(1, 24)]
    for p in trn:
        text = p.read_text(encoding="utf-8")
        assert text.startswith("# QA TRAINING COPY")
        assert not yaml.safe_load(text)["case_id"].startswith("CASE-")
    assert "training/answer_key/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_no_answer_key_content_in_investigator_outputs():
    texts = {p.name: p.read_text(encoding="utf-8") for p in CASE_FILES}
    texts["alert_sample.csv"] = (PROCESSED / "alert_sample.csv").read_text(encoding="utf-8")
    for name in ("alerts.parquet", "profiles.parquet", "txns_alerted.parquet"):
        texts[name] = " ".join(pd.read_parquet(PROCESSED / name).columns)
    for name, text in texts.items():
        for token in FORBIDDEN:
            assert not re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text), f"{token!r} in {name}"


def test_case_prep_never_reads_answer_key_files():
    src = (ROOT / "src" / "case_prep.py").read_text(encoding="utf-8")
    for name in KEY_FILES + ["Is_laundering", "Laundering_type"]:
        assert name not in src


def test_disposition_values_documented_in_template():
    header = CASE_FILES[0].read_text(encoding="utf-8").split("case_id:")[0]
    assert all(d in header for d in DISPOSITIONS)
