"""Data access and calculations for the Streamlit app (Phase 5). No Streamlit imports.

The app reads ONLY the investigator-facing and QA/MI files listed in ALLOWED_FILES.
It never opens answer-key or per-alert evaluation files, and every loaded table is
checked for label columns.
"""

from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
ALLOWED_FILES = {
    "alerts.parquet", "profiles.parquet", "txns_alerted.parquet", "alert_sample.csv",
    "scenario_effectiveness.csv", "typology_coverage.csv",
}
FORBIDDEN_COLUMNS = {"Is_laundering", "Laundering_type", "planted_mismatch", "planted_mismatch_type",
                     "planted_mismatch_note", "window_is_laundering", "window_typologies", "red_flags_missed",
                     "planted_errors"}
NOT_RECORDED = "Not recorded"

WORKED_DIR = ROOT / "qa" / "worked_examples"
SLA_WORKING_DAYS = 5  # portfolio assumption (docs/methodology.md), not a Barclays or statutory standard


def recommendations(eff: pd.DataFrame, findings: pd.DataFrame) -> list[tuple[str, str]]:
    """The three recommendations shared by the MI page and the PDF, with every figure read from the data."""
    e = eff.set_index("scenario")
    low = e[e["laundering_labelled_pct"] < 1].sort_values("laundering_labelled_pct")
    best = e["laundering_labelled_pct"].idxmax()
    low_txt = "; ".join(f"{r.Index} {int(r.alerts):,} alerts at {r.laundering_labelled_pct}%" for r in low.itertuples())
    codes = findings["error_code"].value_counts()
    status = lambda code: "open" if (findings.loc[findings["error_code"] == code, "status"] != "Closed").any() else "closed"  # noqa: E731
    return [
        ("Recalibrate the low-yield scenarios",
         f"{low_txt} laundering-labelled windows, against {e.loc[best, 'laundering_labelled_pct']}% for {best} "
         "(scenario_effectiveness.csv; labels used retrospectively only). Review the thresholds and design of these "
         "scenarios before allocating investigator capacity to their alerts."),
        ("Calibrate outcomes independently before relying on the QA pass rate",
         f"{codes.get('CAL-01', 0)} outcomes are flagged as borderline (CAL-01), and the QA assessments were prepared in "
         "the same AI-assisted workflow as the case notes and validated by the project author. Have an independent "
         "reviewer re-review the borderline cases and blind-review the seeded training set before the pass rate is "
         "relied on."),
        ("Close the case-handling control gaps",
         f"Missing suspicion and disclosure timestamps (PRC-03, {status('PRC-03')}); no escalation-ownership procedure "
         f"(PRC-04, {status('PRC-04')}); case packs listing later-dated alerts (PRC-02, {codes.get('PRC-02', 0)} cases, "
         f"{status('PRC-02')}). Investigator theme: available earlier history not reviewed (SCP-01, "
         f"{codes.get('SCP-01', 0)} case). Make disclosure timestamps mandatory, define escalation ownership, and add "
         "the earlier-alert rule (checklist A3) to investigator guidance."),
    ]


def attribution(findings: pd.DataFrame, taxonomy: dict) -> pd.Series:
    """Investigator error vs process/template weakness vs data limitation vs calibration point."""
    rules = taxonomy["attribution"]
    return findings.apply(lambda f: rules["scored"] if f["scored"] == "True"
                          else rules["by_prefix"][f["error_code"].split("-")[0]], axis=1)


def _working_days(start, end) -> int:
    days = pd.bdate_range(pd.Timestamp(start) + pd.Timedelta(days=1), pd.Timestamp(end))
    return len(days)


def timeliness(cases: list[dict]) -> pd.DataFrame:
    """Case timeliness against the 5-working-day target and disclosure timing against the
    same-working-day target. Missing timestamps are 'Not verifiable', never 'late'."""
    rows = []
    for c in cases:
        if c.get("date_closed"):
            wd = _working_days(c["alert_date"], c["date_closed"])
            status = "Within target" if wd <= SLA_WORKING_DAYS else "Outside target"
        else:
            wd, status = None, "Not verifiable (no case-handling dates)"
        if "suspicion_formed_at" not in c:
            disclosure = "Not recordable (v1 template)" if c["disposition"] == "ESCALATE_SAR" else "Not applicable"
        elif c["disposition"] != "ESCALATE_SAR":
            disclosure = "Not applicable"
        elif c.get("suspicion_formed_at") and c.get("internal_disclosure_at"):
            same_day = str(c["suspicion_formed_at"])[:10] == str(c["internal_disclosure_at"])[:10]
            disclosure = "Same working day" if same_day else "Outside same-day target"
        else:
            disclosure = "Not verifiable (timestamps not recorded)"
        rows.append(dict(case_id=c["case_id"], alert_date=c["alert_date"], date_closed=c.get("date_closed"),
                         working_days_to_close=wd, case_timeliness=status, disposition=c["disposition"],
                         disclosure_timeliness=disclosure))
    return pd.DataFrame(rows)


def case_segments(cases: list[dict]) -> pd.Series:
    return pd.Series({c["case_id"]: c["evidence"]["customer_profile"]["segment"] for c in cases}, name="segment")


def checklist_view(case_id: str, findings: pd.DataFrame, checklist: dict) -> pd.DataFrame:
    """Every checklist question with the QA result recorded for one case. A question with no finding
    is shown as 'No exception recorded', not as a positive confirmation."""
    f = findings[findings["case_id"] == case_id]
    rows = []
    for sid, sec in checklist["sections"].items():
        for qid, q in sec["questions"].items():
            hits = f[f["question_ref"] == qid]
            if hits.empty:
                result = "No exception recorded"
            else:
                result = "; ".join(f"{r.severity} {r.error_code} ({r.finding_id})" for r in hits.itertuples())
            rows.append(dict(question=qid, section=sec["name"], critical=bool(q.get("critical")),
                             requirement=" ".join(q["text"].split()), result=result))
    return pd.DataFrame(rows)


def worked_example_reviews(cases: list[dict], findings: pd.DataFrame) -> pd.DataFrame:
    """Review rows for the worked examples, derived with the same QA engine as the main sample."""
    from src.qa_engine import qa_outcome, quality_score, severity_counts
    rows = []
    for c in cases:
        sev = findings.loc[findings["case_id"] == c["case_id"], "severity"].tolist()
        n = severity_counts(findings, c["case_id"])
        rows.append(dict(case_id=c["case_id"], disposition=c["disposition"], critical=n["Critical"], major=n["Major"],
                         minor=n["Minor"], observations=n["Observation"],
                         qa_outcome=qa_outcome([s for s in sev if s != "Observation"]), quality_score=quality_score(sev),
                         case_note_author="Illustrative variant of CASE-001 (prepared with AI assistance)",
                         reviewer="Illustrative QA (prepared with AI assistance; author review pending)",
                         review_type="Worked example; not part of the sample or QA MI"))
    return pd.DataFrame(rows)


def load_worked_examples() -> tuple[list[dict], pd.DataFrame]:
    """Illustrative, deliberately flawed case-note variants with their QA findings (not part of the sample or MI)."""
    cases = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(WORKED_DIR.glob("WEX-*.yaml"))]
    findings = pd.read_csv(WORKED_DIR / "findings.csv", dtype=str, keep_default_na=False)
    return cases, findings


def _check(df: pd.DataFrame, name: str) -> pd.DataFrame:
    leaked = FORBIDDEN_COLUMNS & set(df.columns)
    if leaked:
        raise ValueError(f"{name} contains label or answer-key columns: {sorted(leaked)}")
    return df


def read_processed(name: str) -> pd.DataFrame:
    if name not in ALLOWED_FILES:
        raise ValueError(f"{name} is not an app-approved file")
    path = PROCESSED / name
    df = pd.read_parquet(path) if name.endswith(".parquet") else pd.read_csv(path)
    return _check(df, name)


def load_txns() -> pd.DataFrame:
    df = read_processed("txns_alerted.parquet")
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df


def load_yaml(relpath: str) -> dict:
    with open(ROOT / relpath, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_cases() -> list[dict]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "cases").glob("CASE-*.yaml"))]


def load_qa() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    read = lambda n: pd.read_csv(ROOT / "qa" / n, dtype=str, keep_default_na=False)  # noqa: E731
    reviews, findings, appeals = read("reviews.csv"), read("findings.csv"), read("appeals.csv")
    reviews["quality_score"] = pd.to_numeric(reviews["quality_score"])
    return reviews, findings, appeals


def account_timeline(txns: pd.DataFrame, account_id: int, end_date, lookback_days: int = 90) -> pd.DataFrame:
    """The account's transactions in [end_date - lookback + 1, end_date], never after end_date
    (txns_alerted can hold later rows from other accounts' histories)."""
    end = pd.Timestamp(end_date).date()
    start = end - timedelta(days=lookback_days - 1)
    own = txns[((txns["Sender_account"] == account_id) | (txns["Receiver_account"] == account_id))
               & (txns["Date"] >= start) & (txns["Date"] <= end)].copy()
    credit = own["Receiver_account"] == account_id
    own["direction"] = credit.map({True: "Credit", False: "Debit"})
    own["counterparty"] = own["Sender_account"].where(credit, own["Receiver_account"])
    own["counterparty_location"] = own["Sender_bank_location"].where(credit, own["Receiver_bank_location"])
    return own.sort_values(["Date", "Time"]).reset_index(drop=True)


def headline_metrics(alerts: pd.DataFrame, reviews: pd.DataFrame) -> dict:
    outcomes = reviews["qa_outcome"].value_counts()
    passed = outcomes.get("Pass", 0) + outcomes.get("Pass with observations", 0)
    return {
        "alerts": len(alerts),
        "alerted_accounts": int(alerts["account_id"].nunique()),
        "cases_reviewed": len(reviews),
        "qa_pass_rate": round(100 * passed / len(reviews), 1) if len(reviews) else None,
        "mean_quality_score": round(reviews["quality_score"].mean(), 1) if len(reviews) else None,
        "fails": int(outcomes.get("Fail", 0)),
    }


def findings_with_context(findings: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    ctx = reviews[["case_id", "scenario", "investigator", "disposition"]]
    out = findings.merge(ctx, on="case_id", how="left", suffixes=("", "_case"))
    out["scenario"] = out["scenario"].fillna("Project-level")
    out["investigator"] = out["investigator"].replace("", pd.NA).fillna(out["investigator_case"]).fillna("—")
    return out.drop(columns=["investigator_case"])


def counts_by(findings: pd.DataFrame, reviews: pd.DataFrame, column: str) -> pd.DataFrame:
    """Findings per scenario or investigator, split scored vs observation; includes zero rows."""
    f = findings_with_context(findings, reviews)
    f = f[f["case_id"] != "PROJECT"]
    f["type"] = f["scored"].map({"True": "Scored", "False": "Observation"})
    table = f.pivot_table(index=column, columns="type", values="finding_id", aggfunc="count", fill_value=0)
    table = table.reindex(sorted(reviews[column].unique()), fill_value=0)
    for col in ("Scored", "Observation"):
        if col not in table:
            table[col] = 0
    return table[["Scored", "Observation"]].reset_index()


def root_cause_pareto(findings: pd.DataFrame) -> pd.DataFrame:
    t = findings.groupby(["root_cause", "severity"]).size().reset_index(name="count")
    order = t.groupby("root_cause")["count"].sum().sort_values(ascending=False).index
    t["root_cause"] = pd.Categorical(t["root_cause"], categories=order, ordered=True)
    return t.sort_values(["root_cause", "severity"]).reset_index(drop=True)


def compact(amount: float) -> str:
    """Short amount for metric tiles: 2,996,202.30 -> '3.00M', 12,795 -> '12.8k'."""
    for div, unit in ((1e6, "M"), (1e3, "k")):
        if abs(amount) >= div:
            return f"{amount / div:.2f}{unit}" if unit == "M" else f"{amount / div:.1f}{unit}"
    return f"{amount:,.0f}"


def display(value) -> str:
    """Human-readable value for possibly-missing case fields."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return NOT_RECORDED
    return str(value)
