"""Documentation figures must match the stored QA and effectiveness records."""

import re
from pathlib import Path

import pandas as pd

from src import app_data

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
METHOD = (ROOT / "docs" / "methodology.md").read_text(encoding="utf-8")


def facts():
    reviews, findings, _ = app_data.load_qa()
    o, d = reviews["qa_outcome"].value_counts(), reviews["disposition"].value_counts()
    return dict(
        obs=int((findings["scored"] == "False").sum()),
        mean=round(reviews["quality_score"].mean(), 1),
        fail=o.get("Fail", 0), pwo=o.get("Pass with observations", 0), passed=o.get("Pass", 0),
        sar=d.get("ESCALATE_SAR", 0), l2=d.get("ESCALATE_L2", 0), close=d.get("CLOSE_NO_FURTHER_ACTION", 0),
    )


def test_observation_count_is_15_and_documented_consistently():
    f = facts()
    assert f["obs"] == 15
    assert f"**Observations (not scored):** {f['obs']}" in README
    assert f"Observations, not scored ({f['obs']} in total)" in METHOD
    for text in (README, METHOD):
        # 17 may appear only in the explicit correction note.
        assert not re.search(r"\b17 (in total|observations)", text)


def test_outcomes_dispositions_and_mean_score_match_records():
    f = facts()
    assert f"{f['fail']} Fail, {f['pwo']} Pass with observations" in README and f"{f['passed']} Pass." in README
    assert f"{f['sar']} internal disclosures to the MLRO, {f['l2']} L2 referrals, {f['close']} closures" in README
    assert f"mean {f['mean']}" in README and f"a mean of {f['mean']}" in METHOD


def test_readme_attribution_and_timeliness_match_records():
    reviews, findings, _ = app_data.load_qa()
    attr = app_data.attribution(findings, app_data.load_yaml("config/error_taxonomy.yaml")).value_counts()
    line = (f"investigator error {attr['Investigator error']}, process or template weakness "
            f"{attr['Process or template weakness']}, calibration point {attr['Calibration point']}, data limitation "
            f"{attr['Data limitation']}")
    assert line in README and line in METHOD
    tl = app_data.timeliness(app_data.load_cases())["case_timeliness"].value_counts()
    assert (f"{tl.get('Within target', 0)} within target, {tl.get('Not verifiable (no case-handling dates)', 0)} not "
            f"verifiable (no timestamps), {tl.get('Outside target', 0)} outside tolerance") in README


def test_checklist_size_stated_correctly_everywhere():
    n = sum(len(s["questions"]) for s in app_data.load_yaml("config/qa_checklist.yaml")["sections"].values())
    assert f"{n}-question checklist" in README and f"{n} questions in sections A–G" in METHOD
    for rel in ("README.md", "docs/methodology.md", "docs/PROJECT_PLAN.md", "docs/role_mapping.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if rel.endswith("PROJECT_PLAN.md"):  # only the as-built resume section; §4a keeps the original design target
            text = text.split("**Accurate version (as built):**")[1].split("**Original draft")[0]
            assert f"{n}-question checklist" in text
        wrong = [k for k in range(10, 30) if k != n and re.search(rf"\b{k}[- ]question", text)]
        assert not wrong, f"{rel} states a checklist size of {wrong}"


def test_readme_effectiveness_table_matches_csv():
    eff = pd.read_csv(ROOT / "data" / "processed" / "scenario_effectiveness.csv")
    for r in eff.itertuples():
        row = next(line for line in README.splitlines() if line.startswith(f"| {r.scenario} "))
        assert f"| {r.alerts:,} |" in row and f"| {r.laundering_labelled_pct}% |" in row, r.scenario
    assert f"{eff['alerts'].sum():,} alerts" in README


PUBLIC_FILES = ["README.md", "docs/methodology.md", "docs/PROJECT_PLAN.md", "training/README.md", "src/app_ui.py",
                "src/app_data.py", "src/report.py"] + [f"app/{p}" for p in ("Home.py",)] + \
               [str(p.relative_to(ROOT)) for p in (ROOT / "app" / "pages").glob("*.py")] + \
               [str(p.relative_to(ROOT)) for p in (ROOT / "training" / "seeded_cases").glob("*.yaml")]


def test_review_statement_is_consistent_and_ai_generated_wording_removed():
    from src.app_ui import REVIEW_STATEMENT
    for text in (README, METHOD):
        assert REVIEW_STATEMENT in text
    for rel in PUBLIC_FILES:
        assert "AI-generated" not in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_authorship_disclosed_and_no_unsupported_claims():
    plan = (ROOT / "docs" / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert "Superseded" in plan and "Do not claim" in plan
    for text in (README, METHOD):
        assert not re.search(r"blind review identified \d", text)
        assert "independently validated" not in text
