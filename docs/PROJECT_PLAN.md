# Project Plan: Transaction Monitoring Investigation & QA Review Framework

**Author:** Parth Pardeshi
**Target role:** Transaction Monitoring Quality Assurance Analyst (Barclays UK, BA4, Glasgow)
**Timeline:** 7 working days
**Stack:** Python (pandas, DuckDB), YAML, pytest, Streamlit, Plotly
**Deliverables:** GitHub repo · live Streamlit app · 1-page QA Findings Report (PDF)

---

## 1. Why this project exists

The role reviews completed AML investigations and judges whether financial crime risk was correctly **identified, investigated, evidenced and concluded**. This project simulates that end to end:

1. **Detect:** rule-based TM scenarios raise alerts on synthetic UK transaction data.
2. **Investigate:** written L1 investigation case notes for a sample of alerts.
3. **Quality-assure:** each case is reviewed against a QA checklist, findings are severity-classified, remediation is assigned and appeals are recorded.
4. **Report:** QA MI shows pass rates, error trends and root causes, with recommendations for senior stakeholders.

**Positioning rule:** This is not an ML project. The skill being demonstrated is **reviewer judgement**, not modelling. Keep rules simple and explainable, and put the effort into steps 2 to 4.

**JD coverage map**

| JD requirement | Where the project proves it |
|---|---|
| Review investigations against policies, standards, QA guidance | Phase 4: QA checklist and case reviews |
| Identify gaps in evidence, rationale, risk assessment | Phase 4: findings log |
| Error classification, remediation, appeal processes | Phase 4: taxonomy, remediation, appeals |
| ML / TF / sanctions risks, red flags, high-risk jurisdictions, SoF/SoW, SARs | Phases 2–3: scenarios, case notes, red-flag library |
| Assess transaction patterns and escalate through governance | Phase 3: dispositions (close / escalate / SAR) |
| Trackers, MI, trend identification, root-cause analysis | Phase 5: MI dashboard and report |
| Personal and Business Banking customer types | Phase 1: synthetic customer profile layer |
| Communicate findings to senior stakeholders | Phase 6: QA Findings Report |

---

## 2. Data

**Primary dataset: SAML-D** (Oztas et al., 2023, Bournemouth University)
Kaggle: `berkanoztas/synthetic-transaction-monitoring-dataset-aml`

- About 9.5M synthetic transactions, 12 features, 28 typologies (11 normal, 17 suspicious). Roughly 0.1% of transactions are labelled laundering.
- UK-centric, with high-risk countries and high-risk payment types. This is a good match for Barclays UK.
- Expected columns (verify on download): `Time, Date, Sender_account, Receiver_account, Amount, Payment_currency, Received_currency, Sender_bank_location, Receiver_bank_location, Payment_type, Is_laundering, Laundering_type`

**Backup dataset:** IBM Transactions for AML (Kaggle, `ealtman2019`).

**Handling the size:**
- Never commit the raw CSV. Add `data/raw/` to `.gitignore`.
- Run scenarios locally with **DuckDB** directly over the CSV (fast, no memory blow-up).
- Export only what the app needs to `data/processed/*.parquet`: alerts, alerted-account transaction history (90 days), and profiles. Keep each file well under GitHub's 100 MB limit (target < 30 MB total).

**Gap to fill:** SAML-D has no KYC data. Phase 1 adds a synthetic customer profile layer so investigations can test activity against **expected activity**, which is how real reviews work.

---

## 3. Repository structure

```
tm-qa-framework/
├── README.md
├── requirements.txt
├── .gitignore                    # data/raw/
├── data/
│   ├── raw/                      # SAML-D CSV (local only)
│   └── processed/                # alerts.parquet, txns_alerted.parquet, profiles.parquet
├── config/
│   ├── scenarios.yaml            # TM rule thresholds
│   ├── high_risk_jurisdictions.yaml
│   ├── qa_checklist.yaml         # questions, sections, weights, critical flags
│   └── error_taxonomy.yaml       # severities, error codes, root-cause categories
├── src/
│   ├── profiles.py               # synthetic KYC layer
│   ├── scenarios.py              # TM rules (DuckDB SQL)
│   ├── alerts.py                 # alert generation + sampling
│   ├── qa_engine.py              # scoring, outcome logic
│   └── mi.py                     # MI aggregations
├── cases/
│   └── CASE-001.yaml ...         # investigator case notes (handwritten)
├── qa/
│   ├── reviews.csv               # QA outcome per case
│   ├── findings.csv              # one row per finding
│   └── appeals.csv
├── app/
│   ├── Home.py
│   └── pages/
│       ├── 1_Alert_Explorer.py
│       ├── 2_Case_Review_Workbench.py
│       ├── 3_QA_Findings_Tracker.py
│       ├── 4_QA_MI_Dashboard.py
│       ├── 5_Typology_Library.py
│       └── 6_Methodology.py
├── docs/
│   ├── methodology.md
│   └── QA_Findings_Report.pdf
└── tests/
    ├── test_scenarios.py
    └── test_qa_engine.py
```

---

## 4. Phase-by-phase plan

### Phase 0: Setup (Day 1, morning)
- [ ] Create repo, venv, `requirements.txt` (`pandas duckdb pyarrow pyyaml streamlit plotly pytest`)
- [ ] Download SAML-D and confirm the column names and the `Payment_type`, `Laundering_type` and location values
- [ ] Quick EDA: value counts per typology, payment type, location, and amount distribution
- [ ] **Reading (2 hrs):** JMLSG Part I Ch. 5 (CDD) and Ch. 6 (suspicious activity, reporting); NCA guidance on submitting good-quality SARs

### Phase 1: Synthetic customer profile layer (Day 1, afternoon)
For every account that appears in an alert, generate a deterministic profile (seeded by account ID):

| Field | Values |
|---|---|
| `segment` | Personal Banking / Business Banking |
| `occupation_or_sector` | e.g. Student, Nurse, Retired; Café, Construction, Car trader, Import/Export |
| `declared_income_or_turnover` | Annual £ band |
| `expected_monthly_credits` | £ band derived from income or turnover |
| `account_open_date` | Date |
| `customer_risk_rating` | Low / Medium / High |
| `pep_flag`, `adverse_media_flag` | Mostly False; a few True to create test cases |

Design some **mismatches on purpose** (e.g. a "Student" receiving £40k/month). These become the red flags investigators must spot and QA must check.

### Phase 2: TM scenarios and alert generation (Day 2)
Implement 6 explainable rules in `scenarios.py`, with thresholds in `scenarios.yaml`. The thresholds below are illustrative and should be tuned to produce a manageable alert volume.

| ID | Scenario | Illustrative logic | ML/TF risk |
|---|---|---|---|
| TM01 | Structuring | ≥3 cash deposits of £7,500–£9,999 in 7 days | Placement, threshold avoidance |
| TM02 | Rapid movement of funds | ≥80% of credits debited out within 48 hrs, total > £10k | Layering, mule accounts |
| TM03 | High-risk jurisdiction | Cross-border to/from high-risk location, > £5k in 30 days | ML/TF, sanctions exposure |
| TM04 | Fan-in | ≥8 distinct senders to one account in 7 days | Money mule collection |
| TM05 | Fan-out | ≥8 distinct receivers from one account in 7 days | Layering, dispersal |
| TM06 | Behavioural change | 30-day credits > 3× prior 90-day monthly average, or > 2× expected activity from profile | Unexplained change in activity |

Then:
- [ ] Generate alerts → `alerts.parquet` (alert_id, account, scenario, trigger date, trigger value)
- [ ] **Scenario effectiveness table:** alerts per scenario, % of alerts on accounts with `Is_laundering = 1`, and typologies caught vs missed. This shows you understand false positives and coverage, which is useful in interviews.
- [ ] **Sample for investigation:** stratified sample of **24 alerts** (4 per scenario). Mix of true positives and false positives.
- [ ] `pytest`: one test per rule using a tiny handcrafted fixture (e.g. 3 deposits of £9,500 → TM01 fires; 2 deposits → it doesn't)

### Phase 3: Investigation case notes (Days 3–4)
**Write these yourself.** This is the most valuable part of the project, and interviewers will probe it. AI tools can help with formatting, but not with the judgement.

Template (`cases/CASE-0XX.yaml`):

```yaml
case_id: CASE-007
alert_id: TM02-00412
scenario: TM02 Rapid movement of funds
investigator: INV-B            # 3 fictional investigators: INV-A, INV-B, INV-C
date_opened: 2023-03-14
date_closed: 2023-03-17
customer_summary: >
  Personal Banking, Student, declared income £8k, account opened 4 months ago. Risk rating: Medium.
activity_reviewed: >
  90-day lookback. 11 credits from 9 unrelated individuals totalling £23,400,
  86% sent onward within 24h to 2 accounts (one UAE-domiciled).
red_flags_identified:
  - Activity inconsistent with profile (income vs credits)
  - Multiple unrelated third-party credits
  - Rapid onward movement
red_flags_missed: []           # filled ONLY in the reference answer key, not shown to investigator
source_of_funds: "Not established; no RFI raised."
screening_adverse_media: "No adverse media. Sanctions screening clear."
rationale: >
  ...
disposition: ESCALATE_SAR      # CLOSE_NO_FURTHER_ACTION | ESCALATE_L2 | ESCALATE_SAR
planted_errors: []             # answer key for QA, hidden in "reviewer mode"
```

**Error planting plan:** About 10 of 24 cases contain deliberate errors, spread across investigators so one investigator shows a pattern. That gives the root-cause analysis something real to find.

| Planted error | Severity | # cases |
|---|---|---|
| Incorrect outcome: closed when a SAR or escalation was required | Critical | 2 |
| Sanctions or high-risk jurisdiction exposure not escalated | Critical | 1 |
| Key red flag not identified (outcome still correct) | Major | 2 |
| Source of funds/wealth not considered for activity inconsistent with profile | Major | 2 |
| Rationale doesn't support the conclusion | Major | 1 |
| Incomplete lookback / documentation gap / missing screening note | Minor | 2 |

Make INV-B repeatedly miss SoF considerations, which points to a **knowledge gap** root cause. Make the TM03 cases show **unclear procedure**.

Also write at least 2 **good false-positive closures** with strong rationale. QA should recognise good work too.

> **Superseded (2026-10-22).** The error-planting plan above, and the `red_flags_missed` and `planted_errors` template fields, were not built into the 24 cases. CASE-001 to CASE-024 contain no planted errors. Planted errors exist only in the seeded training copies in `training/seeded_cases/`, whose answer key is git-ignored and which have not been reviewed.

### Phase 4: QA framework and reviews (Day 5)

**4a. QA checklist (`qa_checklist.yaml`)**, with about 15 questions in 6 sections. Answers: Yes / No / N/A. Critical questions trigger automatic failure.

| Section | Example questions | Critical? |
|---|---|---|
| A. Alert & scope | Was the full triggering activity and an appropriate lookback reviewed? | |
| B. Customer understanding (CDD) | Was activity assessed against the customer's profile and expected activity? Was the customer risk rating considered? | |
| C. Transaction analysis & red flags | Were all material red flags identified and addressed? Were counterparties and jurisdictions assessed? | |
| D. SoF / SoW & screening | Was source of funds/wealth considered where activity is inconsistent with the profile? Were sanctions, PEP and adverse media checks evidenced? | |
| E. Rationale & outcome | Does the rationale logically support the conclusion? **Is the outcome correct?** | Yes |
| F. Escalation & SAR | **Was a required escalation or SAR raised?** Was any sanctions exposure escalated? | Yes |
| G. Documentation & timeliness | Is the case note clear, evidenced and completed within SLA? | |

**4b. Error taxonomy (`error_taxonomy.yaml`)**

- **Critical:** incorrect outcome, missed SAR or escalation, unescalated sanctions exposure, tipping-off risk → **Fail**
- **Major:** material evidence or rationale gap, but outcome is correct → **Fail** (or Pass with observations, depending on your rule; document the choice)
- **Minor:** documentation, formatting, or within-tolerance timeliness → **Pass with observations**
- **Root-cause categories:** Knowledge gap · Procedure not followed · Procedure unclear · System/data limitation · Time pressure

**4c. Scoring logic (`qa_engine.py`)**
- Any Critical → Fail
- Any Major → Fail
- Minor only → Pass with observations
- None → Pass
- Also compute a weighted quality score (%) for trend MI
- `pytest`: tests for each outcome path

**4d. Run the reviews.** Review all 24 cases **blind**, using only the case note, not the `planted_errors` key. Then compare your findings against the key and record the hit rate (e.g. "identified 11 of 12 planted errors"). This is an honest self-calibration metric and a strong interview talking point.

> **Superseded (2026-10-22).** No blind review was performed and no hit rate exists. The QA assessments of the 24 cases were reviewed by the author, which is not an independent or blind review. A blind review of the seeded training set remains outstanding (protocol in `training/README.md`).

**4e. Findings, remediation and appeals**
- `findings.csv`: case_id, question_ref, severity, error_code, description, regulatory/procedure reference, root cause, remediation action, owner, due date, status
- `appeals.csv`: 2–3 appeals from "investigators" with an outcome (Upheld / Overturned) and reasoning. The JD names appeal processes explicitly.

### Phase 5: Streamlit app (Day 6)

| Page | Contents |
|---|---|
| **Home** | Project purpose, pipeline diagram (Detect → Investigate → QA → MI), headline KPIs, a clear **"synthetic data, simulated cases"** disclaimer |
| **1. Alert Explorer** | Alert volumes by scenario, scenario effectiveness table, filter by scenario/segment/jurisdiction, drill into an alert's transaction timeline (Plotly) |
| **2. Case Review Workbench** ⭐ | Pick a case → customer profile card, 90-day transaction timeline, counterparty and jurisdiction summary, investigator case note. **"Try it yourself" mode:** the visitor answers the QA checklist, then clicks *Reveal QA Outcome* to compare against your review and the planted-error key. This is the feature recruiters will remember. |
| **3. QA Findings Tracker** | Filterable findings log (severity, investigator, scenario, status), remediation status, appeals log |
| **4. QA MI Dashboard** | Pass rate, quality score by investigator and scenario, errors by severity and code, root-cause Pareto, 3 written recommendations |
| **5. Typology Library** | Red-flag reference for each scenario: what it looks like, common legitimate explanations, what a good investigation should evidence |
| **6. Methodology** | Sampling approach, checklist, taxonomy, scoring rules, regulatory references, limitations |

> **Superseded (2026-10-22).** The Case Review Workbench was built without the "Try it yourself" mode and without a planted-error key to reveal; no such key exists for the 24 cases.

**Build notes**
- Load data with `@st.cache_data`. Read only from `data/processed/` and the YAML files.
- Keep `st.session_state` for the Workbench answers.
- Deploy on Streamlit Community Cloud from the GitHub repo (same as your other projects).

### Phase 6: Report, README, polish (Day 7)
- [ ] **QA Findings Report (1 page, PDF).** Written for a "Head of TM Operations": headline pass rate, top 3 error themes, root causes, 3 recommendations (e.g. targeted SoF refresher for the team; clarify the TM03 high-risk jurisdiction procedure; add a mandatory SoF field to the case template), and next steps.
- [ ] README: problem, approach, screenshots or GIF, live demo link, how to run, limitations, regulatory references
- [ ] Run all tests, deploy, check every page on mobile width, fix typos (it's a QA project, so typos would be ironic)

---

## 5. Regulatory references to cite (and actually read)

- **Proceeds of Crime Act 2002:** ss.327–329 (principal offences), s.330 (failure to disclose), s.333A (tipping off)
- **Terrorism Act 2000:** terrorist financing offences and disclosure duties
- **Money Laundering Regulations 2017:** CDD (reg. 28), EDD and high-risk third countries (reg. 33)
- **JMLSG Guidance Part I:** CDD, monitoring, suspicious activity reporting
- **Sanctions and Anti-Money Laundering Act 2018 / OFSI:** financial sanctions obligations
- **NCA:** SAR and DAML (Defence Against Money Laundering) guidance
- **FCA Financial Crime Guide (FCG)**

Reference these in the checklist (e.g. "Q-F1, POCA s.330 / JMLSG Pt I Ch. 6"). Cite only what you've read.

---

## 6. Scope cuts if time runs short

Cut in this order:
1. Phase 5 Typology Library page
2. Reduce to 4 scenarios and 16 cases
3. Appeals log (keep 1 example)
4. Drop the "Try it yourself" mode and show your review only

**Never cut:** handwritten case notes, the QA checklist, the error taxonomy, blind reviews, and the MI and recommendations. Those are the point of the project.

> **Superseded (2026-10-22).** As built, CASE-002 to CASE-024 were not handwritten by the author (see README, Authorship and review), and no blind review has taken place.

---

## 7. Resume entry (use only after completing)

> **Superseded (2026-10-22).** The original draft below no longer matches what was built. The case notes and QA assessments were reviewed by the author rather than all independently drafted (see README, Authorship and review), and no blind review has taken place. Do not use the original wording; use the accurate version instead.

**Accurate version (as built):**

**Transaction Monitoring QA Framework** | *Python, DuckDB, Streamlit, pytest* | Live Demo | Code
- Built an AML transaction-monitoring QA framework on 9.5M synthetic transactions (SAML-D): 6 explainable DuckDB rule scenarios raising 11,295 alerts, with retrospective effectiveness analysis (laundering-labelled window yield of 0.0–12.5% by scenario).
- Defined the QA standard:
  - a 19-question checklist;
  - a severity taxonomy (Critical or Major means Fail);
  - a weighted quality score;
  - a findings log with remediation, and an appeals process.

- Reviewed and validated 24 simulated investigation case notes and their QA assessments:
  - checked the transaction evidence and the figures;
  - checked the investigative reasoning against red flags, source of funds and screening;
  - reviewed severity-graded QA findings;
  - confirmed that dispositions and escalations were consistent with the documented methodology.

  Drafted one case note (CASE-001) end to end.
- Built a Streamlit QA MI app and a one-page findings report. Found and fixed a look-ahead (future-information) defect in the case evidence packs, with regression tests.

Do not claim: independently drafting every case note, an independent or blind QA review, a blind-review hit rate, or professional Barclays or TM QA experience. Describe the QA work as reviewing and validating the assessments; authorship is stated in the README.

**Original draft (superseded, kept for the record):**

**Transaction Monitoring QA Review Framework** | *Python, DuckDB, Streamlit* | Live Demo | Code
- Designed an AML Transaction Monitoring QA framework on 9.5M synthetic UK transactions (SAML-D): built 6 rule-based scenarios (structuring, mule fan-in, rapid movement of funds, high-risk jurisdictions) and wrote 24 investigation case notes with close / escalate / SAR dispositions
- Quality-assured all 24 investigations against a JMLSG/MLR 2017-aligned checklist, classifying findings by severity (critical / major / minor) with root cause, remediation actions and an appeals log; blind review identified X of Y seeded errors
- Built QA MI (pass rate, error trends by investigator and scenario, root-cause Pareto) in an interactive Streamlit app, with a findings report recommending targeted coaching and procedure changes

Add to Skills: *Transaction Monitoring, AML/CTF, Quality Assurance & Quality Control, red-flag identification, SAR escalation, error classification, root-cause analysis, QA MI*

---

## 8. Interview prep from this project

Be ready to explain:
- One case you'd **fail** and exactly why, citing the checklist question and regulation
- One case that looked suspicious but was a **reasonable closure**, and why
- How you'd give that investigator **constructive feedback** (specific, evidence-based, focused on behaviour, with a learning action)
- Why most TM alerts are false positives, and what that means for QA sampling
- What tipping off is and why it matters in case notes and RFIs
- What you'd do with a finding the investigator disputes (the appeals process)

---

## 9. Honesty guardrails

- Label everything as **synthetic data and simulated investigations**: in the app, the README and the resume.
- The fictional investigators (INV-A/B/C) are your own case notes with planted errors. Say so.
- Present this as evidence of **understanding and approach**, not as professional TM or QA experience.

> **Superseded (2026-10-22).** The second guardrail no longer applies: the case notes of the fictional investigators (INV-A/B/C) contain no planted errors. Authorship is stated in the README (Authorship and review).

---

## 10. Definition of done

- [ ] 6 scenarios implemented and tested
- [ ] 24 case notes written, about 10 with planted errors
- [ ] 24 blind QA reviews, findings log, appeals log
- [ ] Streamlit app deployed, with all pages working and the disclaimer visible
- [ ] 1-page QA Findings Report PDF
- [ ] README with demo link and screenshots
- [ ] Resume and LinkedIn updated with the project
- [ ] ICA AML certificate enrolment done (in parallel)

> **Superseded (2026-10-22).** The second and third items no longer match the project: the 24 case notes contain no planted errors, and the 24 QA reviews were reviewed by the author, not performed blind.
