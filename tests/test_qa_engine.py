import glob

import pandas as pd
import pytest
import yaml

from src.qa_engine import QA_DIR, load_qa, load_yaml, qa_outcome, severity_counts


# Outcome rules

@pytest.mark.parametrize("severities,expected", [
    (["Critical"], "Fail"),
    (["Major"], "Fail"),
    (["Major", "Minor"], "Fail"),
    (["Minor", "Minor"], "Pass with observations"),
    (["Observation"], "Pass"),
    ([], "Pass"),
])
def test_qa_outcome_rules(severities, expected):
    scored = [s for s in severities if s != "Observation"]
    assert qa_outcome(scored) == expected


CFG = {"base": 100, "floor": 0, "deductions": {"Critical": 100, "Major": 30, "Minor": 10, "Observation": 0}}


@pytest.mark.parametrize("severities,expected", [
    ([], 100),                                  # no findings
    (["Observation", "Observation"], 100),      # observations never deduct
    (["Minor"], 90),
    (["Minor", "Minor", "Minor"], 70),
    (["Major"], 70),
    (["Major", "Minor"], 60),
    (["Critical"], 0),                          # critical removes the full base
    (["Critical", "Minor"], 0),                 # floor holds
    (["Minor"] * 12, 0),                        # floor holds for many minors
])
def test_quality_score_paths(severities, expected):
    from src.qa_engine import quality_score
    assert quality_score(severities, CFG) == expected


def test_quality_score_uses_config_and_rejects_unknown_severity():
    from src.qa_engine import quality_score
    assert quality_score(["Minor"]) == 100 - load_yaml("error_taxonomy.yaml")["quality_score"]["deductions"]["Minor"]
    with pytest.raises(KeyError):
        quality_score(["Severe"], CFG)


def test_score_never_overrides_categorical_outcome():
    from src.qa_engine import quality_score
    # High-scoring Major case still fails; Minor-only case at the floor still passes with observations.
    assert quality_score(["Major"], CFG) == 70 and qa_outcome(["Major"]) == "Fail"
    assert quality_score(["Minor"] * 12, CFG) == 0 and qa_outcome(["Minor"] * 12) == "Pass with observations"


def test_taxonomy_matches_engine_rules():
    tax = load_yaml("error_taxonomy.yaml")
    assert tax["severities"]["Major"]["outcome"] == "Fail"
    assert tax["severities"]["Critical"]["outcome"] == "Fail"
    assert tax["severities"]["Minor"]["outcome"] == "Pass with observations"
    assert tax["severities"]["Observation"]["scored"] is False
    assert set(tax["appeals"]["outcomes"]) == {"Upheld", "Overturned"}


def test_checklist_contains_earlier_alert_rule_and_critical_questions():
    q = {k: v for s in load_yaml("qa_checklist.yaml")["sections"].values() for k, v in s["questions"].items()}
    assert "prior alert falls within or at the boundary" in " ".join(q["A3"]["text"].split())
    assert all(q[k].get("critical") for k in ("E2", "F1", "F2", "F3"))


# QA records reconcile with case records

@pytest.fixture(scope="module")
def qa():
    return load_qa()


@pytest.fixture(scope="module")
def cases():
    return {c["case_id"]: c for c in (yaml.safe_load(open(p, encoding="utf-8")) for p in sorted(glob.glob("cases/CASE-*.yaml")))}


def test_every_case_has_one_review(qa, cases):
    reviews, _ = qa
    assert sorted(reviews["case_id"]) == sorted(cases) and len(cases) == 24


def test_reviews_reconcile_with_cases_and_findings(qa, cases):
    reviews, findings = qa
    for r in reviews.to_dict("records"):
        c = cases[r["case_id"]]
        assert r["alert_id"] == c["alert_id"] and r["investigator"] == c["investigator"]
        assert r["disposition"] == c["disposition"]
        n = severity_counts(findings, r["case_id"])
        assert [int(r[k]) for k in ("critical", "major", "minor", "observations")] == \
            [n["Critical"], n["Major"], n["Minor"], n["Observation"]], r["case_id"]
        scored = findings.loc[(findings.case_id == r["case_id"]) & (findings.scored == "True"), "severity"]
        assert r["qa_outcome"] == qa_outcome(scored), r["case_id"]


def test_stored_scores_and_outcomes_match_engine(qa):
    from src.qa_engine import derive
    reviews, findings = qa
    assert derive(reviews, findings)[reviews.columns].equals(reviews)  # stored derived columns are current
    assert reviews.loc[reviews.case_id == "CASE-001", "quality_score"].item() == "70"


def test_findings_are_traceable_and_consistent_with_taxonomy(qa, cases):
    _, findings = qa
    codes = load_yaml("error_taxonomy.yaml")["error_codes"]
    questions = {k for s in load_yaml("qa_checklist.yaml")["sections"].values() for k in s["questions"]}
    assert findings["finding_id"].is_unique
    for f in findings.to_dict("records"):
        assert f["case_id"] in cases or f["case_id"] == "PROJECT"
        if f["case_id"] in cases:
            assert f["alert_id"] == cases[f["case_id"]]["alert_id"]
        assert f["error_code"] in codes and codes[f["error_code"]]["severity"] == f["severity"], f["finding_id"]
        assert f["question_ref"] in questions
        assert f["scored"] == str(f["severity"] != "Observation")
        assert f["description"] and f["remediation"] and f["owner"]


def test_reviews_disclose_authorship_and_non_independence(qa):
    reviews, _ = qa
    assert reviews["review_type"].str.contains("not independent").all()
    ai = reviews[reviews.case_id != "CASE-001"]
    assert (ai["case_note_author"] == "Prepared with AI assistance; reviewed by project author").all()
    assert ai["review_type"].str.contains("not blind").all()


def test_appeals_log_schema():
    appeals = pd.read_csv(QA_DIR / "appeals.csv")
    assert list(appeals.columns) == ["appeal_id", "case_id", "finding_id", "raised_by", "grounds", "decided_by",
                                     "outcome", "reasoning", "decision_date"]


def test_qa_outputs_contain_no_labels_or_answer_key_fields():
    for name in ("findings.csv", "reviews.csv", "appeals.csv"):
        text = (QA_DIR / name).read_text(encoding="utf-8")
        for token in ("Is_laundering", "Laundering_type", "planted", "red_flags_missed", "answer_key"):
            assert token not in text, f"{token} in {name}"
