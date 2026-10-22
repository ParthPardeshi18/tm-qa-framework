import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from src import app_data, app_ui  # noqa: E402

app_ui.setup("Transaction Monitoring QA Framework", full_disclaimer=True)

st.markdown(
    "This project simulates how a Transaction Monitoring **Quality Assurance** team checks completed "
    "AML investigations. It looks at whether financial crime risk was correctly identified, "
    "investigated, evidenced and concluded. The skill on show is reviewer judgement, not modelling."
)
st.markdown(
    "**Pipeline:**  Detect (6 rule-based scenarios on 9.5M synthetic transactions) → "
    "Investigate (24 sampled alerts, case notes) → Quality-assure (checklist, severity taxonomy, outcome "
    "rules) → Report (QA MI and recommendations)"
)

reviews, findings, _ = app_ui.qa()
m = app_data.headline_metrics(app_ui.alerts(), reviews)
c = st.columns(3)
c[0].metric("Alerts", f"{m['alerts']:,}")
c[1].metric("Alerted accounts", f"{m['alerted_accounts']:,}")
c[2].metric("Cases reviewed", m["cases_reviewed"])
c = st.columns(3)
c[0].metric("QA pass rate", f"{m['qa_pass_rate']}%", help="Includes Pass with observations")
c[1].metric("Fails", m["fails"])
c[2].metric("Mean quality score", m["mean_quality_score"])

st.caption(
    "Read the pass rate with care: the QA assessments were prepared in the same workflow as the case "
    "notes and validated by the project author, not by an independent or blind reviewer. See **Methodology**."
)
st.markdown(
    "Use the pages in the sidebar: Alert Explorer, Case Review Workbench, QA Findings Tracker, "
    "QA MI Dashboard, Typology Library and Methodology."
)
