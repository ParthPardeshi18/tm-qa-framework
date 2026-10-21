# Methodology

All data is synthetic: SAML-D transactions plus simulated customer profiles and investigations.

## Synthetic customer profiles (Phase 1, `src/profiles.py`)

SAML-D has no KYC data. Each account that needs investigating gets a synthetic profile, so activity can be tested against **expected activity**.

### Generation

- **Input:** account IDs only. No transaction data is read, so profiles are generated only for the accounts requested (e.g. alerted accounts in Phase 2).
- **Determinism:** each field is drawn from SHA-256 of `tmqa-profile-v1|<account_id>|<field>`. Python's `hash()` (salted per process) and the `random` module (not guaranteed stable across versions) are not used. The same ID always gives the same profile. Changing `SALT` or the lookup tables changes every profile, and a pinned-profile test catches this.

### Fields

| Field | Values / rule |
|---|---|
| `segment` | Personal Banking (75%) / Business Banking (25%) |
| `occupation_or_sector` | 13 occupations or 10 business sectors, weighted |
| `declared_income_or_turnover_band` | Annual £ band, restricted to bands plausible for the occupation/sector (e.g. Student: £0–£10k) |
| `expected_monthly_credits_min_gbp` / `_max_gbp` | Band ÷ 12 |
| `account_open_date` | 2005-01-01 to 2022-10-06 |
| `customer_risk_rating` | Additive score: Business +1, high-risk sector +2, PEP +3, adverse media +2, account < 1 year old +1. 0 = Low, 1–2 = Medium, 3+ = High |
| `pep_flag` | ~1% |
| `adverse_media_flag` | ~2% |
| `planted_mismatch`, `planted_mismatch_type`, `planted_mismatch_note` | Deliberate test cases (below) |

High-risk sectors: Convenience store, Car trader, Import/Export, Money service business. These are cash-intensive or high-value goods businesses.

### Deliberate mismatches (planted test cases)

About 3% of accounts are planted. They are flagged with `planted_mismatch = True` plus a type and a note. All other profiles have `planted_mismatch = False` and null type and note. Planted profiles have clear PEP/adverse-media screening, so the profile-vs-activity mismatch is the only signal.

| Type | Profile | Red flag the investigator should raise |
|---|---|---|
| `LOW_INCOME_PERSONAL` | Student, £0–£10k income, expected credits up to £833/month | Material credits inconsistent with profile; SoF not explained |
| `MICRO_BUSINESS` | Hairdresser, £0–£50k turnover, expected credits up to £4,167/month | High-value or cross-border flows inconsistent with the business |
| `NEW_ACCOUNT_LOW_EXPECTED` | Student, opened within 90 days of dataset start, £0–£10k income | New account with high throughput: mule indicator |

The typical SAML-D transaction is ~£6.1k (median, `docs/eda_notes.md`). So a single typical credit exceeds a planted account's whole expected month.

The `planted_*` fields are answer-key data. They must be hidden in investigator and "try it yourself" views.

### Assumptions

- `Amount` is treated as GBP. The currency of `Amount` is still an open question (`docs/eda_notes.md` §10).
- Expected monthly credits are taken as the gross annual band ÷ 12. This ignores tax and timing, which errs on the side of generous expectations.
- Accounts are opened before the first SAML-D date (2022-10-07). Per-account first-seen dates aren't used, because computing them would need a full scan.
- Planted cases are selected by hash (~3% of whatever IDs are requested), not by observed activity. Whether a planted account actually shows excessive activity is confirmed in Phase 2/3 when its transactions are pulled.
- Occupations, sectors, bands, weights and rates are illustrative design choices, not derived from SAML-D.

## Transaction monitoring scenarios (Phase 2, `src/scenarios.py`, `src/alerts.py`)

Run with `python -m src.alerts` (about 1 minute). DuckDB reads the raw CSV directly and the 9.5M rows are never loaded into pandas. The raw file is read-only. Thresholds live in `config/scenarios.yaml`; the TM03 watchlist lives in `config/high_risk_jurisdictions.yaml`.

### Label isolation

The rules read only the `detect` view, which excludes `Is_laundering` and `Laundering_type`. Tests confirm that the rules run on data with no label columns, and that flipping the labels does not change the alerts. Labels are used afterwards, only for evaluation and to stratify the investigation sample.

### Currency assumption

The currency of `Amount` is **unverified**. Thresholds are in dataset monetary units, and amounts are used as recorded with no FX conversion, whatever `Payment_currency` says. "£" in labels and in the profile fields `*_gbp` is an assumption, not a confirmed fact.

### Account aggregation, windows and duplicates

- **Legs:** each transaction gives a credit leg (`Receiver_account`) and a debit leg (`Sender_account`). A leg is monitored only if its own-side bank location is `UK`, which simulates a UK bank monitoring its own customers. Cash deposits are credits to `Receiver_account`; in SAML-D sender and receiver always differ (assumption: the receiver is the account credited).
- **Windows:** `window_days: N` covers the N calendar days ending on the trigger date, inclusive (`RANGE ... INTERVAL N-1 DAYS PRECEDING`). Same-day transactions are all included. Dates only: the `Time` column is not used.
- **Comparisons:** counts, totals and ratios use `>=`. Amount bands are `[min, max)`.
- **Triggers:** at most one per account per scenario per date, evaluated on dates where the account has relevant activity.
- **Duplicate suppression:** per account and scenario, the first trigger becomes an alert. Further triggers on dates up to 30 days later (`suppression_days`) are suppressed. The next trigger after that starts a new alert. Different scenarios on the same account produce separate alerts (no cross-scenario consolidation yet).
- **Alert ID:** `<scenario>-<nnnnn>`, numbered by trigger date then account ID, so IDs are stable for the same data and config.

### Scenarios and threshold choice

The plan's illustrative thresholds flag 10k to 110k accounts per rule on this data. Thresholds were tightened using **volume-only** DuckDB diagnostics (distinct accounts triggered; labels not used) to roughly 350 to 4,000 accounts per rule.

| ID | Rule | Alerts |
|---|---|---:|
| TM01 | >= 3 cash deposits, each 3,000 to <6,000, to one account within 7 days | 375 |
| TM02 | 2-day credits >= 50,000 and 2-day debits >= 90% of those credits | 1,520 |
| TM03 | >= 150,000 credits + debits with watchlist-located counterparties within 30 days | 3,956 |
| TM04 | >= 20 distinct senders within 7 days | 1,556 |
| TM05 | >= 25 distinct receivers within 7 days | 1,615 |
| TM06 | Behavioural change vs own history **and** profile (below) | 2,273 |

**TM01 diagnostic.** UK cash deposits (225k) are small: median 1,767, P75 3,157, P95 5,209, P99 5,845. No non-laundering cash deposit is >= 7,500, so the plan's 7,500 to 9,999 band fires almost only on labelled laundering, leaving no false positives to review. Distinct accounts triggered by band and count within 7 days:

| Band | >= 2 | >= 3 | >= 4 |
|---|---:|---:|---:|
| 2,000 to <5,000 | 6,073 | 827 | 112 |
| 3,000 to <5,000 | 2,765 | 177 | 18 |
| **3,000 to <6,000** | 3,992 | **349** | 32 |
| 4,000 to <7,500 | 1,592 | 63 | 3 |
| 5,000 to <7,500 | 305 | 3 | 0 |

The chosen rule keeps the plan's pattern ("3 in 7 days") and moves the band to roughly the upper quartile to 99th percentile of this dataset's cash deposits. It is "repeated large cash for this population", not a statutory reporting threshold. Note: SAML-D's `Structuring` typology contains no cash; its cash laundering typologies are `Smurfing` and `Deposit-Send`.

**TM02:** dates only, so it shows credits and debits close together within 2 calendar days. It does not check that debits came after credits.

**TM03 watchlist.** The source is FATF, *Jurisdictions under Increased Monitoring, 23 June 2023* (26 jurisdictions; retrieved from fatf-gafi.org on 2026-10-21). This is a **historical analytical watchlist for this simulation**: not a legal high-risk-country classification (e.g. MLR 2017 Sch. 3ZA), not a sanctions list and not a current compliance list. Names are matched to SAML-D locations case-insensitively, with explicit aliases `Türkiye -> Turkey` and `United Arab Emirates -> UAE`. Matches: **Albania, Nigeria, Turkey, UAE**. The other 22 have no SAML-D location. Morocco and Pakistan are in SAML-D but not on this snapshot. The single snapshot is applied to the whole data period, although the real list changed during it. The threshold is high (150,000) because 17k UK accounts have recurring watchlist activity: a 5,000 threshold would flag 88% of them.

**TM06 comparison.**

1. Stage 1 (SQL). On date D:
   - window credits = credits in [D-29, D];
   - baseline = credits in the 90 days before the window, [D-119, D-30];
   - baseline monthly average = baseline / 3.

   The rule fires if all of these hold:
   - window credits >= 10 x the baseline monthly average;
   - window credits >= 100,000;
   - the baseline has >= 10 credit transactions;
   - the whole baseline lies inside the data, so triggers start around 2023-02-03.
2. Stage 2 (profile). Profiles are generated only for the stage-1 accounts. A trigger is kept if window credits >= 2 x `expected_monthly_credits_max_gbp` x (30/30).

The plan's "or profile" arm was not used. SAML-D activity is large relative to the illustrative profile bands (median about 5.6k of credits per account-month), so a profile-only arm would flag most low-income profiles. The profile is used as confirmation. The ">= 10 baseline credits" condition was added because, without it, most stage-1 hits are accounts with one tiny baseline credit (9k+ accounts). This means TM06 does not cover dormant or newly active accounts.

### Outputs (`data/processed`)

| File | Audience | Contents |
|---|---|---|
| `alerts.parquet` | Investigator | alert_id, scenario, account_id, window, trigger_value, trigger_detail |
| `profiles.parquet` | Investigator | Profiles for all alerted accounts, **without** `planted_*` fields |
| `txns_alerted.parquet` | Investigator | Raw rows (labels dropped) where an alerted account is sender or receiver, within 90 days up to each of its trigger dates |
| `alert_sample.csv` | Investigator | 24 sampled alerts (same columns as `alerts.parquet`) |
| `alert_evaluation.parquet` | Answer key | Labelled-leg counts and typologies per alert window |
| `profiles_answer_key.parquet` | Answer key | `planted_*` fields per alerted account |
| `alert_sample_key.csv` | Answer key | Labels and planted flags for the sample |
| `scenario_effectiveness.csv`, `typology_coverage.csv` | QA / MI | See `docs/scenario_effectiveness.md` |

### Evaluation definitions

See `docs/scenario_effectiveness.md`. In short:

- An alert is laundering-labelled if any monitored leg of the account inside its alert window has `Is_laundering = 1`.
- A typology is "detected" if at least one of its laundering transactions is such a leg.

"Detected" is a weak test: busy accounts touch many typologies. Coverage % is the more honest measure.

### Investigation sample

Up to 4 alerts per scenario, ordered by `sha256("tmqa-sample-v1|alert_id")`:

- at most 1 account with a planted profile mismatch;
- then up to 2 laundering-labelled windows;
- then non-labelled windows;
- any shortfall filled from the remaining alerts.

Each account appears at most once. Result: 24 alerts, 10 laundering-labelled windows, 6 planted-mismatch accounts. TM05 has no labelled windows, so its 4 are all non-labelled.

### Limitations

- The currency of `Amount` is unverified, and there is no FX normalisation.
- Windows are date-based; TM02 does not check the order of credits and debits.
- Only UK-side legs are monitored. Laundering transactions with no UK side cannot be covered (see `monitored_txns`).
- The TM03 watchlist is a single static snapshot; there is no country-risk weighting.
- TM06 needs at least 120 days of data and an established baseline, so it cannot detect dormant or new-account spikes.
- The `txns_alerted` history (90 days) shows only part of TM06's 120-day comparison span.
- Thresholds were tuned for alert volume on the same data they run on (in-sample). Labels were not used for tuning, but the thresholds are not validated out of sample.
- Window-level labels overstate what a rule "caught", and SAML-D labels individual transactions, not accounts.

## Case notes (Phase 3, `src/case_prep.py`, `cases/`)

### Template versions

| Version | Cases | Fields |
|---|---|---|
| v1 | CASE-001 | Facts, evidence, and investigator judgement fields (dates, red flags, source of funds, screening, rationale, disposition, escalation decision) |
| v2 | CASE-002 to CASE-024 | v1 plus four disclosure-tracking fields |

CASE-001 was completed and QA-reviewed on v1 before the disclosure-tracking fields existed. It is preserved unchanged and is not retro-fitted. The fields were added after its QA review found that the template could not evidence when suspicion was formed or when the internal disclosure was made. That gap was recorded as a process observation, not an investigator finding. `case_prep.py --force` never overwrites a case that contains investigator content.

### Disclosure-tracking fields (v2)

| Field | Content |
|---|---|
| `suspicion_formed_at` | ISO 8601 date-time when suspicion was formed |
| `internal_disclosure_at` | ISO 8601 date-time of the internal disclosure |
| `disclosure_recipient` | Who received it, e.g. nominated officer / MLRO |
| `referral_evidence` | Reference or summary of the evidence supporting the referral |

The fields stay `null` when no internal disclosure is made, or when the information is not recorded. Values are never estimated or invented.

### Timeliness standard (portfolio assumption)

| Step | Project target |
|---|---|
| Alert generation to investigator disposition | Within 5 working days |
| Suspicion formed to internal disclosure | Same working day (operational target) |
| L2 review | Never delays an internal disclosure |

These targets are **portfolio assumptions for QA practice**. They are not Barclays service standards and not statutory deadlines.

The applicable statutory requirement, where POCA s.330 applies, is to disclose **as soon as is practicable** after the knowledge or suspicion arises. The same-working-day target is a stricter operational proxy used so that timeliness can be tested. Missing it is a QA timeliness observation; it does not establish a breach of the statute.

**Missing timestamps:** if `suspicion_formed_at` or `internal_disclosure_at` is missing, timeliness **cannot be verified**. That does not by itself prove the disclosure was late. QA records it as a gap in documentation or evidence, not as a late disclosure. For CASE-001 (v1), the gap is attributed to the template, not to the investigator.

## QA outcome rules (decided before Phase 4)

These rules apply consistently to all 24 QA reviews. They will later be encoded in `config/qa_checklist.yaml`, `config/error_taxonomy.yaml` and `src/qa_engine.py`.

| Highest severity found | QA outcome | Examples |
|---|---|---|
| Critical | **Fail** | Incorrect outcome; a required escalation or internal disclosure missed; sanctions exposure not escalated, where applicable |
| Major | **Fail** | A material evidence gap; a rationale that does not support the conclusion; a material red flag or risk-assessment gap. Applies even when the disposition is correct |
| Minor only | **Pass with observations** | Non-material documentation gaps; timeliness issues within tolerance |
| None | **Pass** | |

Principles:

- A correct disposition does not by itself make an investigation good quality. QA assesses whether the investigator:
  - identified the relevant risks;
  - investigated proportionately;
  - evidenced the assessment;
  - reached a conclusion the record supports.
- Severity is applied proportionately. The same underlying error is not classified more than once without justification.
- A limitation of the synthetic dataset is not an investigator failure. A missing record does not by itself prove that a required check was not performed.

## Case completion (Phase 3): authorship and conventions

### Authorship and review

The investigation case notes and QA assessments were prepared with AI assistance and reviewed by the project author for factual accuracy and consistency.

| Cases | Case note | QA assessment |
|---|---|---|
| CASE-001 | Drafted by the project author with step-by-step AI coaching | Findings decided by the author on AI-proposed points |
| CASE-002 to CASE-024 | Prepared with AI assistance, following the conventions set during CASE-001; reviewed by the author | Prepared with AI assistance in the same workflow; reviewed by the author |

The author's review covered:

- the transaction evidence and the figures in each note;
- the investigative reasoning;
- the QA findings;
- whether the conclusions are consistent with this methodology.

The original plan expected the author to draft every note. The AI-assisted workflow with author review replaced that for CASE-002 to CASE-024. The fictional investigator IDs (INV-A/B/C) are labels only. This is synthetic portfolio work, not professional casework.

**Independence and blindness.** The author's review is a validation of the work, not an independent QA review:

- The case notes and the QA assessments were prepared in the same AI-assisted workflow, so the QA assessments are not independent of the case preparation.
- No second reviewer has assessed the cases, and no blind review has been performed.

During preparation, the AI assistant also saw the sample answer key (`alert_sample_key.csv`), printed while checking Phase 2 outputs. It was not consulted while preparing or assessing the cases, but its influence cannot be ruled out. Therefore:

- The plan's blind-review hit-rate metric (§4d) **cannot be derived from these notes**.
- The distribution of dispositions must not be compared with the answer key as evidence of skill.

### Conventions applied (CASE-002 to CASE-024)

- **Evidence standard:** "Option A". Only investigator-facing data is used:
  - the case evidence block;
  - `txns_alerted.parquet`;
  - the profiles.

  There are no invented requests for information, screening results, customer explanations or documents. Actions that would be needed are recorded as "not evidenced as completed".
- **Screening wording:** fixed. KYC flags on file are never treated as screening results.
- **Case-handling dates:** `date_opened` and `date_closed` are **null**, because no case-handling record exists for these simulated cases. Validation accepts both null or both valid and ordered, never one without the other.
- **Disclosure-tracking fields:** null, because there is no record of when suspicion was formed or the disclosure was made. Timeliness is therefore unverifiable, which is not treated as lateness.
- **Look-ahead defect (fixed 2026-10-21):** the template's `other_alerts_on_account` originally listed every alert on the account, including alerts dated after the case (CASE-007, CASE-009, CASE-013).
  - **Root cause:** `build_evidence` in `src/case_prep.py` filtered by account only. It now keeps only alerts dated on or before the case's alert date.
  - **Records corrected:** in the three affected cases, only the future-alert entries were removed from the evidence. The rationale sentence that named those alerts was replaced with a dated `[Correction 2026-10-21: ...]` note. All other evidence and judgements are unchanged, and the corrected evidence matches the regenerated evidence.
  - **Tests:** regression tests check that no case lists or names a later-dated alert, and that `build_evidence` excludes future alerts while keeping past and same-day ones.
  - **QA record:** the related observations (PRC-02) are closed.
  - **Remaining look-ahead risk:** `txns_alerted.parquet` can hold later rows for an account that appears in other accounts' histories. The case evidence and the app's timelines are bounded by the review period, so those rows are never shown.
- **Data quality:** some accounts appear under two bank locations (CASE-003, CASE-006, CASE-020). The notes qualify reliance on those transactions.
- **Earlier history:** earlier history available in the investigator data was reviewed where relevant (CASE-011, CASE-022, CASE-024). In each of these the prior alert fell before the lookback, so the earlier-alert rule did not require review. CASE-009's concurrent alert (same date) was covered by the review.
- **Figure check:** every two-decimal figure in the 23 notes was automatically checked against amounts computed from the investigator data. Exceptions were "about X million" approximations, checked manually against monthly totals.

### Resulting dispositions (all 24 cases)

| Disposition | Cases |
|---|---:|
| ESCALATE_SAR (internal disclosure) | 19 (CASE-001, 003–005, 009–011, 013–024) |
| ESCALATE_L2 | 5 (CASE-002, 006, 007, 008, 012) |
| CLOSE_NO_FURTHER_ACTION | 0 |

No case could be closed. Under Option A nothing in the record can resolve activity that far exceeds the profile, and the sampled alerts are dominated by extreme activity. The L2 cases are those where the observed pattern was consistent with a testable legitimate explanation and the decisive evidence was outside the case pack. Six outcomes are flagged as borderline for calibration (`CAL-01`).

## QA framework and results (Phase 4)

### Framework

- **Checklist** (`config/qa_checklist.yaml`): 19 questions in sections A–G, answered Yes/No/N/A.
  - E2 (outcome), F1 (disclosure), F2 (sanctions) and F3 (tipping-off/DAML) are critical.
  - A3 is the **earlier-alert rule**: where a prior alert falls within or at the boundary of the review lookback, its triggering activity must be reviewed, or the decision not to review it justified.
  - A4 bars reliance on information dated after the case.
- **Taxonomy** (`config/error_taxonomy.yaml`):
  - severities and outcome rules, with Major → Fail;
  - error codes, each tied to one severity;
  - root-cause categories, including "Not determinable" for single-case evidence;
  - remediation requirements by severity;
  - appeal handling.
- **Appeals:** the investigator appeals a scored finding in writing within 5 working days (portfolio assumption). A reviewer not involved in the original review decides: Upheld or Overturned, with reasoning. The case outcome is then recalculated. The log is `qa/appeals.csv`; it is currently empty, because no appeals have been made.
- **Engine:** `src/qa_engine.py` derives each outcome from its scored findings. Tests reconcile `qa/reviews.csv` with `qa/findings.csv` and the case files.

### Results

| Case | Outcome | Scored findings |
|---|---|---|
| CASE-001 | Pass with observations | 3 Minor (SCP-01, CP-02, ACT-01) + 1 process observation |
| CASE-002 to CASE-024 | Pass | None |

Observations, not scored (15 in total): borderline outcomes for calibration (6), look-ahead alerts in the case pack (3, now remediated and closed), data quality (3), and template, process or timeliness limitations (3, including two project-level). An earlier version of this section stated 17; that count was wrong.

### Weighted quality score

For trend MI, each case gets a score from its findings: `score = max(0, 100 − Σ deductions)`. The deductions, configured in `config/error_taxonomy.yaml`, are:

| Severity | Deduction |
|---|---:|
| Critical | 100 |
| Major | 30 |
| Minor | 10 |
| Observation | 0 |

How to read it:

- The deductions are illustrative portfolio assumptions, not calibrated weights.
- The score **never overrides the categorical outcome**. A Major-finding case scoring 70 is still a Fail, and a Minor-only case that reaches the floor is still Pass with observations.
- The score is computed by `src/qa_engine.py` (`python -m src.qa_engine` refreshes `qa/reviews.csv`).
- Current values: CASE-001 scores 70 and the other 23 cases score 100, a mean of 98.8. This reflects the non-independent review described above, not investigator performance.

### Seeded training set (prepared; not yet reviewed)

`training/seeded_cases/` contains 23 shuffled training copies (TRN-01 to TRN-23) of CASE-002 to CASE-024. Ten of them have errors planted according to the plan's error-planting table. The answer key and the seeding script are in `training/answer_key/`, which is excluded from git and never read by the app or the tests.

- **No blind review has been performed.** The assistant that designed the errors cannot review them blind.
- Until a reviewer who has not seen the key or the design reviews the set, the blind-review hit rate remains **outstanding** and is not claimed. The protocol is in `training/README.md`.

**How to read this.** CASE-002 to CASE-024 were prepared after the CASE-001 review and deliberately avoided its three findings. Their QA assessments came from the same AI-assisted workflow and were validated by the author. A clean result therefore mainly shows that the notes are internally consistent and accurate against the data. It is not an independent QA result.

### Seeded errors: status

The seeded copies now exist in `training/` (see "Seeded training set" above). The genuine notes in `cases/` were not altered. What remains is a blind review by a reviewer who has not seen the answer key or the seeding design.

### Attribution: investigator error, process weakness or data limitation

Every QA record is attributed using `config/error_taxonomy.yaml` (`attribution`):

| Attribution | Codes | Scored? |
|---|---|---|
| Investigator error | Critical, Major and Minor codes | Yes |
| Process or template weakness | PRC-* | No: owned by the process owner |
| Data limitation | DAT-* | No |
| Calibration point | CAL-* | No: needs independent calibration |

Investigators are not penalised for information that does not exist in the data, such as screening results. They are penalised only for what their note does with it. For example, recording screening as "clear" without evidence is SCR-01 (Major), while recording that results are unavailable is correct. The MI, tracker and PDF all report findings by attribution.

Current split (18 records): investigator error 3, process or template weakness 6, calibration point 6, data limitation 3.

### Worked QA examples (illustrative)

`qa/worked_examples/` holds three deliberately flawed variants of CASE-001. They share its real evidence; only the investigator's judgement fields differ. They are built by `python -m src.worked_examples` and shown in the Case Review Workbench.

| Example | What the note does | QA result |
|---|---|---|
| WEX-01 | Treats the alert as cash-only, assumes pension or savings as the source of funds, records screening as clear, and closes | Fail (Critical OUT-01, Majors RF-01, SOF-01, SCR-01); score 0 |
| WEX-02 | Reaches the right outcome (disclosure) with generic red flags, no source-of-funds assessment and no stated grounds | Fail (Majors RAT-01, RF-01, SOF-01) despite a correct disposition; score 10 |
| WEX-03 | The author's CASE-001 note with counterparties named and actions routed; earlier history still unreviewed | Pass with observations (Minor SCP-01); missing screening data recorded as a data limitation, not penalised; score 90 |

They show the core QA judgement: suspicious-looking activity is not the test. The test is whether the investigation identified, evidenced and concluded the risk. They are **not** part of the 24-case sample, the QA MI or the seeded training set. They were prepared with AI assistance, and the author's review of them is pending.

### Legal references: verification status

| Reference | Used for | Status |
|---|---|---|
| MLR 2017 reg. 28(11)(a)–(b) | Ongoing monitoring: scrutiny of transactions (including source of funds, where necessary) against knowledge of the customer, and keeping CDD up to date | Verified against legislation.gov.uk, 2026-10-22 |
| POCA 2002 s.330(2)–(4) | Disclosure duty: "knows or suspects, or has reasonable grounds for knowing or suspecting" that another person is engaged in money laundering; disclose to a nominated officer "as soon as is practicable" | Verified against legislation.gov.uk, 2026-10-22 |
| POCA 2002 s.333A(1)–(2) | Tipping off: disclosing that a disclosure has been made, where likely to prejudice an investigation | Verified against legislation.gov.uk, 2026-10-22 |
| JMLSG Guidance Part I (Ch. 5 and 6), NCA SAR guidance, SAMLA 2018 / OFSI guidance | Checklist pointers | Not verified in this project; pointers only |

The 5-working-day and same-working-day targets, the severity weights, the appeal window and the disposition definitions are **project assumptions**, not Barclays policies or statutory requirements.

### QA standards change log (governance)

| Date | Change | Reason |
|---|---|---|
| 2026-10-21 | Case template v2 adds four disclosure-tracking fields | The CASE-001 review found that disclosure timing could not be evidenced (PRC-01) |
| 2026-10-21 | Checklist A3 (earlier-alert rule) and A4 (no look-ahead) added | CASE-001 review; look-ahead defect |
| 2026-10-21 | Major → Fail outcome rule recorded; severity taxonomy, remediation and appeals defined | Plan §4b required a documented choice |
| 2026-10-21 | Look-ahead defect fixed in `case_prep.py`; three case packs corrected | PRC-02 |
| 2026-10-21 | Weighted quality score added (MI only; never overrides the outcome) | Plan §4c |
| 2026-10-22 | Attribution layer and worked QA examples added; recommendations computed from the data | Role-alignment review |
