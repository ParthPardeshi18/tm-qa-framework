from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import app_data

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / "app" / "Home.py"] + sorted((ROOT / "app" / "pages").glob("*.py"))
KEY_FILES = ["alert_evaluation", "alert_sample_key", "profiles_answer_key", "answer_key", "training/"]


def test_app_reads_only_approved_files_and_never_key_files():
    sources = [p.read_text(encoding="utf-8") for p in PAGES] + [
        (ROOT / "src" / n).read_text(encoding="utf-8") for n in ("app_data.py", "app_ui.py")]
    for text in sources:
        for key in KEY_FILES:
            assert key not in text
    with pytest.raises(ValueError):
        app_data.read_processed("alert_evaluation.parquet")


def test_loaded_tables_have_no_label_columns():
    for name in app_data.ALLOWED_FILES:
        df = app_data.read_processed(name)
        assert not app_data.FORBIDDEN_COLUMNS & set(df.columns), name
    with pytest.raises(ValueError):
        app_data._check(pd.DataFrame({"Is_laundering": [1]}), "x")


def test_headline_metrics_reconcile_with_records():
    alerts = app_data.read_processed("alerts.parquet")
    reviews, findings, _ = app_data.load_qa()
    m = app_data.headline_metrics(alerts, reviews)
    assert m["alerts"] == len(alerts) and m["cases_reviewed"] == 24
    outcomes = reviews["qa_outcome"].value_counts()
    assert m["fails"] == outcomes.get("Fail", 0)
    assert m["qa_pass_rate"] == round(100 * (24 - m["fails"]) / 24, 1)
    assert m["mean_quality_score"] == round(reviews["quality_score"].mean(), 1)


def test_account_timeline_never_includes_rows_after_end_date():
    txns = app_data.load_txns()
    case = {c["case_id"]: c for c in app_data.load_cases()}["CASE-007"]  # account has later rows in txns_alerted
    rp = case["evidence"]["review_period"]
    tl = app_data.account_timeline(txns, case["account_id"], rp["end"], rp["days"])
    assert str(tl["Date"].max()) <= rp["end"] and str(tl["Date"].min()) >= rp["start"]
    la = case["evidence"]["lookback_activity"]
    assert (tl["direction"] == "Credit").sum() == la["credits_count"]
    assert (tl["direction"] == "Debit").sum() == la["debits_count"]


def test_counts_by_includes_every_value_and_reconciles():
    reviews, findings, _ = app_data.load_qa()
    for col in ("scenario", "investigator"):
        t = app_data.counts_by(findings, reviews, col)
        assert sorted(t[col]) == sorted(reviews[col].unique())
        case_findings = findings[findings["case_id"] != "PROJECT"]
        assert t["Scored"].sum() + t["Observation"].sum() == len(case_findings)


def test_root_cause_pareto_totals_all_findings():
    _, findings, _ = app_data.load_qa()
    assert app_data.root_cause_pareto(findings)["count"].sum() == len(findings)


def test_compact_amounts():
    assert app_data.compact(2996202.30) == "3.00M"
    assert app_data.compact(12795.02) == "12.8k"
    assert app_data.compact(636.77) == "637"
    assert app_data.compact(0) == "0"


def test_display_handles_missing_values():
    for missing in (None, "", float("nan")):
        assert app_data.display(missing) == app_data.NOT_RECORDED
    assert app_data.display("ESCALATE_L2") == "ESCALATE_L2"


def test_no_case_timeline_shows_transactions_after_alert_date():
    txns = app_data.load_txns()
    for c in app_data.load_cases():
        rp = c["evidence"]["review_period"]
        tl = app_data.account_timeline(txns, c["account_id"], rp["end"], rp["days"])
        assert tl.empty or str(tl["Date"].max()) <= c["alert_date"], c["case_id"]
        assert len(tl) == c["evidence"]["lookback_activity"]["transactions"], c["case_id"]


def test_app_code_uses_no_deprecated_arguments():
    for p in PAGES:
        assert "use_container_width" not in p.read_text(encoding="utf-8"), p.name


def test_workbench_renders_every_case():
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "2_Case_Review_Workbench.py"), default_timeout=120).run()
    options = at.selectbox[0].options
    assert len(options) == 24
    for opt in options:
        at.selectbox[0].set_value(opt.split(" · ")[0]).run()
        assert not at.exception, opt
        assert any(m.label == "QA outcome" for m in at.metric)


def test_alert_explorer_empty_filter_state():
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "1_Alert_Explorer.py"), default_timeout=120).run()
    at.multiselect[0].set_value([]).run()
    assert not at.exception
    assert any("No alerts match" in i.value for i in at.info)


def test_findings_tracker_empty_filter_state():
    at = AppTest.from_file(str(ROOT / "app" / "pages" / "3_QA_Findings_Tracker.py"), default_timeout=120).run()
    at.multiselect[0].set_value([]).run()
    assert not at.exception
    assert any("No findings match" in i.value for i in at.info)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_renders_without_exception_and_shows_disclaimer(page):
    at = AppTest.from_file(str(page), default_timeout=120).run()
    assert not at.exception, at.exception
    from src.app_ui import REVIEW_STATEMENT, SHORT_NOTE
    shown = [e.value for e in at.info] + [e.value for e in at.caption]
    expected = REVIEW_STATEMENT if page.name == "Home.py" else SHORT_NOTE
    assert any(expected in text for text in shown), page.name
