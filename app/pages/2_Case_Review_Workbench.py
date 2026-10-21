import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from src import app_data, app_ui  # noqa: E402
from src.case_prep import DISCLOSURE_FIELDS  # noqa: E402

app_ui.setup("Case Review Workbench")
st.markdown(
    "QA assesses the **investigation**, not only the transactions. Suspicious-looking activity can be well "
    "investigated, and a correct disposition can still rest on an unsupported investigation. For each case, compare "
    "the evidence with the investigator's note, then check how QA recorded each checklist requirement."
)

case_set = st.radio("Case set", ["Sample cases (24)", "Worked QA examples (3, illustrative)"], horizontal=True)
reviews, findings, _ = app_ui.qa()
taxonomy = app_ui.config("config/error_taxonomy.yaml")
if case_set.startswith("Sample"):
    cases = {c["case_id"]: c for c in app_ui.cases()}
else:
    wex_cases, findings = app_ui.worked_examples()
    cases = {c["case_id"]: c for c in wex_cases}
    reviews = app_data.worked_example_reviews(wex_cases, findings)
    st.warning("Illustrative worked examples: deliberately flawed variants of CASE-001 that share its real evidence. "
               "They show a Critical fail, a Major fail despite a correct disposition, and a Minor-only pass in which a "
               "data limitation is not penalised. They are not part of the sample or the QA MI. Prepared with AI "
               "assistance; review by the project author is pending.")
reviews = reviews.set_index("case_id")

cid = st.selectbox("Case", list(cases), format_func=lambda k: f"{k} · {cases[k]['alert_id']} · {cases[k]['scenario']}")
c, r, ev = cases[cid], reviews.loc[cid], cases[cid]["evidence"]

st.caption(f"Case note author: **{r['case_note_author']}** · QA reviewer: **{r['reviewer']}** · {r['review_type']}")

left, right = st.columns([1, 2])
with left:
    st.subheader("Customer profile (synthetic KYC)")
    p = ev["customer_profile"]
    st.markdown(
        f"- **Segment:** {p['segment']}\n- **Occupation / sector:** {p['occupation_or_sector']}\n"
        f"- **Declared income / turnover:** {p['declared_income_or_turnover_band']}\n"
        f"- **Expected monthly credits:** {p['expected_monthly_credits_min_gbp']:,}-{p['expected_monthly_credits_max_gbp']:,}\n"
        f"- **Account opened:** {p['account_open_date']}\n- **Risk rating:** {p['customer_risk_rating']}\n"
        f"- **KYC flags on file:** PEP {'Yes' if p['pep_flag'] else 'No'}, adverse media "
        f"{'Yes' if p['adverse_media_flag'] else 'No'} (profile flags, not screening results)"
    )
    st.subheader("Alert")
    st.markdown(f"**{c['scenario']}** · investigator {c['investigator']}  \n"
                f"Window {ev['alert']['window_start']} to {ev['alert']['trigger_date']}  \n{ev['alert']['trigger_detail']}")
with right:
    st.subheader("Evidence summary")
    rp, la = ev["review_period"], ev["lookback_activity"]
    st.markdown(f"Review period {rp['start']} to {rp['end']} ({rp['days']} days"
                f"{', cut short by the dataset start' if rp['truncated_by_dataset_start'] else ''}).")
    m = st.columns(4)
    m[0].metric("Credits", app_data.compact(la["credits_total"]), f"{la['credits_count']} txns", delta_color="off",
                help=f"{la['credits_total']:,.2f}")
    m[1].metric("Debits", app_data.compact(la["debits_total"]), f"{la['debits_count']} txns", delta_color="off",
                help=f"{la['debits_total']:,.2f}")
    m[2].metric("Senders", la["distinct_senders"])
    m[3].metric("Receivers", la["distinct_receivers"])
    tl = app_data.account_timeline(app_ui.txns(), c["account_id"], rp["end"], rp["days"])
    if tl.empty:
        st.info("No transactions in the review period.")
    else:
        st.plotly_chart(px.scatter(tl, x="Date", y="Amount", color="direction", symbol="Payment_type",
                                   hover_data=["counterparty", "counterparty_location"]), width="stretch")
    st.markdown("**Top counterparties by value**")
    st.dataframe(pd.DataFrame(ev["top_counterparties_by_value"]), hide_index=True, width="stretch")
    others = ev["other_alerts_on_account"]
    st.markdown("**Other alerts on the account (on or before the case date):** "
                + (", ".join(f"{o['alert_id']} ({o['trigger_date']})" for o in others) or "none"))

st.divider()
st.subheader("Investigator case note")
st.markdown(f"**Customer summary.** {c['customer_summary']}")
st.markdown(f"**Activity reviewed.** {c['activity_reviewed']}")
st.markdown("**Red flags identified**")
for flag in c["red_flags_identified"] or []:
    st.markdown(f"- {flag}")
if not c["red_flags_identified"]:
    st.write(app_data.NOT_RECORDED)
for label, key in (("Source of funds / wealth", "source_of_funds"), ("Screening and adverse media", "screening_adverse_media"),
                   ("Rationale", "rationale"), ("Escalation decision", "escalation_decision")):
    with st.expander(label, expanded=key == "rationale"):
        st.write(app_data.display(c[key]))
d = st.columns(3)
d[0].metric("Disposition", app_data.display(c["disposition"]))
d[1].metric("Date opened", app_data.display(c["date_opened"]))
d[2].metric("Date closed", app_data.display(c["date_closed"]))
if any(k in c for k in DISCLOSURE_FIELDS):
    st.markdown("**Disclosure tracking:** " + " · ".join(f"{k}: {app_data.display(c.get(k))}" for k in DISCLOSURE_FIELDS))
    st.caption("Missing timestamps mean timeliness cannot be verified; they do not prove the disclosure was late.")
else:
    st.caption("This case uses the v1 template, which has no disclosure-tracking fields.")

st.divider()
st.subheader("QA outcome")
q = st.columns(3)
q[0].metric("QA outcome", r["qa_outcome"])
q[1].metric("Quality score", int(r["quality_score"]))
q[2].metric("Scored findings", int(r["critical"]) + int(r["major"]) + int(r["minor"]))
case_findings = findings[findings["case_id"] == cid]
if case_findings.empty:
    st.info("No findings or observations recorded for this case.")
else:
    case_findings = case_findings.assign(attribution=app_data.attribution(case_findings, taxonomy))
    st.dataframe(case_findings[["finding_id", "question_ref", "severity", "attribution", "error_code", "description",
                                "remediation", "status"]], hide_index=True, width="stretch")
    st.caption("Attribution separates investigator errors (scored) from process or template weaknesses, data limitations "
               "and calibration points (recorded, not scored). Investigators are not penalised for information that "
               "does not exist in the data.")

checklist = app_ui.config("config/qa_checklist.yaml")
n_questions = sum(len(sec["questions"]) for sec in checklist["sections"].values())
with st.expander(f"QA checklist view ({n_questions} requirements)"):
    st.caption("'No exception recorded' means QA raised no finding against the requirement; it is not a separate "
               "positive sign-off. Critical requirements decide the outcome on their own.")
    st.dataframe(app_data.checklist_view(cid, findings, checklist),
                 hide_index=True, width="stretch")
