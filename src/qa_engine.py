"""QA scoring (Phase 4): derive each case's QA outcome and quality score from its findings.

    python -m src.qa_engine    # recompute the derived columns of qa/reviews.csv from qa/findings.csv

Rules live in config/error_taxonomy.yaml.
- Outcome (categorical, decisive): Critical or Major means Fail; Minor only means
  Pass with observations; no scored findings means Pass. Observations are not scored.
- Quality score (MI only): max(floor, base - sum of severity deductions). The score
  is reported beside the outcome and never changes it.
"""

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "qa"
CONFIG_DIR = ROOT / "config"
SCORED = ["Critical", "Major", "Minor"]
DERIVED_COLUMNS = ["critical", "major", "minor", "observations", "qa_outcome", "quality_score"]


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def qa_outcome(severities) -> str:
    found = set(severities)
    if found & {"Critical", "Major"}:
        return "Fail"
    if "Minor" in found:
        return "Pass with observations"
    return "Pass"


def quality_score(severities, config=None) -> int:
    """Weighted score in [floor, base]. Unknown severities raise KeyError."""
    cfg = config or load_yaml("error_taxonomy.yaml")["quality_score"]
    deduction = sum(cfg["deductions"][s] for s in severities)
    return max(cfg["floor"], cfg["base"] - deduction)


def severity_counts(findings: pd.DataFrame, case_id: str) -> dict:
    sev = findings.loc[findings["case_id"] == case_id, "severity"]
    return {s: int((sev == s).sum()) for s in SCORED + ["Observation"]}


def load_qa():
    findings = pd.read_csv(QA_DIR / "findings.csv", dtype=str, keep_default_na=False)
    reviews = pd.read_csv(QA_DIR / "reviews.csv", dtype=str, keep_default_na=False)
    return reviews, findings


def derive(reviews: pd.DataFrame, findings: pd.DataFrame) -> pd.DataFrame:
    """Return reviews with the derived columns recomputed from findings."""
    cfg = load_yaml("error_taxonomy.yaml")["quality_score"]
    out = reviews.copy()
    for i, cid in out["case_id"].items():
        n = severity_counts(findings, cid)
        case_sev = findings.loc[findings["case_id"] == cid, "severity"].tolist()
        scored = [s for s in case_sev if s in SCORED]
        out.loc[i, ["critical", "major", "minor", "observations"]] = [
            str(n["Critical"]), str(n["Major"]), str(n["Minor"]), str(n["Observation"])]
        out.loc[i, "qa_outcome"] = qa_outcome(scored)
        out.loc[i, "quality_score"] = str(quality_score(case_sev, cfg))
    return out


def main() -> None:
    reviews, findings = load_qa()
    out = derive(reviews, findings)
    cols = [c for c in reviews.columns if c not in DERIVED_COLUMNS]
    ordered = cols[:5] + DERIVED_COLUMNS + cols[5:]  # case_id..disposition, then derived, then metadata
    out[ordered].to_csv(QA_DIR / "reviews.csv", index=False)
    print(out[["case_id", "qa_outcome", "quality_score"]].to_string(index=False))


if __name__ == "__main__":
    main()
