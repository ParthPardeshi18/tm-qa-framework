from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from src.alerts import evaluate_alerts, export_history, select_sample, typology_coverage
from src.profiles import TURNOVER_BANDS, generate_profile
from src.scenarios import (
    DETECTION_COLUMNS,
    LABEL_COLUMNS,
    load_config,
    load_watchlist,
    prepare,
    run_scenarios,
    suppress,
    tm01,
    tm02,
    tm03,
    tm04,
    tm05,
    tm06,
)

D0 = date(2023, 1, 1)
CFG = {"monitored_bank_location": "UK", "suppression_days": 30}


def txn(sender, receiver, amount, day=0, ptype="ACH", s_loc="UK", r_loc="UK",
        currency="UK pounds", laundering=0, typology="Normal_Fan_Out"):
    return {
        "Date": D0 + timedelta(days=day), "Time": "10:00:00", "Sender_account": sender,
        "Receiver_account": receiver, "Amount": float(amount), "Payment_currency": currency,
        "Received_currency": currency, "Sender_bank_location": s_loc,
        "Receiver_bank_location": r_loc, "Payment_type": ptype,
        "Is_laundering": laundering, "Laundering_type": typology,
    }


def make_con(rows, with_labels=True):
    con = duckdb.connect()
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    if not with_labels:
        df = df.drop(columns=LABEL_COLUMNS)
    df.insert(0, "txn_id", range(1, len(df) + 1))
    con.register("src_df", df)
    con.execute("CREATE TABLE txns AS SELECT * FROM src_df")
    con.unregister("src_df")
    prepare(con, CFG)
    return con


# Config and jurisdiction watchlist

def test_config_has_all_scenarios_and_currency_assumption():
    cfg = load_config()
    assert set(cfg["scenarios"]) == {"TM01", "TM02", "TM03", "TM04", "TM05", "TM06"}
    assert "unverified" in cfg["currency_assumption"]


SAML_LOCATIONS = ["UK", "Albania", "Austria", "France", "Germany", "India", "Italy", "Japan", "Mexico",
                  "Morocco", "Netherlands", "Nigeria", "Pakistan", "Spain", "Switzerland", "Turkey",
                  "UAE", "USA"]


def test_watchlist_matches_dataset_names_with_aliases():
    matched, unmatched = load_watchlist(SAML_LOCATIONS)
    assert matched == ["Albania", "Nigeria", "Turkey", "UAE"]
    assert "Türkiye" not in unmatched and "United Arab Emirates" not in unmatched
    assert "Cayman Islands" in unmatched and len(matched) + len(unmatched) == 26


def test_watchlist_excludes_jurisdictions_not_on_june_2023_list():
    matched, _ = load_watchlist(SAML_LOCATIONS)
    for loc in ("Morocco", "Pakistan", "UK", "Mexico"):
        assert loc not in matched


def test_watchlist_matching_is_case_insensitive_and_returns_dataset_spelling():
    matched, _ = load_watchlist(["turkey", "uae", "ALBANIA"])
    assert matched == ["ALBANIA", "turkey", "uae"]


# Account-level aggregation

def test_legs_split_credit_and_debit_for_monitored_side_only():
    con = make_con([txn(1, 2, 100), txn(3, 4, 100, s_loc="UK", r_loc="UAE"), txn(5, 6, 100, s_loc="Spain")])
    legs = con.sql("SELECT account_id, side FROM legs ORDER BY account_id").fetchall()
    assert legs == [(1, "debit"), (2, "credit"), (3, "debit"), (6, "credit")]


def test_detect_view_has_no_label_columns():
    con = make_con([txn(1, 2, 100)])
    cols = [r[0] for r in con.sql("DESCRIBE detect").fetchall()]
    assert cols == DETECTION_COLUMNS and not set(LABEL_COLUMNS) & set(cols)


# TM01 structuring

P1 = {"payment_type": "Cash Deposit", "window_days": 7, "min_amount": 3000, "max_amount": 6000, "min_count": 3}


def deposits(amounts_days, acct=10, **kw):
    return [txn(900 + i, acct, a, d, ptype="Cash Deposit", **kw) for i, (a, d) in enumerate(amounts_days)]


def test_tm01_fires_on_three_in_band_deposits_in_7_days():
    t = tm01(make_con(deposits([(3500, 0), (4000, 3), (5999.99, 6)])), P1)
    assert t[["account_id", "trigger_date", "trigger_value"]].values.tolist() == [[10, D0 + timedelta(6), 3.0]]
    assert t["window_start"][0] == D0


def test_tm01_two_deposits_do_not_fire():
    assert tm01(make_con(deposits([(3500, 0), (4000, 1)])), P1).empty


def test_tm01_band_is_min_inclusive_max_exclusive():
    assert len(tm01(make_con(deposits([(3000, 0), (3000, 1), (3000, 2)])), P1)) == 1
    assert tm01(make_con(deposits([(6000, 0), (3000, 1), (3000, 2)])), P1).empty


def test_tm01_window_is_7_calendar_days_inclusive():
    assert tm01(make_con(deposits([(3500, 0), (3500, 3), (3500, 7)])), P1).empty  # day 0 to 7 = 8 days
    assert tm01(make_con(deposits([(3500, 1), (3500, 3), (3500, 7)])), P1)["trigger_date"].tolist() == [D0 + timedelta(7)]


def test_tm01_ignores_other_payment_types_and_other_accounts():
    rows = deposits([(3500, 0), (3500, 1)]) + [txn(1, 10, 3500, 2, ptype="ACH")] + deposits([(3500, 2)], acct=11)
    assert tm01(make_con(rows), P1).empty


def test_tm01_uses_amount_as_recorded_regardless_of_currency():
    # Currency assumption: no FX conversion. A Euro cash deposit of 3500 counts as 3500 units.
    t = tm01(make_con(deposits([(3500, 0), (3500, 1), (3500, 2)], currency="Euro")), P1)
    assert len(t) == 1


# TM02 rapid movement

P2 = {"window_days": 2, "min_credits": 50000, "min_debit_ratio": 0.9}


def test_tm02_fires_when_90pct_moved_out_within_2_days():
    t = tm02(make_con([txn(1, 10, 50000, 0), txn(10, 2, 45000, 1)]), P2)
    assert t["trigger_date"].tolist() == [D0 + timedelta(1)] and t["trigger_value"][0] == pytest.approx(0.9)


def test_tm02_boundaries():
    assert tm02(make_con([txn(1, 10, 50000, 0), txn(10, 2, 44999, 1)]), P2).empty  # ratio < 0.9
    assert tm02(make_con([txn(1, 10, 49999, 0), txn(10, 2, 49999, 0)]), P2).empty  # credits < min
    assert tm02(make_con([txn(1, 10, 50000, 0), txn(10, 2, 50000, 2)]), P2).empty  # debit outside window


def test_tm02_aggregates_multiple_credits_and_debits():
    rows = [txn(1, 10, 30000, 0), txn(2, 10, 20000, 1), txn(10, 3, 25000, 1), txn(10, 4, 20000, 1)]
    assert len(tm02(make_con(rows), P2)) == 1


# TM03 high-risk jurisdiction

P3 = {"window_days": 30, "min_total": 150000}
WL = ["Albania", "Nigeria", "Turkey", "UAE"]


def test_tm03_sums_credits_and_debits_with_watchlist_counterparties():
    rows = [txn(10, 2, 100000, 0, r_loc="UAE"), txn(3, 10, 50000, 29, s_loc="Nigeria")]
    t = tm03(make_con(rows), P3, WL)
    assert t[["account_id", "trigger_value"]].values.tolist() == [[10, 150000.0]]


def test_tm03_ignores_non_watchlist_and_out_of_window():
    rows = [txn(10, 2, 100000, 0, r_loc="Morocco"), txn(10, 3, 100000, 1, r_loc="UK"),
            txn(10, 4, 100000, 0, r_loc="UAE"), txn(10, 5, 50000, 30, r_loc="Turkey")]
    assert tm03(make_con(rows), P3, WL).empty


def test_tm03_empty_watchlist_returns_no_triggers():
    assert tm03(make_con([txn(10, 2, 1e6, 0, r_loc="UAE")]), P3, []).empty


# TM04 / TM05 fan-in and fan-out

P45 = {"window_days": 7, "min_distinct_counterparties": 20}


def test_tm04_counts_distinct_senders_in_window():
    rows = [txn(100 + i, 10, 100, i % 7) for i in range(20)]
    assert tm04(make_con(rows), P45)["trigger_value"].tolist() == [20.0]
    assert tm04(make_con(rows[:19]), P45).empty


def test_tm04_repeat_sender_counts_once():
    rows = [txn(100 + i, 10, 100, 0) for i in range(19)] + [txn(100, 10, 100, 1)]
    assert tm04(make_con(rows), P45).empty


def test_tm04_window_boundary():
    rows = [txn(100 + i, 10, 100, 0) for i in range(19)] + [txn(200, 10, 100, 7)]
    assert tm04(make_con(rows), P45).empty


def test_tm05_counts_distinct_receivers():
    rows = [txn(10, 100 + i, 100, i % 7) for i in range(20)]
    assert len(tm05(make_con(rows), P45)) == 1
    assert tm04(make_con(rows), P45).empty  # debits never count as fan-in


# TM06 behavioural change with profile

P6 = {"window_days": 30, "baseline_days": 90, "min_baseline_credit_count": 1, "min_ratio": 10,
      "min_credits": 100000, "profile_multiple": 2}


def find_account(pred):
    return next(a for a in range(1, 100000) if pred(generate_profile(a)))


LOW = find_account(lambda p: p["expected_monthly_credits_max_gbp"] < 1000)
BIG = find_account(lambda p: p["declared_income_or_turnover_band"] == TURNOVER_BANDS[3][0])  # max 416,667


def tm06_rows(acct, spike, baseline=3000):
    # Data starts D0. Baseline credit on day 30, spike on day 119 (baseline = days 0..89).
    return [txn(1, 2, 1, 0), txn(5, acct, baseline, 30), txn(6, acct, spike, 119)]


def test_tm06_fires_on_spike_above_history_and_profile():
    t = tm06(make_con(tm06_rows(LOW, 100000)), P6)
    assert t["account_id"].tolist() == [LOW] and t["trigger_date"][0] == D0 + timedelta(119)
    assert t["trigger_value"][0] == pytest.approx(100000 / 1000)  # baseline 3000 over 3 months


def test_tm06_profile_stage_suppresses_when_profile_supports_activity():
    assert tm06(make_con(tm06_rows(BIG, 200000)), P6).empty  # 200k < 2 x 416,667


def test_tm06_needs_ratio_minimum_and_full_baseline():
    assert tm06(make_con(tm06_rows(LOW, 100000, baseline=31000)), P6).empty  # ratio < 10
    assert tm06(make_con(tm06_rows(LOW, 99999, baseline=100)), P6).empty  # below min_credits
    rows = [txn(1, 2, 1, 1), txn(5, LOW, 3000, 30), txn(6, LOW, 100000, 119)]  # data starts day 1
    assert tm06(make_con(rows), P6).empty
    assert tm06(make_con([txn(1, 2, 1, 0), txn(6, LOW, 100000, 119)]), P6).empty  # no baseline credits


def test_tm06_requires_established_baseline_credit_count():
    p = dict(P6, min_baseline_credit_count=3)
    assert tm06(make_con(tm06_rows(LOW, 100000)), p).empty  # 1 baseline credit
    rows = [txn(1, 2, 1, 0), txn(5, LOW, 1000, 30), txn(7, LOW, 1000, 40), txn(8, LOW, 1000, 89),
            txn(6, LOW, 100000, 119)]
    assert len(tm06(make_con(rows), p)) == 1  # 3 baseline credits; day 89 is the last baseline day


# Duplicate suppression and pipeline

def test_suppress_keeps_first_and_next_after_suppression_period():
    t = pd.DataFrame({"account_id": [1, 1, 1, 1, 2],
                      "trigger_date": [D0, D0 + timedelta(1), D0 + timedelta(30), D0 + timedelta(31), D0]})
    kept = suppress(t, 30)
    assert kept.values.tolist() == [[1, D0], [1, D0 + timedelta(31)], [2, D0]]


def fan_in_rows():
    # 25 distinct senders to account 10 over days 0-4; one laundering-labelled credit.
    return [txn(100 + i, 10, 100, i % 5, laundering=int(i == 3), typology="Fan_In" if i == 3 else "Normal_Fan_In")
            for i in range(25)]


def test_run_scenarios_works_without_label_columns_and_ids_are_stable():
    cfg = load_config()
    a = run_scenarios(make_con(fan_in_rows(), with_labels=False), cfg, WL)
    b = run_scenarios(make_con(fan_in_rows()), cfg, WL)
    assert a.equals(b)
    assert a["alert_id"].tolist() == ["TM04-00001"] and a["account_id"].tolist() == [10]


def test_labels_do_not_change_alerts():
    cfg = load_config()
    flipped = [dict(r, Is_laundering=1 - r["Is_laundering"]) for r in fan_in_rows()]
    assert run_scenarios(make_con(fan_in_rows()), cfg, WL).equals(run_scenarios(make_con(flipped), cfg, WL))


# Evaluation, history and sampling

def test_evaluation_labels_alert_window_and_typology_coverage():
    con = make_con(fan_in_rows() + [txn(1, 2, 100, 0, laundering=1, typology="Cycle")])
    alerts = run_scenarios(con, load_config(), WL)
    ev = evaluate_alerts(con, alerts)
    assert ev["window_is_laundering"].tolist() == [True]
    assert ev["window_typologies"].tolist() == ["Fan_In"]
    cov = typology_coverage(con).set_index("typology")
    assert bool(cov.loc["Fan_In", "detected"]) and not bool(cov.loc["Cycle", "detected"])
    assert cov.loc["Fan_In", "scenarios"] == "TM04" and cov.loc["Cycle", "scenarios"] == ""


def test_export_history_respects_lookback_and_drops_labels():
    con = make_con([txn(1, 10, 100, 0), txn(10, 2, 100, 5), txn(3, 10, 100, 6), txn(4, 5, 100, 6)])
    alerts = pd.DataFrame({"account_id": [10], "trigger_date": [D0 + timedelta(6)]})
    h = export_history(con, alerts, lookback_days=6)  # days 1..6
    assert h["txn_id"].tolist() == [2, 3]
    assert not set(LABEL_COLUMNS) & set(h.columns)


def sample_pool():
    rows = []
    for sc in ("TM01", "TM02"):
        for i in range(10):
            rows.append({"alert_id": f"{sc}-{i:05d}", "scenario": sc, "account_id": i,
                         "window_is_laundering": i % 3 == 0, "planted_mismatch": i in (4, 5)})
    return pd.DataFrame(rows)


def test_sample_is_reproducible_stratified_and_account_unique():
    s1 = select_sample(sample_pool(), 4, 2, 1, "salt")
    s2 = select_sample(sample_pool().sample(frac=1, random_state=1), 4, 2, 1, "salt")
    assert s1["alert_id"].tolist() == s2["alert_id"].tolist()
    assert s1["account_id"].is_unique and len(s1) == 8
    per = s1.groupby("scenario")
    assert (per.size() == 4).all()
    assert (per["window_is_laundering"].sum() == 2).all()
    assert per["planted_mismatch"].sum().tolist() == [1, 1]


def test_sample_fills_shortfall_when_no_labelled_alerts():
    pool = sample_pool().assign(window_is_laundering=False)
    s = select_sample(pool, 4, 2, 1, "salt")
    assert len(s) == 8 and not s["window_is_laundering"].any()
