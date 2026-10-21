import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from src import app_data, app_ui  # noqa: E402

app_ui.setup("QA Findings Tracker")

reviews, findings, appeals = app_ui.qa()
taxonomy = app_ui.config("config/error_taxonomy.yaml")
f = app_data.findings_with_context(findings, reviews)
f["attribution"] = app_data.attribution(f, taxonomy)

c = st.columns(5)
sev = c[0].multiselect("Severity", ["Critical", "Major", "Minor", "Observation"], default=["Critical", "Major", "Minor", "Observation"])
inv = c[1].multiselect("Investigator", sorted(f["investigator"].unique()), default=sorted(f["investigator"].unique()))
scen = c[2].multiselect("Scenario", sorted(f["scenario"].unique()), default=sorted(f["scenario"].unique()))
status = c[3].multiselect("Status", sorted(f["status"].unique()), default=sorted(f["status"].unique()))
attr = c[4].multiselect("Attribution", sorted(f["attribution"].unique()), default=sorted(f["attribution"].unique()))
view = f[f["severity"].isin(sev) & f["investigator"].isin(inv) & f["scenario"].isin(scen) & f["status"].isin(status)
         & f["attribution"].isin(attr)]

st.caption("Scored findings (Critical, Major, Minor) drive the QA outcome. Observations record process, template, "
           "data or calibration points and do not count against the investigator.")
if view.empty:
    st.info("No findings match the selected filters.")
else:
    view = view.assign(error_text=view["error_code"].map(lambda k: taxonomy["error_codes"].get(k, {}).get("text", "")))
    st.dataframe(view[["finding_id", "case_id", "scenario", "investigator", "question_ref", "severity", "attribution", "error_code",
                       "error_text", "description", "root_cause", "remediation", "owner", "status"]],
                 hide_index=True, width="stretch")

st.subheader("Remediation status")
st.dataframe(f.groupby(["attribution", "severity", "status"]).size().reset_index(name="findings"), hide_index=True)

st.subheader("Appeals")
st.caption(taxonomy["appeals"]["process"])
if appeals.empty:
    st.info("No appeals have been raised. Appeal outcomes are never simulated.")
else:
    st.dataframe(appeals, hide_index=True, width="stretch")
