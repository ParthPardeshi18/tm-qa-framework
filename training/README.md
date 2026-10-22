# Seeded QA training set (simulation design)

`seeded_cases/` holds 23 training copies (`TRN-01` to `TRN-23`) of the case notes CASE-002 to CASE-024, in shuffled order. Some copies contain deliberately planted errors, following the error-planting plan in `docs/PROJECT_PLAN.md` (Phase 3). The rest are unchanged copies.

- **Not genuine case notes.** The genuine notes in `cases/` are unchanged. The app and the tests never read this folder.
- **Answer key** (`answer_key/`, excluded from git): the seeding script and `seeded_errors.csv`, which records each planted error with its code, severity, checklist question and expected outcome.
- **Status:** no blind review of this set has been performed. The drafting workflow that designed the errors cannot review it blind, and neither can anyone who has opened `answer_key/` or the seeding script.

## Blind review protocol

1. The reviewer must not have seen `answer_key/`, the seeding script or the conversation in which the set was designed.
2. Review each `TRN-xx.yaml` using only the training file, the investigator-facing data (`data/processed/alerts.parquet`, `profiles.parquet`, `txns_alerted.parquet`) and `config/qa_checklist.yaml`. Do not compare copies against `cases/`; that would reveal the planted changes.
3. Record findings in a separate file, for example `training/blind_review_findings.csv`, using the columns of `qa/findings.csv`.
4. Only after the review is complete, compare against `answer_key/seeded_errors.csv`. Report the hit rate (planted errors found / 10) and any false positives.

## If no independent reviewer is available

The blind-review hit rate, and any claim of independent QA validation, remain **outstanding**. They must not be estimated or claimed. The project then demonstrates the framework (checklist, taxonomy, scoring, tracker and MI) but not validated reviewer accuracy.
