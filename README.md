# Transaction Monitoring QA Framework

A portfolio project that simulates how a Transaction Monitoring **Quality Assurance** team reviews completed AML investigations. It checks whether financial crime risk was identified, investigated, evidenced and concluded correctly. The focus is reviewer judgement, not modelling.

**Live app:** [tm-app-framework-gikizvs6uqh3n4ltac67vy.streamlit.app](https://tm-app-framework-gikizvs6uqh3n4ltac67vy.streamlit.app/)

> **Synthetic data - portfolio project. Not Barclays work and not professional casework.**
> - Transactions come from the synthetic SAML-D dataset, and customer profiles are synthetic.
> - The case notes and QA assessments were reviewed by the project author. The review is a validation of the work, not an independent or blind QA review, and no blind-review hit rate is claimed (see [Authorship and review](#authorship-and-review)).
> - Nothing here is a compliance endorsement.

## At a glance

| | |
|---|---|
| **Business problem** | TM investigators close alerts every day. QA must judge whether each investigation identified the risk, evidenced it and reached a supported conclusion. Suspicious-looking activity alone is not the test. |
| **Approach** | Generate alerts with explainable rules, investigate a sample, then quality-assure the investigations against a written standard and report MI to operations leadership. |
| **QA framework** | 19-question checklist; Critical and Major → Fail, Minor only → Pass with observations; weighted score for MI only; root causes; remediation tracking; appeals. Findings are attributed to the investigator, the process or template, or the data, so investigators aren't penalised for information that doesn't exist. |
| **Results** | 11,295 alerts; 24 cases reviewed (19 Personal, 5 Business Banking); 0 Fail, 1 Pass with observations, 23 Pass; 3 Minor findings and 15 observations; 1 control defect (look-ahead) found and fixed. Three worked examples show Fail outcomes, including a Major fail despite a correct disposition. |
| **Limitations** | Synthetic data and profiles; QA assessments validated by the author, so not an independent or blind review; currency unverified; timeliness unverifiable for 23 cases. |
| **Technology** | Python, DuckDB SQL, YAML configuration, Streamlit, Plotly, reportlab, pytest. |

How each capability of a TM QA Analyst role maps to evidence here: [docs/role_mapping.md](docs/role_mapping.md).

## What it does

`Detect → Investigate → Quality-assure → Report`

1. **Detect:** six explainable rules (TM01–TM06) run in DuckDB over 9.5M synthetic transactions and raise 11,295 alerts.
2. **Investigate:** a reproducible sample of 24 alerts. Each has an evidence pack and a YAML case note: red flags, source of funds and wealth, screening, rationale, disposition and escalation.
3. **Quality-assure:**
   - a 19-question checklist (A–G);
   - a severity taxonomy: Critical or Major means **Fail**, Minor only means **Pass with observations**, none means **Pass**;
   - a findings log with remediation and owners, and an appeals process;
   - a weighted quality score for MI.
4. **Report:** a Streamlit app and a one-page [QA Findings Report](docs/QA_Findings_Report.pdf).

## Data

**SAML-D** (Oztas et al., 2023), Kaggle `berkanoztas/synthetic-transaction-monitoring-dataset-aml`:

- 9,504,852 transactions, 12 columns and 28 typologies (17 suspicious);
- 0.104% are labelled laundering;
- dates run from 2022-10-07 to 2023-08-23.

The currency of `Amount` is **unverified**: thresholds are in dataset units, and GBP is assumed only for labels. Laundering labels are **never** used to fire alerts. They are used afterwards, only for scenario-effectiveness MI. See [docs/eda_notes.md](docs/eda_notes.md).

## Results (from the stored outputs)

**Scenario effectiveness** (retrospective; an alert counts as laundering-labelled if any monitored transaction in its alert window is labelled):

| Scenario | Alerts | Laundering-labelled windows |
|---|---:|---:|
| TM01 Structuring (cash deposits) | 375 | 12.5% |
| TM02 Rapid movement of funds | 1,520 | 1.8% |
| TM03 High-risk jurisdiction (FATF 23 Jun 2023 snapshot) | 3,956 | 1.2% |
| TM04 Fan-in | 1,556 | 0.4% |
| TM05 Fan-out | 1,615 | 0.0% |
| TM06 Behavioural change vs history and profile | 2,273 | 0.4% |

**Investigations and QA (24 cases)**
- **Dispositions:** 19 internal disclosures to the MLRO, 5 L2 referrals, 0 closures.
- **QA outcomes:** 0 Fail, 1 Pass with observations (CASE-001: 3 Minor findings), 23 Pass.
- **Quality score:** mean 98.8.
- **Observations (not scored):** 15, covering 6 borderline outcomes for calibration, 3 look-ahead defects (fixed), 3 data-quality issues and 3 template or process gaps.
- **By attribution:** investigator error 3, process or template weakness 6, calibration point 6, data limitation 3.
- **Timeliness (5-working-day target, a portfolio assumption):** 1 within target, 23 not verifiable (no timestamps), 0 outside tolerance.
- **Worked QA examples** (illustrative, outside the sample): WEX-01 Fail (Critical: wrongly closed), WEX-02 Fail (Major: correct disposition, unsupported investigation), WEX-03 Pass with observations (Minor; data limitation not penalised).
- **Reading the figures:** they show the framework working. They are **not** evidence of investigator quality, because the QA assessments were prepared in the same workflow as the case notes and validated by the author, not by an independent reviewer.

## Key limitations and unresolved control issues

- No independent or blind review has taken place. The seeded training set ([training/](training/README.md)) has not yet been reviewed.
- CASE-002 to CASE-024 have no case-handling or disclosure timestamps, so timeliness can't be verified (this is not treated as lateness).
- No escalation ownership procedure exists in the simulation.
- Thresholds were tuned on alert volume using the same data they run on (in-sample), and the watchlist is a single June 2023 snapshot.
- Some accounts appear under two bank locations.
- **Look-ahead defect (fixed):** case packs listed alerts dated after the case. The cause was corrected and regression tests were added.

## Recommendations (evidence in the report and MI page)

1. **Recalibrate the low-yield scenarios.** TM05, TM04 and TM06 return 0.0–0.4% labelled windows, against 12.5% for TM01.
2. **Calibrate outcomes independently before relying on the QA pass rate.** Six outcomes are borderline, and no review so far has been independent of the case preparation.
3. **Close the case-handling control gaps.** Make disclosure timestamps mandatory, define escalation ownership, and apply the earlier-alert rule (checklist A3).

## Setup and run

Requires **Python 3.11 or newer** (pandas 3 needs 3.11+). The dependencies in `requirements.txt` are pinned to the versions verified in a clean Python 3.11 environment, where the full test suite passed.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

The app and tests only need the committed outputs in `data/processed/`, `cases/`, `qa/` and `config/`.

```bash
streamlit run app/Home.py
```

```bash
python -m pytest
```

```bash
python -m src.report
```

`python -m src.report` regenerates `docs/QA_Findings_Report.pdf`.

To rebuild everything from raw data (optional, about 1 minute; needs the SAML-D CSV at `data/raw/SAML-D.csv`, which is not committed):

```bash
python -m src.alerts
```

This regenerates alerts, profiles, evaluation files and the sample. Re-running under the pinned duckdb 2.0.0 reproduces every committed output exactly, except for floating-point noise in `alerts.trigger_value` (at most 2.3e-10, from summation order). Alert IDs, accounts, dates and the 24-alert sample are unchanged. `python -m src.case_prep` builds blank case templates and never overwrites a case that has investigator content. `python -m src.qa_engine` recomputes QA outcomes and scores from `qa/findings.csv`.

## Deployment

The app is live on Streamlit Community Cloud at https://tm-app-framework-gikizvs6uqh3n4ltac67vy.streamlit.app/, deployed from branch `main` with main file `app/Home.py`. The steps below record how it was published and can be repeated for a fork.

**What gets committed:** `app/`, `src/`, `config/`, `cases/`, `qa/`, `tests/`, `docs/` (including the PDF), `training/README.md`, `training/seeded_cases/`, `data/processed/` app inputs, `requirements.txt`, `pytest.ini`, `README.md` and `.gitignore`. That is about 31 MB, and the largest file is `data/processed/txns_alerted.parquet` at 29.5 MB, under GitHub's 100 MB limit.

**What stays excluded (via `.gitignore`):**
- the raw SAML-D CSV;
- the sample answer key, profile answer key and per-alert evaluation file;
- `training/answer_key/`;
- `.venv/`, caches and `.claude/`;
- the unrelated Telco CSV.

The app reads only committed files, through paths relative to the repository, so the raw data is not needed online.

**Steps:**

1. Create an empty GitHub repository, for example `tm-qa-framework` (public or private). This needs your GitHub account.
2. From the project folder, commit and push:

   ```bash
   git checkout -b main
   ```

   ```bash
   git add .
   ```

   ```bash
   git status
   ```

   Check that no `SAML-D.csv`, `*_key*`, `alert_evaluation` or `training/answer_key` file is listed, then commit and push:

   ```bash
   git commit -m "Transaction Monitoring QA framework (synthetic portfolio project)"
   ```

   ```bash
   git remote add origin https://github.com/<your-user>/tm-qa-framework.git
   ```

   ```bash
   git push -u origin main
   ```

3. At share.streamlit.io: **Create app** → choose the repository, branch `main`, and main file path `app/Home.py`. Under **Advanced settings**, choose Python 3.11 or newer. No secrets are needed.
4. After the build, open each of the seven pages at desktop and mobile width and confirm the disclaimer is shown.

## Repository

| Path | Contents |
|---|---|
| `src/` | `profiles.py` (synthetic KYC), `scenarios.py` (TM rules), `alerts.py` (pipeline), `case_prep.py` (evidence packs), `qa_engine.py` (outcomes, scores), `worked_examples.py` (illustrative QA examples), `app_data.py` / `app_ui.py` (app), `report.py` (PDF) |
| `config/` | Scenario thresholds, FATF watchlist, QA checklist, error taxonomy |
| `cases/` | 24 case notes (YAML) |
| `qa/` | `reviews.csv`, `findings.csv`, `appeals.csv`; `worked_examples/` (3 illustrative flawed notes with their QA findings) |
| `app/` | Streamlit app (Home plus 6 pages) |
| `training/` | Seeded QA training copies; the answer key is git-ignored |
| `docs/` | Project plan, EDA notes, methodology, role mapping, scenario effectiveness, QA Findings Report |
| `tests/` | pytest suite |

## Authorship and review

- Case notes CASE-002 to CASE-024 and their QA assessments were drafted with an AI tool and reviewed by the project author for factual accuracy and consistency; CASE-001 was written by the author.
- The author's review covered:
  - the transaction evidence and the figures in each note;
  - the investigative reasoning;
  - the QA findings;
  - whether the conclusions are consistent with the documented methodology.
- This is the author's own validation, not an independent assessment by a second reviewer. No blind review has been performed. The sample answer key was also seen during preparation, so no blind-review metric is derived from these notes.
- The regulatory references (POCA 2002 ss.330 and 333A, MLR 2017 reg. 28, JMLSG Part I, NCA SAR guidance) are pointers. Verify the exact provisions before citing them.

Full detail: [docs/methodology.md](docs/methodology.md).
