import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from src import app_ui  # noqa: E402

app_ui.setup("Methodology")

st.markdown(
    f"**Authorship and review.** {app_ui.REVIEW_STATEMENT} The author reviewed the transaction evidence, "
    "validated the figures, checked the investigative reasoning and the QA findings, and confirmed that the "
    "conclusions are consistent with the documented methodology. This is the author's own validation, not an "
    "independent assessment by a second reviewer. No blind review has been performed and no blind-review hit "
    "rate is claimed."
)
st.markdown(
    "**Data.** SAML-D synthetic transaction dataset (Oztas et al., 2023), about 9.5M transactions. "
    "The currency of `Amount` is unverified (GBP assumed). Synthetic customer profiles are generated "
    "deterministically from account IDs."
)

root = Path(__file__).resolve().parents[2]
for title, rel in (("Full methodology (docs/methodology.md)", "docs/methodology.md"),
                   ("Scenario effectiveness notes (docs/scenario_effectiveness.md)", "docs/scenario_effectiveness.md"),
                   ("EDA notes (docs/eda_notes.md)", "docs/eda_notes.md")):
    with st.expander(title, expanded=title.startswith("Full")):
        path = root / rel
        st.markdown(path.read_text(encoding="utf-8") if path.exists() else "_File not found._")

with st.expander("QA checklist (config/qa_checklist.yaml)"):
    for sid, sec in app_ui.config("config/qa_checklist.yaml")["sections"].items():
        st.markdown(f"**{sid}. {sec['name']}**")
        for qid, q in sec["questions"].items():
            crit = " **[critical]**" if q.get("critical") else ""
            st.markdown(f"- {qid}{crit} ({q['severity_if_no']} if No): {' '.join(q['text'].split())}")
