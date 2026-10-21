# EDA Notes: SAML-D (Phase 0)

Profiled with DuckDB 1.5.6 directly over `data/raw/SAML-D.csv` (~950 MB, not committed).
Profiling date: 2026-10-21.

## 1. Shape

| Metric | Value |
|---|---|
| Rows | 9,504,852 |
| Laundering rows (`Is_laundering = 1`) | 9,873 (0.104%) |
| Date range | 2022-10-07 to 2023-08-23 (~10.5 months; Oct and Aug are partial) |
| Distinct sender accounts | 292,715 |
| Distinct receiver accounts | 652,266 |
| Nulls | 0 in every column |
| Exact duplicate rows | 0 |

Matches the plan's expectations (~9.5M rows, ~0.1% laundering).

## 2. Columns (confirmed)

All 12 expected columns are present, in this order, with these inferred types:

| Column | Type | Note |
|---|---|---|
| `Time` | TIME | |
| `Date` | DATE | |
| `Sender_account` | BIGINT | |
| `Receiver_account` | BIGINT | |
| `Amount` | DOUBLE | Currency of `Amount` not documented (see open questions) |
| `Payment_currency` | VARCHAR | 13 values |
| `Received_currency` | VARCHAR | 13 values |
| `Sender_bank_location` | VARCHAR | 18 values |
| `Receiver_bank_location` | VARCHAR | 18 values |
| `Payment_type` | VARCHAR | 7 values |
| `Is_laundering` | BIGINT | 0 / 1 |
| `Laundering_type` | VARCHAR | 28 values |

## 3. `Payment_type` (7 values)

| Payment_type | Rows | Laundering rows |
|---|---:|---:|
| Credit card | 2,012,909 | 1,136 |
| Debit card | 2,012,103 | 1,124 |
| Cheque | 2,011,419 | 1,087 |
| ACH | 2,008,807 | 1,159 |
| Cross-border | 933,931 | 2,628 |
| Cash Withdrawal | 300,477 | 1,334 |
| Cash Deposit | 225,206 | 1,405 |

Note: UK domestic data, but uses the US term `ACH` (no Faster Payments / BACS / CHAPS split).

## 4. `Laundering_type` (28 values: 11 normal, 17 suspicious)

Each typology maps to exactly one `Is_laundering` value, so the typology label fully determines the flag.

**Normal (`Is_laundering = 0`)**

| Laundering_type | Rows |
|---|---:|
| Normal_Small_Fan_Out | 3,477,717 |
| Normal_Fan_Out | 2,302,220 |
| Normal_Fan_In | 2,104,285 |
| Normal_Group | 528,351 |
| Normal_Cash_Withdrawal | 305,031 |
| Normal_Cash_Deposits | 223,801 |
| Normal_Periodical | 210,526 |
| Normal_Plus_Mutual | 155,041 |
| Normal_Mutual | 125,335 |
| Normal_Foward | 42,031 |
| Normal_single_large | 20,641 |

`Normal_Foward` is misspelled in the source data. Keep the literal value in any SQL filter.

**Suspicious (`Is_laundering = 1`)**

| Laundering_type | Rows |
|---|---:|
| Structuring | 1,870 |
| Cash_Withdrawal | 1,334 |
| Deposit-Send | 945 |
| Smurfing | 932 |
| Layered_Fan_In | 656 |
| Layered_Fan_Out | 529 |
| Stacked Bipartite | 506 |
| Behavioural_Change_1 | 394 |
| Bipartite | 383 |
| Cycle | 382 |
| Fan_In | 364 |
| Gather-Scatter | 354 |
| Behavioural_Change_2 | 345 |
| Scatter-Gather | 338 |
| Single_large | 250 |
| Fan_Out | 237 |
| Over-Invoicing | 54 |

Naming is inconsistent (underscore, hyphen and space separators; mixed case). Match on exact strings.

## 5. Bank locations (18 values, same set for sender and receiver)

UK, Albania, Austria, France, Germany, India, Italy, Japan, Mexico, Morocco, Netherlands, Nigeria, Pakistan, Spain, Switzerland, Turkey, UAE, USA.

| Location | Sender rows | Sender laundering | Receiver rows | Receiver laundering |
|---|---:|---:|---:|---:|
| UK | 9,183,088 | 9,253 | 8,864,634 | 7,308 |
| Turkey | 20,902 | 27 | 35,586 | 177 |
| Switzerland | 20,503 | 41 | 36,081 | 77 |
| Pakistan | 20,346 | 25 | 38,980 | 169 |
| UAE | 20,081 | 34 | 35,897 | 195 |
| Nigeria | 20,027 | 25 | 38,272 | 251 |
| Spain | 19,391 | 27 | 37,288 | 87 |
| Germany | 19,259 | 43 | 38,540 | 102 |
| USA | 19,027 | 36 | 36,850 | 87 |
| Italy | 18,895 | 45 | 36,517 | 131 |
| France | 18,702 | 31 | 38,512 | 82 |
| Japan | 18,468 | 38 | 38,729 | 83 |
| Morocco | 18,437 | 55 | 38,704 | 253 |
| Austria | 18,050 | 38 | 38,844 | 154 |
| Mexico | 17,662 | 44 | 38,385 | 197 |
| Albania | 17,648 | 28 | 38,783 | 235 |
| India | 17,596 | 42 | 36,936 | 137 |
| Netherlands | 16,770 | 41 | 37,314 | 148 |

- UK is ~97% of sender rows and ~93% of receiver rows. Outbound (UK to foreign) is roughly 2x inbound.
- There is **no high-risk flag column**. The high-risk list for TM03 has to be defined in `config/high_risk_jurisdictions.yaml`. Receiver-side laundering rows are highest for Morocco, Nigeria, Albania, Mexico, UAE, Turkey and Pakistan.

## 6. Currencies (13 values)

UK pounds, Euro, Turkish lira, Swiss franc, Dirham, Pakistani rupee, Naira, US dollar, Yen, Moroccan dirham, Mexican Peso, Albanian lek, Indian rupee.

~84k rows have a UK sender but non-GBP `Payment_currency` (and ~82k the receiver-side equivalent), so currency and location are not strictly tied.

## 7. Amount distribution

| Is_laundering | Min | P25 | Median | P75 | P99 | Max | Mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | 3.73 | 2,142.93 | 6,114.63 | 10,458.95 | 44,938.16 | 999,962.19 | 8,729.88 |
| 1 | 15.82 | 2,723.79 | 5,322.79 | 9,789.67 | 419,540.08 | 12,618,498.40 | 40,587.67 |

Laundering medians are similar to normal ones. The difference is in the tail (P99 ~9x higher), driven by large-value typologies.

## 8. Consistency checks

- **Cross-border vs locations:** every `Cross-border` row has different sender and receiver locations. 417 extra rows have different locations but a non-cross-border type: 412 `Cash Withdrawal`, 5 `Cash Deposit`. Treat location, not `Payment_type`, as the source of truth for TM03.
- **Monthly volume** is flat (~0.9M per month, ~900 laundering rows per month) apart from the partial first and last months.

## 9. Findings that affect Phase 2 (scenario design)

1. **TM01 Structuring as drafted won't behave realistically.**
   - The `Structuring` typology has **no cash rows**. It is ACH, Cheque, card and Cross-border, with amounts from £2.1k to £12.5k (median ~£5k).
   - Cash-deposit laundering is labelled `Smurfing` (932 rows) and `Deposit-Send` (473 cash-deposit rows).
   - **No normal cash deposit is ≥ £7,500.** All 57 cash deposits in the £7,500–£9,999 band, and all 149 that are ≥ £10k, are laundering. A cash £7.5k–£9.999k rule would therefore have 0 false positives. That defeats the QA exercise, which needs a mix of true and false positives.
   - Options: lower the band, widen it to non-cash payment types, or accept the rule and get false positives from other scenarios. **Decision needed before Phase 2.**
2. **TM03:** define high-risk jurisdictions in YAML. Use bank location, not `Payment_type`.
3. **TM06 Behavioural change:** maps to `Behavioural_Change_1/2`. `Behavioural_Change_2` is 100% Cross-border.
4. **TM04/TM05 Fan-in/out:** normal fan typologies are very large (millions of rows), so expect many false positives. That is useful for QA sampling.

## 10. Open questions

- **Currency of `Amount`:** is it GBP-equivalent or in `Payment_currency`? The SAML-D paper should confirm this. It matters for the £ thresholds in non-GBP rows (~4% of the data).
- **High-risk jurisdiction list:** pick a basis (e.g. FATF grey/black list or UK MLR 2017 Sch. 3ZA high-risk third countries as of a stated date) and cite it.
