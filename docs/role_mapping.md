# Role mapping: TM QA Analyst capabilities → project evidence

How this synthetic portfolio project maps to the capabilities of a Transaction Monitoring Quality Assurance Analyst role. The mapping uses the capability list from the role-alignment brief and the JD coverage table in `docs/PROJECT_PLAN.md` §1; the job description text itself is not stored in this repository.

"Strong" means the repository contains working, tested evidence. "Partial" means the capability is shown but the evidence is thin or synthetic. "Gap" means it needs a human or real data.

| # | Capability | Rating | Evidence | Remaining gap |
|---|---|---|---|---|
| 1 | Review completed TM investigations for identification, investigation, evidence and conclusion | **Strong** | 24 case notes with QA reviews; checklist A–G; Case Review Workbench with a checklist view; worked examples WEX-01 to WEX-03 (Critical fail, Major fail despite a correct disposition, Minor-only pass) | QA assessments are not independent of the case preparation (see 4) |
| 2 | Identify gaps in evidence, transaction analysis, customer understanding, source of funds and wealth, risk, rationale and disposition | **Partial → Strong for method** | Error codes RF-01, FLW-01, SOF-01, SCR-01, RAT-01, EVD-01, SCP-01 and CP-02; CASE-001's three Minor findings; worked examples showing each gap type | Only one sample case has scored findings |
| 3 | Understand ML, TF, sanctions, PEPs, adverse media, SARs and jurisdiction risk; separate facts from hypotheses | **Strong (ML), partial (TF, sanctions)** | Case notes separate observed facts, hypotheses, unresolved questions and "not evidenced" actions; KYC flags are never treated as screening results; watchlist treated as context, not a sanctions match; verified POCA s.330 and s.333A references | No terrorist-financing scenario and no real screening data |
| 4 | Apply a consistent checklist, severity taxonomy, pass/fail method, remediation and appeals | **Strong** | `config/qa_checklist.yaml` (19 questions, critical flags); `config/error_taxonomy.yaml` (severities, Major → Fail, codes, root causes, remediation, appeals, attribution); `src/qa_engine.py` with tests for every outcome path | Appeals log empty: no appeals raised, and none simulated |
| 5 | Identify root causes, recurring errors, investigator patterns and control weaknesses; recommend proportionate action | **Partial** | Root-cause Pareto; attribution split (investigator 3, process 6, data 3, calibration 6); look-ahead control defect found and fixed with regression tests; three data-derived recommendations | Too few scored findings to show a genuine investigator pattern |
| 6 | Credible MI: outcomes, weighted scores, findings by severity, scenario and investigator, root causes, recommendations | **Strong** | QA MI Dashboard and PDF; scenario effectiveness; every headline figure reconciled by tests (`tests/test_docs.py`, `tests/test_report.py`) | Metrics come from a non-independent review |
| 7 | Develop and govern QA standards; timeliness; risks outside tolerance; continuous improvement | **Partial** | Standards change log (`docs/methodology.md`); template v2; timeliness MI (1 within target, 23 not verifiable, 0 outside); remediation status tracking | No timestamps for 23 cases; the SLA targets are portfolio assumptions |
| 8 | Communicate sensitive findings to stakeholders | **Strong** | Case notes; CASE-001 investigator feedback and QA finding; findings tracker; dashboard; one-page report addressed to the Head of TM Operations | No live stakeholder interaction |
| 9 | Digital and analytical skills | **Strong** | Python, DuckDB SQL over 9.5M rows, YAML configuration, Streamlit, reportlab, 130+ pytest tests, reproducibility check under pinned dependencies, label-leakage and look-ahead guards | — |
| 10 | Personal Banking and Business Banking coverage | **Partial** | Profiles by segment with different expected-activity bases; 19 Personal and 5 Business cases; business-specific considerations (controllers, turnover, circular flows) in notes and the Typology Library; dispositions by segment in the MI | Synthetic profiles; no business ownership or KYB data |

## What only a human can add

1. An independent reviewer to re-review the six borderline outcomes (CAL-01).
2. A blind review of `training/seeded_cases/` by someone who has not seen the answer key, to produce a genuine hit rate.
3. The author's review of the three worked examples.
4. Deployment, and any claims about real-world TM or QA experience, which this project does not establish.
