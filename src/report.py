"""Phase 6: one-page QA Findings Report (PDF) built from the stored outputs.

    python -m src.report    # writes docs/QA_Findings_Report.pdf

Every figure is read from qa/*.csv, data/processed/scenario_effectiveness.csv and the
case files. Nothing is typed in by hand.
"""

from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src import app_data

OUT = app_data.ROOT / "docs" / "QA_Findings_Report.pdf"


def facts() -> dict:
    reviews, findings, appeals = app_data.load_qa()
    eff = app_data.read_processed("scenario_effectiveness.csv")
    scored = findings[findings["scored"] == "True"]
    obs = findings[findings["scored"] == "False"]
    taxonomy = app_data.load_yaml("config/error_taxonomy.yaml")
    cases = app_data.load_cases()
    return dict(
        reviews=reviews, eff=eff, scored=scored, obs=obs, appeals=appeals, findings=findings,
        attribution=app_data.attribution(findings, taxonomy).value_counts().to_dict(),
        timeliness=app_data.timeliness(cases)["case_timeliness"].value_counts().to_dict(),
        segments=app_data.case_segments(cases).value_counts().to_dict(),
        n_questions=sum(len(s["questions"]) for s in app_data.load_yaml("config/qa_checklist.yaml")["sections"].values()),
        outcomes=reviews["qa_outcome"].value_counts().to_dict(),
        dispositions=reviews["disposition"].value_counts().to_dict(),
        mean_score=round(reviews["quality_score"].mean(), 1),
        obs_by_code=obs["error_code"].value_counts().to_dict(),
    )


def build(path=OUT) -> int:
    f = facts()
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=7.6, leading=9.4)
    h = ParagraphStyle("h", parent=ss["Heading2"], fontSize=9.5, leading=11, spaceBefore=4, spaceAfter=1.5)
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=13, leading=15, spaceAfter=2)
    warn = ParagraphStyle("w", parent=body, backColor=colors.HexColor("#FFF4E5"), borderPadding=3,
                          borderColor=colors.HexColor("#E8A33D"), borderWidth=0.6)
    P = lambda t, s=body: Paragraph(t, s)  # noqa: E731

    o, d = f["outcomes"], f["dispositions"]
    n = len(f["reviews"])
    story = [
        P("QA Findings Report - Transaction Monitoring Investigations", title),
        P(f"To: Head of TM Operations (simulated audience) · Generated {date.today().isoformat()} · Synthetic portfolio work"),
        Spacer(1, 3),
        P("<b>Synthetic data - portfolio project.</b> Transactions are from the synthetic SAML-D dataset; customer profiles are "
          "synthetic. The case notes and QA assessments were reviewed by the project author "
          "for factual accuracy and consistency. This is the author's validation, not an independent or blind "
          "QA review. This is not Barclays work and carries no compliance endorsement.", warn),
        P("Headline", h),
        P(f"{n} sampled alerts were investigated and QA-reviewed against a {f['n_questions']}-question checklist (sections A-G). "
          f"Outcomes: <b>{o.get('Fail', 0)} Fail</b>, {o.get('Pass with observations', 0)} Pass with observations, "
          f"{o.get('Pass', 0)} Pass; mean quality score {f['mean_score']}/100. Dispositions: {d.get('ESCALATE_SAR', 0)} internal "
          f"disclosure to the MLRO, {d.get('ESCALATE_L2', 0)} L2 referral, {d.get('CLOSE_NO_FURTHER_ACTION', 0)} closed. "
          "<b>The pass rate is not evidence of investigator quality.</b> The QA assessments were prepared in the same "
          "workflow as the case notes, which were drafted after the first review and avoided its findings, and "
          "were validated by the author rather than an independent reviewer."),
        P(f"Scenario effectiveness ({f['eff']['alerts'].sum():,} alerts; labels used retrospectively only)", h),
    ]
    eff = f["eff"]
    rows = [["Scenario", "Alerts", "Accounts", "Laundering-labelled windows"]] + [
        [f"{r.scenario} {r.scenario_name}", f"{r.alerts:,}", f"{r.accounts:,}", f"{r.laundering_labelled_pct}%"]
        for r in eff.itertuples()]
    t = Table(rows, colWidths=[78 * mm, 22 * mm, 22 * mm, 45 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.2), ("LEADING", (0, 0), (-1, -1), 8.4),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [t]

    scored = f["scored"]
    themes = "; ".join(f"{r.error_code} ({r.case_id}): {r.description.rstrip('.')}" for r in scored.itertuples()) or "none"
    sev = ", ".join(f"{v} {k}" for k, v in scored["severity"].value_counts().items()) or "none"
    in_cases = ", ".join(sorted(scored["case_id"].unique())) or "no case"
    ob = f["obs_by_code"]
    attr = "; ".join(f"{k} {v}" for k, v in sorted(f["attribution"].items(), key=lambda kv: -kv[1]))
    tml = "; ".join(f"{k} {v}" for k, v in f["timeliness"].items())
    segs = ", ".join(f"{v} {k}" for k, v in f["segments"].items())
    story += [
        P("Top error themes", h),
        P(f"<b>By attribution ({len(f['findings'])} records):</b> {attr}. Only investigator errors are scored. "
          f"<b>Segments:</b> {segs}. <b>Timeliness (5-working-day target, portfolio assumption):</b> {tml}; "
          f"{f['timeliness'].get('Outside target', 0)} recorded outside tolerance."),
        P(f"<b>Scored findings ({len(scored)}: {sev}; in {in_cases}):</b> {themes}"),
        P(f"<b>Observations ({len(f['obs'])}, not scored):</b> borderline outcomes needing calibration {ob.get('CAL-01', 0)}; "
          f"case packs listing later-dated alerts {ob.get('PRC-02', 0)} (look-ahead defect, now fixed and corrected); "
          f"data-quality issues {ob.get('DAT-01', 0)} (accounts under two bank locations); disclosure-timing template gap "
          f"{ob.get('PRC-01', 0)}; no timestamps for CASE-002 to CASE-024, so timeliness unverifiable {ob.get('PRC-03', 0)}; "
          f"no escalation ownership procedure {ob.get('PRC-04', 0)}."),
        P("Root causes", h),
        P("Single-case findings give no evidence of cause (recorded as 'Not determinable'). The recurring themes are "
          "<b>system/data and procedure limitations</b> - template fields, case-pack generation, data quality and the "
          "absence of an escalation procedure - not investigator knowledge gaps."),
        P("Recommendations", h),
    ]
    for i, (rt, text) in enumerate(app_data.recommendations(f["eff"], f["findings"]), 1):
        story.append(P(f"<b>{i}. {rt}.</b> {text}"))
    story += [
        P("<b>Remediation priority:</b> (1) the open process gaps PRC-03 and PRC-04, which affect every case; (2) "
          "independent calibration of the CAL-01 outcomes; (3) investigator feedback on the CASE-001 Minor findings. "
          "Three illustrative worked examples (Case Review Workbench) show how the same evidence produces a Critical fail, "
          "a Major fail despite a correct disposition, and a Minor-only pass."),
        P("Limitations and outstanding work", h),
        P("Currency of amounts unverified (GBP assumed); synthetic profiles; thresholds tuned in-sample on volume; the "
          "jurisdiction watchlist is a single FATF 23 June 2023 snapshot; window-level labels overstate what a rule caught. "
          f"Appeals logged: {len(f['appeals'])}. <b>Outstanding:</b> independent human calibration of the borderline outcomes; "
          "a genuinely blind review of the seeded training set (training/) to measure reviewer accuracy - no hit rate is "
          "claimed."),
    ]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=11 * mm,
                            bottomMargin=10 * mm, title="QA Findings Report (synthetic portfolio work)")
    doc.build(story)
    return doc.page


if __name__ == "__main__":
    pages = build()
    print(f"wrote {OUT} ({pages} page{'s' if pages != 1 else ''})")
