"""Alert generation pipeline (Phase 2).

    python -m src.alerts

Loads the raw SAML-D CSV into DuckDB (read-only, not pandas), runs TM01-TM06,
and writes to data/processed:

Investigator-facing (no labels, no planted answer key):
  alerts.parquet        one row per alert
  profiles.parquet      synthetic profiles of alerted accounts (no planted_* fields)
  txns_alerted.parquet  raw transactions of alerted accounts, history_lookback_days
                        up to each trigger date, label columns dropped
  alert_sample.csv      the investigation sample

Answer key / evaluation (retrospective only, never a rule input):
  alert_evaluation.parquet   laundering labels inside each alert window
  profiles_answer_key.parquet  planted_* fields per alerted account
  alert_sample_key.csv       labels and planted flags for the sample
  scenario_effectiveness.csv, typology_coverage.csv, docs/scenario_effectiveness.md

Alert window label: an alert is "laundering-labelled" if any monitored leg of
the alerted account dated inside [window_start, trigger_date] has
Is_laundering = 1. Typology coverage: a laundering transaction is "covered"
if it is such a leg for at least one alert. A typology is "detected" if at
least one of its transactions is covered.
"""

import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from src.profiles import generate_profiles
from src.scenarios import DETECTION_COLUMNS, load_config, load_watchlist, run_scenarios

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "data" / "raw" / "SAML-D.csv"
OUT = ROOT / "data" / "processed"
PLANTED_FIELDS = ["planted_mismatch", "planted_mismatch_type", "planted_mismatch_note"]


def load_transactions(con, csv_path=RAW_CSV) -> None:
    """Create `txns` from the CSV. txn_id follows a full sort on the detection
    columns (no exact duplicate rows exist, docs/eda_notes.md), so it is stable."""
    path = str(csv_path).replace("'", "''")
    con.execute(f"""
        CREATE OR REPLACE TABLE txns AS
        SELECT row_number() OVER (ORDER BY Date, Time, Sender_account, Receiver_account, Amount,
                                  Payment_currency, Received_currency, Sender_bank_location,
                                  Receiver_bank_location, Payment_type) AS txn_id, *
        FROM read_csv('{path}')
    """)


def evaluate_alerts(con, alerts: pd.DataFrame) -> pd.DataFrame:
    """Per alert: laundering-labelled legs inside the alert window (retrospective)."""
    con.register("alerts_df", alerts[["alert_id", "account_id", "window_start", "trigger_date"]])
    con.execute("""
        CREATE OR REPLACE TEMP TABLE alert_legs AS
        SELECT a.alert_id, l.txn_id, t.Is_laundering, t.Laundering_type
        FROM alerts_df a
        JOIN legs l ON l.account_id = a.account_id AND l.date BETWEEN a.window_start AND a.trigger_date
        JOIN txns t ON t.txn_id = l.txn_id
    """)
    ev = con.sql("""
        SELECT a.alert_id,
               count(l.txn_id) AS window_txns,
               coalesce(sum(l.Is_laundering), 0) AS window_laundering_txns,
               coalesce(sum(l.Is_laundering), 0) > 0 AS window_is_laundering,
               coalesce(string_agg(DISTINCT CASE WHEN l.Is_laundering = 1 THEN l.Laundering_type END, '; '
                                   ORDER BY CASE WHEN l.Is_laundering = 1 THEN l.Laundering_type END), '')
                   AS window_typologies
        FROM alerts_df a LEFT JOIN alert_legs l USING (alert_id)
        GROUP BY a.alert_id
    """).df()
    con.unregister("alerts_df")
    return alerts[["alert_id", "scenario"]].merge(ev, on="alert_id")


def typology_coverage(con) -> pd.DataFrame:
    """Suspicious typologies: laundering transactions covered by any alert window.
    Needs the alert_legs table created by evaluate_alerts()."""
    return con.sql("""
        WITH pairs AS (
            SELECT DISTINCT l.Laundering_type AS typology, split_part(l.alert_id, '-', 1) AS scenario
            FROM alert_legs l WHERE l.Is_laundering = 1),
        by_typology AS (
            SELECT typology, string_agg(scenario, ', ' ORDER BY scenario) AS scenarios FROM pairs GROUP BY 1),
        covered AS (SELECT DISTINCT txn_id FROM alert_legs WHERE Is_laundering = 1),
        monitored AS (SELECT DISTINCT txn_id FROM legs),
        counts AS (
            SELECT t.Laundering_type AS typology,
                   count(*) AS laundering_txns,
                   count(m.txn_id) AS monitored_txns,
                   count(c.txn_id) AS covered_txns,
                   round(100.0 * count(c.txn_id) / count(*), 1) AS coverage_pct,
                   count(c.txn_id) > 0 AS detected
            FROM txns t
            LEFT JOIN monitored m USING (txn_id)
            LEFT JOIN covered c USING (txn_id)
            WHERE t.Is_laundering = 1
            GROUP BY 1)
        SELECT counts.*, coalesce(b.scenarios, '') AS scenarios
        FROM counts LEFT JOIN by_typology b USING (typology)
        ORDER BY coverage_pct DESC, typology
    """).df()


def scenario_effectiveness(alerts: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    df = alerts[["alert_id", "scenario", "scenario_name", "account_id"]].merge(ev, on=["alert_id", "scenario"])
    rows = []
    for (sid, name), g in df.groupby(["scenario", "scenario_name"]):
        typologies = sorted({t for s in g["window_typologies"] for t in s.split("; ") if t})
        rows.append({
            "scenario": sid, "scenario_name": name, "alerts": len(g),
            "accounts": g["account_id"].nunique(),
            "laundering_labelled_alerts": int(g["window_is_laundering"].sum()),
            "laundering_labelled_pct": round(100 * g["window_is_laundering"].mean(), 1),
            "typologies_in_windows": ", ".join(typologies),
        })
    return pd.DataFrame(rows)


def select_sample(df: pd.DataFrame, per_scenario: int, labelled_per_scenario: int,
                  planted_per_scenario: int, salt: str) -> pd.DataFrame:
    """Reproducible stratified sample. Needs columns alert_id, scenario, account_id,
    window_is_laundering, planted_mismatch. Order within a scenario is
    sha256(salt|alert_id). Picks at most planted_per_scenario planted accounts,
    then non-planted labelled windows up to labelled_per_scenario, then
    unlabelled, then fills any shortfall from the remaining non-planted alerts.
    An account appears at most once in the sample."""
    df = df.assign(_h=[hashlib.sha256(f"{salt}|{a}".encode()).hexdigest() for a in df["alert_id"]])
    picked, used = [], set()
    for _, g in df.sort_values(["scenario", "_h"]).groupby("scenario", sort=True):
        chosen = []

        def take(rows, n):
            for r in rows.itertuples():
                if len(chosen) >= per_scenario or n <= 0:
                    return
                if r.account_id not in used:
                    chosen.append(r)
                    used.add(r.account_id)
                    n -= 1

        take(g[g["planted_mismatch"]], planted_per_scenario)
        rest = g[~g["planted_mismatch"]]  # planted cap is strict
        n_lab = sum(bool(c.window_is_laundering) for c in chosen)
        take(rest[rest["window_is_laundering"]], labelled_per_scenario - n_lab)
        n_unlab = sum(not c.window_is_laundering for c in chosen)
        take(rest[~rest["window_is_laundering"]], (per_scenario - labelled_per_scenario) - n_unlab)
        take(rest, per_scenario)
        picked += [c.alert_id for c in chosen]
    return df[df["alert_id"].isin(picked)].drop(columns="_h").sort_values("alert_id", ignore_index=True)


def export_history(con, alerts: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """Raw rows (labels dropped) where an alerted account is sender or receiver,
    dated within lookback_days up to any of that account's trigger dates."""
    spans = alerts.groupby(["account_id", "trigger_date"], as_index=False).size()[["account_id", "trigger_date"]]
    con.register("spans", spans)
    cols = ", ".join(f"t.{c}" for c in DETECTION_COLUMNS)
    df = con.sql(f"""
        WITH s AS (SELECT account_id, trigger_date - {int(lookback_days) - 1} AS start_date, trigger_date FROM spans),
        hit AS (
            SELECT t.txn_id FROM txns t JOIN s ON t.Receiver_account = s.account_id
                AND t.Date BETWEEN s.start_date AND s.trigger_date
            UNION
            SELECT t.txn_id FROM txns t JOIN s ON t.Sender_account = s.account_id
                AND t.Date BETWEEN s.start_date AND s.trigger_date)
        SELECT {cols} FROM txns t JOIN hit USING (txn_id) ORDER BY t.txn_id
    """).df()
    con.unregister("spans")
    return df


def _md_table(df: pd.DataFrame) -> str:
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def write_effectiveness_doc(path, eff, cov, sample_key, cfg, watchlist, unmatched) -> None:
    detected = cov[cov["detected"]]["typology"].tolist()
    missed = cov[~cov["detected"]]["typology"].tolist()
    mix = sample_key.groupby("scenario").agg(
        sampled=("alert_id", "size"),
        laundering_labelled=("window_is_laundering", "sum"),
        planted_mismatch=("planted_mismatch", "sum"),
    ).reset_index()
    text = f"""# Scenario Effectiveness (Phase 2)

Generated by `python -m src.alerts`. Synthetic data (SAML-D). Do not edit by hand.

Labels (`Is_laundering`, `Laundering_type`) are used **only here, after detection**.
The rules read a label-free view.

## How it is measured

- **Alert window:** `[window_start, trigger_date]` for the scenario's rolling window.
- **Laundering-labelled alert:** at least one monitored leg of the alerted account inside
  its alert window has `Is_laundering = 1`. The leg can be a credit or a debit, from any
  payment type, not only the legs that met the rule. This is a window-level label, not
  proof that the rule "caught" that transaction.
- **Typology coverage:** a laundering transaction is covered if it is a leg inside at
  least one alert window. A typology is **detected** if at least one of its transactions
  is covered.
- `monitored_txns`: laundering transactions with at least one side at a
  `{cfg['monitored_bank_location']}` bank. Others can never be covered.
- Amounts are in dataset monetary units; the currency is unverified.
- TM03 watchlist: FATF increased monitoring, 23 June 2023 snapshot. Matched locations:
  {', '.join(watchlist)}. FATF names with no SAML-D location: {len(unmatched)}.

## Alerts by scenario

{_md_table(eff)}

Total alerts: {int(eff['alerts'].sum()):,}. Distinct alerted accounts across all scenarios are
counted in `profiles.parquet`.

## Typology coverage

Detected ({len(detected)}): {', '.join(detected) or 'none'}

Missed ({len(missed)}): {', '.join(missed) or 'none'}

{_md_table(cov)}

## Investigation sample

{_md_table(mix)}

Sample alerts: `data/processed/alert_sample.csv` (investigator-facing).
Answer key: `data/processed/alert_sample_key.csv`.
"""
    Path(path).write_text(text, encoding="utf-8")


def main() -> None:
    cfg = load_config()
    con = duckdb.connect()
    load_transactions(con)
    locations = [r[0] for r in con.sql(
        "SELECT DISTINCT Sender_bank_location FROM txns UNION SELECT DISTINCT Receiver_bank_location FROM txns"
    ).fetchall()]
    watchlist, unmatched = load_watchlist(locations)
    print("watchlist matched:", watchlist)

    alerts = run_scenarios(con, cfg, watchlist)
    print(alerts.groupby("scenario").size().to_string())

    ev = evaluate_alerts(con, alerts)
    cov = typology_coverage(con)
    eff = scenario_effectiveness(alerts, ev)

    profiles = generate_profiles(alerts["account_id"].unique())
    key = profiles[["account_id"] + PLANTED_FIELDS]

    s = cfg["sample"]
    pool = alerts.merge(ev, on=["alert_id", "scenario"]).merge(key, on="account_id")
    sample = select_sample(pool, s["per_scenario"], s["labelled_per_scenario"], s["planted_per_scenario"], s["salt"])

    history = export_history(con, alerts, cfg["history_lookback_days"])

    OUT.mkdir(parents=True, exist_ok=True)
    alerts.to_parquet(OUT / "alerts.parquet", index=False, compression="zstd")
    profiles.drop(columns=PLANTED_FIELDS).to_parquet(OUT / "profiles.parquet", index=False, compression="zstd")
    history.to_parquet(OUT / "txns_alerted.parquet", index=False, compression="zstd")
    sample[alerts.columns].to_csv(OUT / "alert_sample.csv", index=False)
    ev.to_parquet(OUT / "alert_evaluation.parquet", index=False, compression="zstd")
    key.to_parquet(OUT / "profiles_answer_key.parquet", index=False, compression="zstd")
    sample[["alert_id", "scenario", "account_id", "window_txns", "window_laundering_txns",
            "window_is_laundering", "window_typologies"] + PLANTED_FIELDS].to_csv(
        OUT / "alert_sample_key.csv", index=False)
    eff.to_csv(OUT / "scenario_effectiveness.csv", index=False)
    cov.to_csv(OUT / "typology_coverage.csv", index=False)
    write_effectiveness_doc(ROOT / "docs" / "scenario_effectiveness.md", eff, cov, sample, cfg, watchlist, unmatched)

    for f in sorted(OUT.glob("*")):
        if f.is_file() and f.name != ".gitkeep":
            print(f"{f.name}: {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
