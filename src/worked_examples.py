"""Illustrative QA worked examples: deliberately flawed variants of CASE-001.

    python -m src.worked_examples    # writes qa/worked_examples/WEX-0*.yaml and findings.csv

They show how a QA reviewer separates suspicious-looking activity from a poorly
investigated case. All three share CASE-001's real evidence block; only the
investigator's judgement fields differ. They are NOT part of the 24-case sample,
the QA MI, or the seeded training set. Review by the project author is pending.
"""

import pandas as pd
import yaml

from src.app_data import ROOT, WORKED_DIR

HEADER = ("# ILLUSTRATIVE QA WORKED EXAMPLE - a deliberately flawed variant of CASE-001 (synthetic data).\n"
          "# Not part of the 24-case sample, the QA MI or the seeded training set.\n"
          "# Review by the project author is pending.\n")

SCREEN_OK = ("No screening results are available in the simulation dataset; screening outcomes cannot be verified. "
             "The PEP No and adverse media No values are KYC flags on file, not screening results.\n")

VARIANTS = {
    "WEX-01": dict(
        title="Suspicious activity, poorly investigated, wrongly closed",
        red_flags_identified=["Three cash deposits totalling 12,795.02 between 8 and 14 February 2023."],
        source_of_funds="The customer is retired; the credits are likely to be pension lump sums and savings "
                        "transfers, which is consistent with retirement.\n",
        screening_adverse_media="Screening clear. No PEP or adverse media.\n",
        rationale="The TM01 alert was triggered by three cash deposits, but the amounts were uneven, so this is "
                  "not structuring. The customer is long-standing, rated Low risk and has no PEP or adverse-media "
                  "flags. The other credits and debits are normal activity for a customer managing retirement funds. "
                  "No further action is required.\n",
        disposition="CLOSE_NO_FURTHER_ACTION",
        escalation_decision="No escalation required.\n",
    ),
    "WEX-02": dict(
        title="Correct outcome, unsupported investigation",
        red_flags_identified=["Unusual account activity.", "Cash deposits."],
        source_of_funds="Not assessed.\n",
        screening_adverse_media=SCREEN_OK,
        rationale="The activity looks suspicious, so an internal disclosure is made.\n",
        disposition="ESCALATE_SAR",
        escalation_decision="Internal disclosure to the MLRO.\n",
    ),
    "WEX-03": dict(
        title="Sound investigation with a minor gap; data limitation not penalised",
        # Starts from the author's CASE-001 note and closes two of its three findings (CP-02, ACT-01).
        escalation_addendum=(
            "\nMaterial counterparties for the disclosure: 7728874438 (13 debits, 530,738.12), 7255191021 (12 credits, "
            "504,530.14), 6775420017 (13 debits, 474,375.32), 8097288482 (12 credits, 343,048.16) and 8541211325 "
            "(12 credits, 293,633.95). Outstanding screening of the customer and these counterparties, and "
            "verification of their relationship to the customer, are passed to the MLRO for determination.\n"),
    ),
}

FINDINGS = [
    # WEX-01: four separate failures. OUT-01 is the outcome; the others are distinct evidence failures that
    # caused it, so each is recorded once (no duplication of the same error).
    ("WEX-01", "E2", "Critical", "OUT-01", "Closed with no further action although the record shows 2,996,202.30 of credits and "
     "3,446,939.33 of debits in 90 days against expected monthly credits of up to 833, 572,742.09 of cross-border outflows "
     "and an unexplained funding gap of 450,737.03. On this record, suspicion should have been formed and disclosed.",
     "Knowledge gap", "Reopen the case and make a prompt internal disclosure to the MLRO; coaching on assessing activity "
     "against the customer profile; sample-check the investigator's next five cases."),
    ("WEX-01", "C1", "Major", "RF-01", "Material red flags not identified: activity far above the profile, 230 credits "
     "(2,981,759.88) concentrated in one 30-day block, debits to 50 receivers, cross-border outflows including "
     "watchlist locations, and prior TM04 and TM05 alerts. Only the alert trigger was considered.",
     "Knowledge gap", "Coaching: analyse the whole account (incoming and outgoing flows), not only the triggering activity."),
    ("WEX-01", "D1", "Major", "SOF-01", "Source of funds asserted as pension and savings with no supporting evidence; an "
     "assumption about missing information was recorded as if it were a finding.",
     "Knowledge gap", "Record source of funds as unresolved when it is not evidenced, and treat an unresolved source "
     "of funds as a factor in the disposition."),
    ("WEX-01", "D2", "Major", "SCR-01", "Screening recorded as clear although no screening results exist; the PEP and "
     "adverse-media values are KYC flags on file, not screening outcomes.",
     "Procedure not followed", "Never record screening as clear without evidence; use the standard wording for "
     "unavailable results."),
    # WEX-02: the disposition is supported by the record, but the investigation is not evidenced: Fail on Majors.
    ("WEX-02", "E1", "Major", "RAT-01", "The rationale does not state the grounds for suspicion or weigh the evidence. The "
     "outcome (disclosure) is supported by the record, but the note gives the MLRO nothing to assess.",
     "Knowledge gap", "Coaching on articulating the grounds for suspicion (what, who, why) in line with good SAR practice."),
    ("WEX-02", "C1", "Major", "RF-01", "Red flags are generic and not tied to evidence: no figures, counterparties, "
     "jurisdictions or prior alerts.", "Knowledge gap", "Tie every red flag to a specific fact and figure."),
    ("WEX-02", "D1", "Major", "SOF-01", "Source of funds and source of wealth not assessed despite activity far above "
     "the profile (credits of 2,996,202.30 against expected monthly credits of up to 833).",
     "Knowledge gap", "Assess source of funds and wealth whenever activity is inconsistent with the profile."),
    # WEX-03: Minor only, plus a data limitation that is correctly not penalised.
    ("WEX-03", "A3", "Minor", "SCP-01", "Available earlier history (2022-10-07 to 2022-11-16) not reviewed despite the "
     "self-identified funding gap of 450,737.03 and a prior TM05 alert at the lookback boundary; the gap is documented "
     "and routed for follow-up.", "Not determinable",
     "Review available history before closure when it could materially affect the assessment, or justify why not."),
    ("WEX-03", "D2", "Observation", "DAT-01", "No screening results exist in the simulation dataset. The note records "
     "this correctly and does not treat screening as clear, so this is a data limitation, not an investigator error.",
     "System/data limitation", "None for the investigator; screening data would be needed for a real review."),
]


def build() -> None:
    base_text = (ROOT / "cases" / "CASE-001.yaml").read_text(encoding="utf-8")
    base = yaml.safe_load(base_text)
    WORKED_DIR.mkdir(parents=True, exist_ok=True)
    for wid, v in VARIANTS.items():
        case = dict(base)
        case["case_id"] = wid
        case["investigator"] = "INV-X (illustrative)"
        for k in ("red_flags_identified", "source_of_funds", "screening_adverse_media", "rationale", "disposition",
                  "escalation_decision"):
            if k in v:
                case[k] = v[k]
        if "escalation_addendum" in v:
            case["escalation_decision"] = base["escalation_decision"] + v["escalation_addendum"]
        body = yaml.safe_dump(case, sort_keys=False, allow_unicode=True, width=100)
        (WORKED_DIR / f"{wid}.yaml").write_text(HEADER + f"# Example: {v['title']}\n" + body, encoding="utf-8")
    rows = []
    for i, (wid, q, sev, code, desc, root, remed) in enumerate(FINDINGS):
        n = sum(1 for f in FINDINGS[:i + 1] if f[0] == wid)
        rows.append(dict(finding_id=f"{wid}-{n:02d}", case_id=wid, alert_id=base["alert_id"],
                         investigator="INV-X (illustrative)", question_ref=q, severity=sev, error_code=code,
                         scored=str(sev != "Observation"), description=desc, evidence="worked example note vs evidence",
                         requirement_reference=f"Checklist {q}", root_cause=root, remediation=remed,
                         owner="INV-X (illustrative)", due_date="", status="Illustrative"))
    pd.DataFrame(rows).to_csv(WORKED_DIR / "findings.csv", index=False)


if __name__ == "__main__":
    build()
    print(f"wrote {len(VARIANTS)} worked examples to {WORKED_DIR}")
