import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from src import app_data, app_ui  # noqa: E402

app_ui.setup("Alert Explorer")

alerts = app_ui.alerts().merge(app_ui.profiles()[["account_id", "segment"]], on="account_id", how="left")
alerts["trigger_date"] = alerts["trigger_date"].astype(str)

st.subheader("Alert volumes by scenario")
f1, f2, f3 = st.columns(3)
scen = f1.multiselect("Scenario", sorted(alerts["scenario"].unique()), default=sorted(alerts["scenario"].unique()))
seg = f2.multiselect("Customer segment", sorted(alerts["segment"].dropna().unique()),
                     default=sorted(alerts["segment"].dropna().unique()))
dmin, dmax = alerts["trigger_date"].min(), alerts["trigger_date"].max()
rng = f3.select_slider("Trigger date range", options=sorted(alerts["trigger_date"].unique()), value=(dmin, dmax))
view = alerts[alerts["scenario"].isin(scen) & alerts["segment"].isin(seg)
              & alerts["trigger_date"].between(rng[0], rng[1])]

if view.empty:
    st.info("No alerts match the selected filters.")
else:
    counts = view.groupby(["scenario", "scenario_name"]).size().reset_index(name="alerts")
    st.plotly_chart(px.bar(counts, x="scenario", y="alerts", hover_data=["scenario_name"]), width="stretch")

st.subheader("Scenario effectiveness (retrospective)")
st.caption(
    "Laundering labels were not used to fire alerts. They are used here only afterwards, in aggregate. An alert "
    "counts as laundering-labelled if any monitored transaction of the account inside its alert window is "
    "labelled. Per-alert labels are never shown."
)
st.dataframe(app_ui.effectiveness(), width="stretch", hide_index=True)
with st.expander("Typology coverage (retrospective, aggregate)"):
    st.dataframe(app_ui.typology_coverage(), width="stretch", hide_index=True)

st.subheader("Alert drill-down: transaction timeline")
if view.empty:
    st.info("Select filters that return alerts to drill down.")
else:
    alert_id = st.selectbox("Alert", view.sort_values("alert_id")["alert_id"])
    a = view.set_index("alert_id").loc[alert_id]
    st.write(f"**{a['scenario_name']}** · account {a['account_id']} · window {a['window_start']} to "
             f"{a['trigger_date']} · {a['trigger_detail']}")
    tl = app_data.account_timeline(app_ui.txns(), int(a["account_id"]), a["trigger_date"], 90)
    if tl.empty:
        st.info("No transactions available for this account in the 90-day lookback.")
    else:
        fig = px.scatter(tl, x="Date", y="Amount", color="direction", symbol="Payment_type",
                         hover_data=["counterparty", "counterparty_location", "Payment_type"])
        fig.add_vrect(x0=str(a["window_start"]), x1=str(a["trigger_date"]), fillcolor="orange", opacity=0.15,
                      line_width=0, annotation_text="alert window")
        st.plotly_chart(fig, width="stretch")
        st.caption("90-day lookback ending on the trigger date; later transactions are excluded. "
                   "Amounts are in dataset units (GBP assumed, unverified).")
