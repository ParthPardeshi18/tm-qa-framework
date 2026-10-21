"""Transaction monitoring scenarios TM01-TM06 (Phase 2), as DuckDB SQL.

Input: a DuckDB table `txns` with the SAML-D columns plus a `txn_id`.

Rules only ever read the `detect` view, which drops Is_laundering and
Laundering_type. Labels are used afterwards for evaluation only (src/alerts.py).

Account aggregation: each transaction gives up to two legs. The credit leg
belongs to Receiver_account, the debit leg to Sender_account. A leg is
monitored only if its own-side bank location is `monitored_bank_location`.
Cash deposits count as credits to Receiver_account.

Windows: window_days N covers the N calendar days ending on the trigger date,
inclusive. Rules are evaluated on dates with activity. Each rule returns at
most one trigger per account per date. suppress() then turns triggers into
alerts.

Amounts are used as recorded (dataset monetary units, currency unverified, no
FX conversion). See config/scenarios.yaml.
"""

from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

from src.profiles import generate_profiles

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
LABEL_COLUMNS = ["Is_laundering", "Laundering_type"]
DETECTION_COLUMNS = [
    "txn_id", "Date", "Time", "Sender_account", "Receiver_account", "Amount",
    "Payment_currency", "Received_currency", "Sender_bank_location",
    "Receiver_bank_location", "Payment_type",
]
TRIGGER_COLUMNS = ["account_id", "trigger_date", "window_start", "trigger_value", "trigger_detail"]


def load_config(path=CONFIG_DIR / "scenarios.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_watchlist(locations, path=CONFIG_DIR / "high_risk_jurisdictions.yaml"):
    """Match watchlist names to dataset locations.

    Returns (matched dataset location values, FATF names with no match).
    """
    with open(path, encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    aliases = wl.get("dataset_name_aliases") or {}
    by_key = {loc.strip().casefold(): loc for loc in locations}
    matched, unmatched = [], []
    for name in wl["jurisdictions"]:
        loc = by_key.get(aliases.get(name, name).strip().casefold())
        (matched if loc else unmatched).append(loc or name)
    return sorted(set(matched)), unmatched


def _str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _window(days: int) -> str:
    return f"PARTITION BY account_id ORDER BY date RANGE BETWEEN INTERVAL {int(days) - 1} DAYS PRECEDING AND CURRENT ROW"


def prepare(con, cfg: dict) -> None:
    """Create the label-free `detect` view, monitored `legs` and per-day `daily` totals."""
    con.execute(f"CREATE OR REPLACE TEMP VIEW detect AS SELECT {', '.join(DETECTION_COLUMNS)} FROM txns")
    loc = _str(cfg["monitored_bank_location"])
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE legs AS
        SELECT txn_id, Receiver_account AS account_id, Sender_account AS counterparty_id, Date AS date,
               Amount AS amount, 'credit' AS side, Payment_type AS payment_type,
               Receiver_bank_location AS own_location, Sender_bank_location AS counterparty_location
        FROM detect WHERE Receiver_bank_location = {loc}
        UNION ALL
        SELECT txn_id, Sender_account, Receiver_account, Date, Amount, 'debit', Payment_type,
               Sender_bank_location, Receiver_bank_location
        FROM detect WHERE Sender_bank_location = {loc}
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE daily AS
        SELECT account_id, date,
               coalesce(sum(amount) FILTER (WHERE side = 'credit'), 0) AS credits,
               count(*) FILTER (WHERE side = 'credit') AS credit_count,
               coalesce(sum(amount) FILTER (WHERE side = 'debit'), 0) AS debits
        FROM legs GROUP BY ALL
    """)


def _finish(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    df["trigger_date"] = pd.to_datetime(df["trigger_date"]).dt.date
    df["window_start"] = df["trigger_date"] - timedelta(days=int(window_days) - 1)
    return df[TRIGGER_COLUMNS].sort_values(["account_id", "trigger_date"], ignore_index=True)


def tm01(con, p) -> pd.DataFrame:
    df = con.sql(f"""
        WITH x AS (
            SELECT account_id, date, count(*) OVER w AS n, sum(amount) OVER w AS total
            FROM legs
            WHERE side = 'credit' AND payment_type = {_str(p['payment_type'])}
              AND amount >= {float(p['min_amount'])} AND amount < {float(p['max_amount'])}
            WINDOW w AS ({_window(p['window_days'])}))
        SELECT account_id, date AS trigger_date, max(n) AS n, max(total) AS total
        FROM x WHERE n >= {int(p['min_count'])} GROUP BY ALL
    """).df()
    df["trigger_value"] = df["n"].astype(float)
    df["trigger_detail"] = [
        f"{n} cash deposits of {p['min_amount']:,}-<{p['max_amount']:,} totalling {t:,.2f} in {p['window_days']} days"
        for n, t in zip(df["n"], df["total"])
    ]
    return _finish(df, p["window_days"])


def tm02(con, p) -> pd.DataFrame:
    df = con.sql(f"""
        WITH x AS (
            SELECT account_id, date, sum(credits) OVER w AS cr, sum(debits) OVER w AS db
            FROM daily WINDOW w AS ({_window(p['window_days'])}))
        SELECT account_id, date AS trigger_date, cr, db FROM x
        WHERE cr >= {float(p['min_credits'])} AND db >= {float(p['min_debit_ratio'])} * cr
    """).df()
    df["trigger_value"] = df["db"] / df["cr"]
    df["trigger_detail"] = [
        f"credits {c:,.2f} and debits {d:,.2f} ({d / c:.0%}) within {p['window_days']} days"
        for c, d in zip(df["cr"], df["db"])
    ]
    return _finish(df, p["window_days"])


def tm03(con, p, watchlist) -> pd.DataFrame:
    if not watchlist:
        return pd.DataFrame(columns=TRIGGER_COLUMNS)
    names = ", ".join(_str(w) for w in watchlist)
    df = con.sql(f"""
        WITH x AS (
            SELECT account_id, date, sum(amount) OVER w AS total, count(*) OVER w AS n
            FROM legs
            WHERE counterparty_location IN ({names}) AND counterparty_location <> own_location
            WINDOW w AS ({_window(p['window_days'])}))
        SELECT account_id, date AS trigger_date, max(total) AS total, max(n) AS n
        FROM x WHERE total >= {float(p['min_total'])} GROUP BY ALL
    """).df()
    df["trigger_value"] = df["total"]
    df["trigger_detail"] = [
        f"{n} transactions totalling {t:,.2f} with watchlist jurisdictions in {p['window_days']} days"
        for n, t in zip(df["n"], df["total"])
    ]
    return _finish(df, p["window_days"])


def _fan(con, p, side: str, noun: str) -> pd.DataFrame:
    df = con.sql(f"""
        WITH x AS (
            SELECT account_id, date,
                   count(DISTINCT counterparty_id) OVER w AS n, sum(amount) OVER w AS total
            FROM legs WHERE side = {_str(side)}
            WINDOW w AS ({_window(p['window_days'])}))
        SELECT account_id, date AS trigger_date, max(n) AS n, max(total) AS total
        FROM x WHERE n >= {int(p['min_distinct_counterparties'])} GROUP BY ALL
    """).df()
    df["trigger_value"] = df["n"].astype(float)
    df["trigger_detail"] = [
        f"{n} distinct {noun}, {side}s totalling {t:,.2f} in {p['window_days']} days"
        for n, t in zip(df["n"], df["total"])
    ]
    return _finish(df, p["window_days"])


def tm04(con, p) -> pd.DataFrame:
    return _fan(con, p, "credit", "senders")


def tm05(con, p) -> pd.DataFrame:
    return _fan(con, p, "debit", "receivers")


def tm06(con, p) -> pd.DataFrame:
    """Two stages. (1) 30-day credits >= min_ratio x baseline monthly average and
    >= min_credits. Needs a full baseline inside the data with at least
    min_baseline_credit_count credits (and a positive total).
    (2) Profiles for stage-1 accounts only. Keep a trigger if window credits
    >= profile_multiple x expected_monthly_credits_max_gbp x (window_days / 30)."""
    w, b = int(p["window_days"]), int(p["baseline_days"])
    baseline = f"PARTITION BY account_id ORDER BY date RANGE BETWEEN INTERVAL {w + b - 1} DAYS PRECEDING AND INTERVAL {w} DAYS PRECEDING"
    df = con.sql(f"""
        WITH x AS (
            SELECT account_id, date,
                   sum(credits) OVER ({_window(w)}) AS cr,
                   sum(credits) OVER ({baseline}) AS base,
                   sum(credit_count) OVER ({baseline}) AS base_n
            FROM daily)
        SELECT account_id, date AS trigger_date, cr, base / ({b} / 30.0) AS base_monthly FROM x
        WHERE date - {w + b - 1} >= (SELECT min(date) FROM daily)
          AND base > 0 AND base_n >= {int(p['min_baseline_credit_count'])}
          AND cr >= {float(p['min_credits'])}
          AND cr >= {float(p['min_ratio'])} * base / ({b} / 30.0)
    """).df()
    profiles = generate_profiles(df["account_id"].unique())[["account_id", "expected_monthly_credits_max_gbp"]]
    df = df.merge(profiles, on="account_id")
    expected = df["expected_monthly_credits_max_gbp"] * w / 30
    df = df[df["cr"] >= float(p["profile_multiple"]) * expected].copy()
    df["trigger_value"] = df["cr"] / df["base_monthly"]
    df["trigger_detail"] = [
        f"{w}-day credits {c:,.2f} = {c / m:.1f}x baseline monthly average {m:,.2f}; "
        f"profile expected monthly max {e:,}"
        for c, m, e in zip(df["cr"], df["base_monthly"], df["expected_monthly_credits_max_gbp"])
    ]
    return _finish(df, w)


def suppress(triggers: pd.DataFrame, days: int) -> pd.DataFrame:
    """Keep the first trigger per account. Drop later triggers on dates
    <= last kept date + days; the next trigger after that starts a new alert."""
    keep, last = [], {}
    for i, (acct, d) in enumerate(zip(triggers["account_id"], triggers["trigger_date"])):
        if acct not in last or (d - last[acct]).days > days:
            keep.append(i)
            last[acct] = d
    return triggers.iloc[keep].reset_index(drop=True)


def run_scenarios(con, cfg: dict, watchlist) -> pd.DataFrame:
    """All alerts, after per-scenario suppression, with stable alert IDs."""
    prepare(con, cfg)
    sc = cfg["scenarios"]
    triggers = {
        "TM01": tm01(con, sc["TM01"]),
        "TM02": tm02(con, sc["TM02"]),
        "TM03": tm03(con, sc["TM03"], watchlist),
        "TM04": tm04(con, sc["TM04"]),
        "TM05": tm05(con, sc["TM05"]),
        "TM06": tm06(con, sc["TM06"]),
    }
    frames = []
    for sid, t in triggers.items():
        a = suppress(t.sort_values(["account_id", "trigger_date"], ignore_index=True), cfg["suppression_days"])
        a = a.sort_values(["trigger_date", "account_id"], ignore_index=True)
        a.insert(0, "alert_id", [f"{sid}-{i + 1:05d}" for i in range(len(a))])
        a.insert(1, "scenario", sid)
        a.insert(2, "scenario_name", sc[sid]["name"])
        frames.append(a)
    return pd.concat(frames, ignore_index=True)
