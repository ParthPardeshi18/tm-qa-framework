"""Attribution, timeliness, checklist view, data-driven recommendations and worked QA examples."""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import app_data
from src.qa_engine import load_yaml, qa_outcome, quality_score

ROOT = Path(__file__).resolve().parents[1]
TAX = load_yaml("error_taxonomy.yaml")
CHECKLIST = load_yaml("qa_checklist.yaml")


@pytest.fixture(scope="module")
def qa():
    reviews, findings, _ = app_data.load_qa()
    return reviews, findings


@pytest.fixture(scope="module")
def cases():
    return app_data.load_cases()


# Attribution: investigator error vs process/template vs data vs calibration

def test_attribution_covers_every_record_and_matches_scoring(qa):
    _, findings = qa
    attr = app_data.attribution(findings, TAX)
    assert attr.notna().all()
    assert ((attr == "Investigator error") == (findings["scored"] == "True")).all()
    assert attr.value_counts().to_dict() == {"Process or template weakness": 6, "Calibration point": 6,
                                            "Investigator error": 3, "Data limitation": 3}


def test_every_unscored_code_has_an_attribution():
    prefixes = {k.split("-")[0] for k, v in TAX["error_codes"].items() if v["severity"] == "Observation"}
    assert prefixes <= set(TAX["attribution"]["by_prefix"])


# Timeliness against the portfolio targets

def test_timeliness_of_stored_cases(cases):
    tl = app_data.timeliness(cases).set_index("case_id")
    assert tl.loc["CASE-001", "working_days_to_close"] == 3
    assert tl.loc["CASE-001", "case_timeliness"] == "Within target"
    assert tl.loc["CASE-001", "disclosure_timeliness"] == "Not recordable (v1 template)"
    assert (tl.drop("CASE-001")["case_timeliness"] == "Not verifiable (no case-handling dates)").all()
    l2 = tl[tl["disposition"] == "ESCALATE_L2"]
    assert (l2["disclosure_timeliness"] == "Not applicable").all()
    assert not (tl["case_timeliness"] == "Outside target").any()


def test_timeliness_edge_cases_flag_outside_tolerance():
    base = {"alert_date": "2023-02-14", "suspicion_formed_at": None, "internal_disclosure_at": None}
    late = dict(base, case_id="X1", date_closed="2023-02-24", disposition="ESCALATE_SAR",  # 8 working days
                suspicion_formed_at="2023-02-15T10:00:00", internal_disclosure_at="2023-02-16T09:00:00")
    ok = dict(base, case_id="X2", date_closed="2023-02-21", disposition="ESCALATE_SAR",  # 5 working days
              suspicion_formed_at="2023-02-15T10:00:00", internal_disclosure_at="2023-02-15T16:00:00")
    missing = dict(base, case_id="X3", date_closed=None, disposition="ESCALATE_SAR")
    tl = app_data.timeliness([late, ok, missing]).set_index("case_id")
    assert tl.loc["X1", ["case_timeliness", "disclosure_timeliness"]].tolist() == ["Outside target", "Outside same-day target"]
    assert tl.loc["X2", ["case_timeliness", "disclosure_timeliness"]].tolist() == ["Within target", "Same working day"]
    assert tl.loc["X3", "case_timeliness"].startswith("Not verifiable")
    assert tl.loc["X3", "disclosure_timeliness"].startswith("Not verifiable")  # missing never means late


# Checklist view

def test_checklist_view_lists_all_questions_and_maps_findings(qa):
    _, findings = qa
    v = app_data.checklist_view("CASE-001", findings, CHECKLIST).set_index("question")
    n = sum(len(s["questions"]) for s in CHECKLIST["sections"].values())
    assert n == 19 and len(v) == n and v["critical"].sum() == 4
    assert "SCP-01" in v.loc["A3", "result"] and "CP-02" in v.loc["C3", "result"] and "ACT-01" in v.loc["D3", "result"]
    assert v.loc["E2", "result"] == "No exception recorded"
    clean = app_data.checklist_view("CASE-004", findings, CHECKLIST)
    assert (clean["result"] == "No exception recorded").all()


# Recommendations are computed, not hard-coded

def test_recommendations_use_current_figures(qa):
    _, findings = qa
    eff = app_data.read_processed("scenario_effectiveness.csv")
    text = " ".join(t for _, t in app_data.recommendations(eff, findings))
    for r in eff[eff["laundering_labelled_pct"] < 1].itertuples():
        assert f"{r.scenario} {r.alerts:,} alerts at {r.laundering_labelled_pct}%" in text
    best = eff.loc[eff["laundering_labelled_pct"].idxmax()]
    assert f"{best.laundering_labelled_pct}% for {best.scenario}" in text
    assert f"{(findings['error_code'] == 'CAL-01').sum()} outcomes are flagged as borderline" in text
    assert "PRC-02, 3 cases, closed" in text and "PRC-04, open" in text


def test_recommendations_follow_changed_data(qa):
    _, findings = qa
    eff = pd.DataFrame({"scenario": ["TM01", "TM05"], "alerts": [10, 20], "laundering_labelled_pct": [50.0, 0.5]})
    text = " ".join(t for _, t in app_data.recommendations(eff, findings))
    assert "TM05 20 alerts at 0.5%" in text and "50.0% for TM01" in text


# Worked QA examples

@pytest.fixture(scope="module")
def worked():
    return app_data.load_worked_examples()


def test_worked_examples_share_case_001_evidence_and_stay_outside_the_sample(worked, cases, qa):
    wex, findings = worked
    base = next(c for c in cases if c["case_id"] == "CASE-001")
    assert [c["case_id"] for c in wex] == ["WEX-01", "WEX-02", "WEX-03"]
    for c in wex:
        assert c["evidence"] == base["evidence"] and c["alert_id"] == base["alert_id"]
    reviews, main_findings = qa
    assert not reviews["case_id"].str.startswith("WEX").any()
    assert not main_findings["case_id"].str.startswith("WEX").any()
    for p in sorted((ROOT / "qa" / "worked_examples").glob("WEX-*.yaml")):
        text = p.read_text(encoding="utf-8")
        assert text.startswith("# ILLUSTRATIVE QA WORKED EXAMPLE")
        for token in ("Is_laundering", "Laundering_type", "planted", "answer_key"):
            assert token not in text


def test_worked_examples_produce_each_outcome_path(worked, cases):
    wex, findings = worked
    base = next(c for c in cases if c["case_id"] == "CASE-001")
    result = {}
    for c in wex:
        sev = findings.loc[findings["case_id"] == c["case_id"], "severity"].tolist()
        result[c["case_id"]] = (qa_outcome([s for s in sev if s != "Observation"]), quality_score(sev))
    assert result == {"WEX-01": ("Fail", 0), "WEX-02": ("Fail", 10), "WEX-03": ("Pass with observations", 90)}
    by_id = {c["case_id"]: c for c in wex}
    assert by_id["WEX-01"]["disposition"] == "CLOSE_NO_FURTHER_ACTION"
    assert by_id["WEX-02"]["disposition"] == base["disposition"]  # correct outcome, still a Fail


def test_worked_example_findings_are_traceable(worked):
    _, findings = worked
    questions = {k for s in CHECKLIST["sections"].values() for k in s["questions"]}
    assert findings["finding_id"].is_unique
    for f in findings.to_dict("records"):
        assert TAX["error_codes"][f["error_code"]]["severity"] == f["severity"], f["finding_id"]
        assert f["question_ref"] in questions and f["description"] and f["remediation"]
    assert set(app_data.attribution(findings, TAX)) == {"Investigator error", "Data limitation"}


def test_workbench_renders_worked_examples():
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "2_Case_Review_Workbench.py"), default_timeout=120).run()
    at.radio[0].set_value("Worked QA examples (3, illustrative)").run()
    assert not at.exception
    for wid in ("WEX-01", "WEX-02", "WEX-03"):
        at.selectbox[0].set_value(wid).run()
        assert not at.exception, wid
        outcome = next(m.value for m in at.metric if m.label == "QA outcome")
        assert outcome == {"WEX-01": "Fail", "WEX-02": "Fail", "WEX-03": "Pass with observations"}[wid]
