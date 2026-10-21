import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from src import app_data, app_ui  # noqa: E402

app_ui.setup("QA MI Dashboard")


def chart(fig, data, label):
    """Chart plus an accessible data table."""
    st.plotly_chart(fig, width="stretch")
    with st.expander(f"View data: {label}"):
        st.dataframe(data, hide_index=True, width="stretch")


reviews, findings, _ = app_ui.qa()
cases = app_ui.cases()
taxonomy = app_ui.config("config/error_taxonomy.yaml")
cfg = taxonomy["quality_score"]
m = app_data.headline_metrics(app_ui.alerts(), reviews)
reviews = reviews.join(app_data.case_segments(cases), on="case_id")
findings = findings.assign(attribution=app_data.attribution(findings, taxonomy))
tl = app_data.timeliness(cases)

c = st.columns(4)
c[0].metric("Cases reviewed", m["cases_reviewed"])
c[1].metric("Pass rate", f"{m['qa_pass_rate']}%", help="Pass plus Pass with observations")
c[2].metric("Fails", m["fails"])
c[3].metric("Mean quality score", m["mean_quality_score"])
st.caption(f"Outcome: Critical or Major → Fail; Minor only → Pass with observations; none → Pass. Quality score = "
           f"max({cfg['floor']}, {cfg['base']} − deductions {cfg['deductions']}). The score is for trend MI only and never "
           "overrides the outcome.")
st.info("Interpretation: the QA assessments were prepared in the same AI-assisted workflow as the case notes and "
        "validated by the project author, not by an independent or blind reviewer. These figures show the framework "
        "working; they are not a measure of investigator performance. The Case Review Workbench's worked examples "
        "show Fail outcomes.")

st.subheader("Outcomes and dispositions")
a, b = st.columns(2)
with a:
    t = reviews["qa_outcome"].value_counts().rename_axis("qa_outcome").reset_index(name="cases")
    chart(px.bar(t, x="qa_outcome", y="cases", title="QA outcomes"), t, "QA outcomes")
with b:
    t = reviews.groupby(["segment", "disposition"]).size().reset_index(name="cases")
    chart(px.bar(t, x="disposition", y="cases", color="segment", barmode="group",
                 title="Dispositions by segment (Personal vs Business Banking)"), t, "dispositions by segment")

st.subheader("Findings: what failed, and whose issue it is")
a, b = st.columns(2)
with a:
    t = findings.groupby(["attribution", "severity"]).size().reset_index(name="findings")
    chart(px.bar(t, x="attribution", y="findings", color="severity", title="Findings by attribution and severity"),
          t, "findings by attribution")
with b:
    t = findings["error_code"].value_counts().rename_axis("error_code").reset_index(name="findings")
    t["description"] = t["error_code"].map(lambda k: taxonomy["error_codes"][k]["text"])
    chart(px.bar(t, x="error_code", y="findings", hover_data=["description"], title="Findings by error code"),
          t, "findings by error code")
st.caption("Only investigator errors are scored. Process or template weaknesses, data limitations and calibration "
           "points are tracked for the process owner and do not count against the investigator.")

st.subheader("Investigator and scenario view")
a, b = st.columns(2)
for col, name in ((a, "investigator"), (b, "scenario")):
    with col:
        t = reviews.groupby(name).agg(cases=("case_id", "size"), mean_score=("quality_score", "mean"),
                                      fails=("qa_outcome", lambda s: int((s == "Fail").sum()))).round(1).reset_index()
        counts = app_data.counts_by(findings, reviews, name)
        t = t.merge(counts, on=name)
        chart(px.bar(t, x=name, y=["Scored", "Observation"], barmode="stack", title=f"Findings by {name}",
                     hover_data=["mean_score", "fails"]), t, f"by {name}")
st.caption("Investigator-level patterns need several scored findings per investigator. With 3 scored findings, all in "
           "one case, no investigator pattern can be inferred from this sample.")

st.subheader("Timeliness and tolerance")
st.caption(f"Targets (portfolio assumptions, not Barclays standards): case closed within {app_data.SLA_WORKING_DAYS} "
           "working days of the alert; internal disclosure on the same working day as suspicion is formed. The statutory "
           "test where POCA s.330 applies is 'as soon as is practicable'. Missing timestamps are reported as not "
           "verifiable, never as late.")
a, b = st.columns(2)
a.dataframe(tl["case_timeliness"].value_counts().rename_axis("case timeliness").reset_index(name="cases"),
            hide_index=True, width="stretch")
b.dataframe(tl["disclosure_timeliness"].value_counts().rename_axis("disclosure timeliness").reset_index(name="cases"),
            hide_index=True, width="stretch")
outside = tl[(tl["case_timeliness"] == "Outside target") | (tl["disclosure_timeliness"] == "Outside same-day target")]
if outside.empty:
    unverifiable = int(tl["case_timeliness"].str.startswith("Not verifiable").sum())
    st.success(f"No case is recorded outside tolerance. {unverifiable} cases cannot be verified because no case-handling "
               "timestamps exist (PRC-03).")
else:
    st.error(f"{len(outside)} case(s) outside tolerance.")
    st.dataframe(outside, hide_index=True, width="stretch")

st.subheader("Root causes and remediation")
a, b = st.columns(2)
with a:
    pareto = app_data.root_cause_pareto(findings)
    chart(px.bar(pareto, x="root_cause", y="count", color="severity", title="Root-cause Pareto"), pareto, "root causes")
with b:
    t = findings.groupby(["attribution", "status"]).size().reset_index(name="findings")
    st.markdown("**Remediation status**")
    st.dataframe(t, hide_index=True, width="stretch")

st.subheader("Recommendations")
for i, (title, text) in enumerate(app_data.recommendations(app_ui.effectiveness(), findings), 1):
    st.markdown(f"**{i}. {title}.** {text}")
