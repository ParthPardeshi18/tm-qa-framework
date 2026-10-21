import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from src import app_ui  # noqa: E402

app_ui.setup("Typology Library")
st.caption("Reference notes for each scenario, as used in this project's case notes and QA checklist. "
           "Thresholds come from config/scenarios.yaml. These are portfolio notes, not firm guidance.")

scen = app_ui.config("config/scenarios.yaml")["scenarios"]
LIBRARY = {
    "TM01": dict(
        flags=["Repeated cash deposits in a narrow value band within days", "Several depositors or source identifiers paying into one account",
               "Cash volume above declared income or turnover", "Cash followed quickly by onward payments"],
        legit=["Cash-intensive business takings (e.g. retail, hairdressing, trades)", "Sale of personal goods for cash",
               "Savings deposited in instalments"],
        evidence=["Dates, amounts and sources of each deposit", "Whether amounts cluster below a threshold being avoided (the UK has no fixed customer cash-reporting threshold)",
                  "Cash compared with expected activity", "What happened to the cash afterwards"]),
    "TM02": dict(
        flags=["Most credits paid out within one to two days", "Large credit followed by many smaller debits",
               "Funds moved on to new or overseas counterparties", "Activity far above profile"],
        legit=["Bill payments or rent soon after salary", "Purchase completions (e.g. property)", "Business working capital"],
        evidence=["Order of credits and debits (date and time)", "Counterparty identities and relationships",
                  "Economic purpose of the pass-through", "Funding of any outflows that exceed inflows"]),
    "TM03": dict(
        flags=["Material flows to or from watchlist-located counterparties", "Recurring cross-border payments with no stated purpose",
               "Mismatch between jurisdiction exposure and profile"],
        legit=["Family remittances", "Trade with overseas suppliers", "Overseas education or property costs"],
        evidence=["Counterparties and purpose", "Whether the watchlist applies on the transaction dates (it is a single June 2023 snapshot here)",
                  "Sanctions screening of parties: watchlist location alone is not a sanctions match", "Enhanced due diligence considerations"]),
    "TM04": dict(
        flags=["Many unrelated senders in a short window", "Identical payment counts or cadence across senders",
               "Funds accumulated, then moved on in bulk", "Profile inconsistent with receiving third-party funds"],
        legit=["Business customer receipts", "Collections for a club, event or family purpose", "Marketplace seller income"],
        evidence=["Who the senders are and their relationship to the customer", "Whether funds are retained or moved on",
                  "Consistency with stated business or purpose"]),
    "TM05": dict(
        flags=["Payments to many distinct receivers in a short window", "Repeat payees receiving identical counts",
               "Outflows far exceeding visible inflows", "Overseas receivers in several jurisdictions"],
        legit=["Payroll or supplier runs for a business", "Distribution of an estate", "Household bill payments"],
        evidence=["How the outflows were funded", "Receiver identities and purpose", "Relationship to inflows (layering or dispersal)"]),
    "TM06": dict(
        flags=["Sudden step change against the account's own history", "Activity far above profile-expected credits",
               "New repeat counterparties appearing in the spike"],
        legit=["One-off events: inheritance, asset sale, compensation", "Business growth not reflected in KYC", "Change of employment"],
        evidence=["Cause of the change and supporting documentation", "Whether a single event explains the full pattern",
                  "Whether a CDD refresh or risk-rating review is needed"]),
}
st.subheader("Personal Banking vs Business Banking")
st.caption("The same alert can mean different things in each segment. In this sample, 19 cases are Personal Banking and "
           "5 are Business Banking (sole traders and small businesses).")
seg = st.columns(2)
seg[0].markdown(
    "**Personal Banking**\n"
    "- Expected activity comes from declared income: salary, pension or benefits (here, a declared annual band "
    "÷ 12).\n"
    "- Key questions: does the activity fit the occupation and income? Is there a documented source of wealth "
    "(inheritance, property sale, savings)?\n"
    "- Common mule indicators: student, retired or low-income profiles receiving third-party funds and passing them on; "
    "recently opened accounts.\n"
    "- Legitimate explanations to test: family support, a one-off life event, transfers between own accounts."
)
seg[1].markdown(
    "**Business Banking**\n"
    "- Expected activity comes from declared turnover and the nature of the business (here, a turnover band ÷ 12).\n"
    "- Key questions: who owns and controls the business? Are receipts and payments consistent with the stated trade "
    "(suppliers, wages, rent)? Is the business cash-intensive?\n"
    "- Indicators: turnover far above the declared band, no business outgoings, circular payments with the same "
    "counterparties, receipts from unrelated third parties.\n"
    "- Legitimate explanations to test: growth not yet reflected in KYC, seasonal trade, large contracts. Scale alone "
    "can point to a CDD refresh rather than suspicion."
)

st.subheader("Scenario reference")
for sid, entry in LIBRARY.items():
    with st.expander(f"{sid} · {scen[sid]['name']}", expanded=sid == "TM01"):
        params = {k: v for k, v in scen[sid].items() if k != "name"}
        st.caption(f"Rule parameters: {params}")
        cols = st.columns(3)
        for col, title, key in zip(cols, ("Red flags", "Common legitimate explanations", "What a good investigation evidences"),
                                   ("flags", "legit", "evidence")):
            col.markdown(f"**{title}**\n" + "\n".join(f"- {x}" for x in entry[key]))
