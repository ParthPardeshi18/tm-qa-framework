"""Phase 3 preparation: one YAML case template per sampled alert.

    python -m src.case_prep            # writes cases/CASE-001.yaml ... (skips existing files)
    python -m src.case_prep --force    # overwrite blank templates; completed cases are never overwritten

Reads ONLY investigator-facing files: alert_sample.csv, alerts.parquet,
profiles.parquet, txns_alerted.parquet and the TM03 watchlist config. It never
opens evaluation or answer-key files, and those inputs carry no labels.

Pre-filled: verifiable facts (alert, synthetic KYC profile, transaction evidence).
Left null for the investigator: dates opened/closed, red flags, source of funds,
screening, rationale, disposition, escalation decision, and the disclosure-tracking
fields (suspicion_formed_at, internal_disclosure_at, disclosure_recipient,
referral_evidence).

Template versions: CASE-001 was completed on the v1 template (CASE_FIELDS_V1),
which has no disclosure-tracking fields. The other cases use v2 (CASE_FIELDS).

Investigators: cases are ordered by alert_id and assigned INV-A, INV-B, INV-C in
rotation. The rule is mechanical and blind to labels.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

from src.profiles import DATASET_START
from src.scenarios import load_config, load_watchlist

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CASES_DIR = ROOT / "cases"
INVESTIGATORS = ["INV-A", "INV-B", "INV-C"]
TOP_COUNTERPARTIES = 5
JUDGEMENT_FIELDS = [
    "date_opened", "date_closed", "red_flags_identified", "source_of_funds",
    "screening_adverse_media", "rationale", "disposition", "escalation_decision",
]
DISCLOSURE_FIELDS = [
    "suspicion_formed_at", "internal_disclosure_at", "disclosure_recipient", "referral_evidence",
]
CASE_FIELDS_V1 = [
    "case_id", "alert_id", "scenario", "investigator", "account_id", "alert_date",
    "date_opened", "date_closed", "customer_summary", "activity_reviewed", "evidence",
    "red_flags_identified", "source_of_funds", "screening_adverse_media", "rationale",
    "disposition", "escalation_decision",
]
CASE_FIELDS = CASE_FIELDS_V1 + DISCLOSURE_FIELDS
V1_CASES = {"CASE-001"}
HEADER = """\
# Investigation case note: SYNTHETIC DATA, SIMULATED CASE.
# Pre-filled: facts from investigator-facing data only (alert, synthetic KYC profile,
# transactions). Amounts are in dataset monetary units (GBP assumed, unverified).
# Do not edit `evidence`: tests/test_cases.py re-derives it from the source data.
# Complete the null fields:
#   date_opened / date_closed: YYYY-MM-DD
#   red_flags_identified:      list of strings
#   source_of_funds:           assessment of source of funds / wealth
#   screening_adverse_media:   sanctions / PEP / adverse-media assessment
#                              (no screening results exist in the data; the PEP and
#                              adverse-media values in the evidence are KYC flags on file)
#   rationale:                 reasoning that supports the disposition
#   disposition:               CLOSE_NO_FURTHER_ACTION | ESCALATE_L2 | ESCALATE_SAR
#   escalation_decision:       what is escalated, to whom, and why (or why not)
# Disclosure tracking (leave null if no internal disclosure is made; never estimate):
#   suspicion_formed_at:       ISO 8601 date-time, e.g. 2023-02-16T15:30:00
#   internal_disclosure_at:    ISO 8601 date-time of the internal disclosure
#   disclosure_recipient:      e.g. Nominated officer / MLRO
#   referral_evidence:         reference or summary of the evidence supporting the referral
"""


def load_inputs():
    sample = pd.read_csv(PROCESSED / "alert_sample.csv")
    alerts = pd.read_parquet(PROCESSED / "alerts.parquet")
    profiles = pd.read_parquet(PROCESSED / "profiles.parquet")
    txns = pd.read_parquet(PROCESSED / "txns_alerted.parquet")
    txns["Date"] = pd.to_datetime(txns["Date"]).dt.date
    return sample, alerts, profiles, txns


def _money(x) -> float:
    return round(float(x), 2)


def summarise(df: pd.DataFrame, account_id: int, watchlist) -> dict:
    """Factual totals for one account's transactions (credits = account is receiver)."""
    cr = df[df["Receiver_account"] == account_id]
    db = df[df["Sender_account"] == account_id]
    # Counterparty location: the other side of each transaction.
    cp = pd.concat([
        pd.DataFrame({"location": cr["Sender_bank_location"], "amount": cr["Amount"]}),
        pd.DataFrame({"location": db["Receiver_bank_location"], "amount": db["Amount"]}),
    ])
    by_type = {}
    for ptype in sorted(set(cr["Payment_type"]) | set(db["Payment_type"])):
        c, d = cr[cr["Payment_type"] == ptype], db[db["Payment_type"] == ptype]
        by_type[ptype] = {
            "credits_count": len(c), "credits_total": _money(c["Amount"].sum()),
            "debits_count": len(d), "debits_total": _money(d["Amount"].sum()),
        }
    locations = {
        loc: {"count": len(g), "total": _money(g["amount"].sum())}
        for loc, g in sorted(cp.groupby("location"), key=lambda kv: kv[0])
    }
    wl = cp[cp["location"].isin(watchlist)]
    non_gbp = df[(df["Payment_currency"] != "UK pounds") | (df["Received_currency"] != "UK pounds")]
    return {
        "transactions": len(df),
        "credits_count": len(cr),
        "credits_total": _money(cr["Amount"].sum()),
        "debits_count": len(db),
        "debits_total": _money(db["Amount"].sum()),
        "distinct_senders": int(cr["Sender_account"].nunique()),
        "distinct_receivers": int(db["Receiver_account"].nunique()),
        "largest_credit": _money(cr["Amount"].max()) if len(cr) else None,
        "largest_debit": _money(db["Amount"].max()) if len(db) else None,
        "first_date": str(df["Date"].min()) if len(df) else None,
        "last_date": str(df["Date"].max()) if len(df) else None,
        "by_payment_type": by_type,
        "counterparty_locations": locations,
        "watchlist_counterparty_count": len(wl),
        "watchlist_counterparty_total": _money(wl["amount"].sum()),
        "non_gbp_currency_transactions": len(non_gbp),
    }


def build_evidence(alert, profile: dict, txns: pd.DataFrame, alerts: pd.DataFrame,
                   watchlist, lookback_days: int) -> dict:
    account_id = int(alert["account_id"])
    trigger = pd.Timestamp(alert["trigger_date"]).date()
    window_start = pd.Timestamp(alert["window_start"]).date()
    requested_start = trigger - timedelta(days=lookback_days - 1)
    start = max(requested_start, DATASET_START)
    own = txns[(txns["Sender_account"] == account_id) | (txns["Receiver_account"] == account_id)]
    period = own[(own["Date"] >= start) & (own["Date"] <= trigger)]
    window = period[period["Date"] >= window_start]

    blocks = []
    end = trigger
    while end >= start:
        b_start = max(end - timedelta(days=29), start)
        b = period[(period["Date"] >= b_start) & (period["Date"] <= end) & (period["Receiver_account"] == account_id)]
        blocks.append({"start": str(b_start), "end": str(end), "days": (end - b_start).days + 1,
                       "credits_count": len(b), "credits_total": _money(b["Amount"].sum())})
        end = b_start - timedelta(days=1)

    is_credit = period["Receiver_account"] == account_id
    cps = pd.DataFrame({
        "counterparty": period["Sender_account"].where(is_credit, period["Receiver_account"]),
        "direction": is_credit.map({True: "credit", False: "debit"}),
        "location": period["Sender_bank_location"].where(is_credit, period["Receiver_bank_location"]),
        "amount": period["Amount"],
    })
    top = (cps.groupby(["counterparty", "direction", "location"], as_index=False)
              .agg(count=("amount", "size"), total=("amount", "sum"))
              .sort_values(["total", "counterparty"], ascending=[False, True]).head(TOP_COUNTERPARTIES))

    # Only alerts known at the case date: later-dated alerts would be look-ahead information.
    others = alerts[(alerts["account_id"] == account_id) & (alerts["alert_id"] != alert["alert_id"])
                    & (pd.to_datetime(alerts["trigger_date"]).dt.date <= trigger)]
    others = others.sort_values("alert_id")
    return {
        "amount_unit": "dataset monetary units (GBP assumed, unverified)",
        "alert": {
            "window_start": str(window_start), "trigger_date": str(trigger),
            "trigger_value": round(float(alert["trigger_value"]), 4),
            "trigger_detail": alert["trigger_detail"],
        },
        "customer_profile": {k: (str(v) if k == "account_open_date" else v.item() if hasattr(v, "item") else v)
                             for k, v in profile.items()},
        "review_period": {
            "start": str(start), "end": str(trigger), "days": (trigger - start).days + 1,
            "requested_lookback_days": lookback_days,
            "truncated_by_dataset_start": requested_start < DATASET_START,
        },
        "lookback_activity": summarise(period, account_id, watchlist),
        "alert_window_activity": summarise(window, account_id, watchlist),
        "credits_by_30_day_block": blocks,
        "top_counterparties_by_value": [
            {"counterparty": int(r.counterparty), "direction": r.direction, "location": r.location,
             "count": int(r.count), "total": _money(r.total)} for r in top.itertuples()
        ],
        "watchlist_reference": "FATF increased monitoring, 23 June 2023 snapshot (simulation watchlist): "
                               + ", ".join(watchlist),
        "other_alerts_on_account": [
            {"alert_id": r.alert_id, "scenario": r.scenario, "trigger_date": str(r.trigger_date)}
            for r in others.itertuples()
        ],
    }


def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"


def customer_summary(p: dict) -> str:
    return (f"{p['segment']}, {p['occupation_or_sector']}, declared income/turnover "
            f"{p['declared_income_or_turnover_band']}, expected monthly credits "
            f"{p['expected_monthly_credits_min_gbp']:,}-{p['expected_monthly_credits_max_gbp']:,}, "
            f"account opened {p['account_open_date']}, risk rating {p['customer_risk_rating']}. "
            f"KYC flags on file: PEP {_yes_no(p['pep_flag'])}, adverse media {_yes_no(p['adverse_media_flag'])}.")


def activity_reviewed(ev: dict) -> str:
    rp, la, aw = ev["review_period"], ev["lookback_activity"], ev["alert_window_activity"]
    abroad = {k: v for k, v in la["counterparty_locations"].items() if k != "UK"}
    abroad_txt = ", ".join(f"{k} {v['count']} txns / {v['total']:,.2f}" for k, v in abroad.items()) or "none"
    trunc = " (lookback cut short by the dataset start)" if rp["truncated_by_dataset_start"] else ""
    return (
        f"{rp['days']}-day lookback {rp['start']} to {rp['end']}{trunc}: "
        f"{la['credits_count']} credits totalling {la['credits_total']:,.2f} from {la['distinct_senders']} distinct senders; "
        f"{la['debits_count']} debits totalling {la['debits_total']:,.2f} to {la['distinct_receivers']} distinct receivers. "
        f"Non-UK counterparty locations: {abroad_txt}. "
        f"Alert window {ev['alert']['window_start']} to {ev['alert']['trigger_date']}: "
        f"{aw['credits_count']} credits ({aw['credits_total']:,.2f}), {aw['debits_count']} debits ({aw['debits_total']:,.2f}). "
        f"Trigger: {ev['alert']['trigger_detail']}."
    )


def build_cases() -> list[dict]:
    cfg = load_config()
    sample, alerts, profiles, txns = load_inputs()
    locations = set(txns["Sender_bank_location"]) | set(txns["Receiver_bank_location"])
    watchlist, _ = load_watchlist(locations)
    profiles = profiles.set_index("account_id")
    cases = []
    for i, alert in enumerate(sample.sort_values("alert_id").to_dict("records")):
        profile = profiles.loc[alert["account_id"]].to_dict()
        ev = build_evidence(alert, profile, txns, alerts, watchlist, cfg["history_lookback_days"])
        case = {
            "case_id": f"CASE-{i + 1:03d}",
            "alert_id": alert["alert_id"],
            "scenario": f"{alert['scenario']} {alert['scenario_name']}",
            "investigator": INVESTIGATORS[i % len(INVESTIGATORS)],
            "account_id": int(alert["account_id"]),
            "alert_date": str(alert["trigger_date"]),
            "customer_summary": customer_summary(ev["customer_profile"]),
            "activity_reviewed": activity_reviewed(ev),
            "evidence": ev,
        }
        case.update({f: None for f in JUDGEMENT_FIELDS + DISCLOSURE_FIELDS})
        cases.append({k: case[k] for k in CASE_FIELDS})
    return cases


def is_completed(path: Path) -> bool:
    """True if any investigator field in an existing case file has been filled in."""
    case = yaml.safe_load(path.read_text(encoding="utf-8"))
    return any(case.get(f) is not None for f in JUDGEMENT_FIELDS + DISCLOSURE_FIELDS)


def main(force: bool = False) -> None:
    CASES_DIR.mkdir(exist_ok=True)
    for case in build_cases():
        path = CASES_DIR / f"{case['case_id']}.yaml"
        if path.exists() and (not force or is_completed(path)):
            print(f"skip {path.name} (exists{', has investigator content' if force else ''})")
            continue
        body = yaml.safe_dump(case, sort_keys=False, allow_unicode=True, width=100)
        path.write_text(HEADER + body, encoding="utf-8")
        print(f"wrote {path.name}")


if __name__ == "__main__":
    main(force="--force" in sys.argv[1:])
