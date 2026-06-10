# AML Transaction Flagging Engine

A rules-based anti-money-laundering (AML) transaction monitoring engine in pure Python. It generates a synthetic retail-banking dataset with planted suspicious patterns, runs a catalog of ten detection rules modeled on **BSA/FinCEN regulations, OFAC sanctions programs, and FATF guidance**, scores the results, and produces a SAR-candidate worklist the way a transaction-monitoring system feeds an investigator's queue.

```
git clone https://github.com/medhanies/aml-transaction-flagging-engine.git
cd aml-transaction-flagging-engine
python -m aml_engine run --seed 42
```

No dependencies. Python 3.11+ and the standard library only.

> **Disclaimer** — This is an educational/portfolio project. All data is synthetic. The jurisdiction lists are point-in-time snapshots (as of the February 2025 FATF plenary) and the FATF greylist in particular changes three times a year. Nothing here is a compliance tool; verify everything against primary sources ([OFAC](https://ofac.treasury.gov/sanctions-programs-and-country-information), [FATF](https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html), [FinCEN](https://www.fincen.gov)) before any real-world use.

## Why these rules

The engine implements three detection families that map to core AML investigator work:

**Structuring (31 U.S.C. § 5324).** Banks must file a Currency Transaction Report for currency transactions of more than $10,000 (31 CFR 1010.311), aggregating same-business-day cash activity by or on behalf of the same person (31 CFR 1010.313). Breaking cash into sub-threshold amounts to evade that reporting is a federal crime even when the money is clean. The engine detects the three classic presentations: repeated just-under-threshold deposits, same-owner aggregation across accounts, and third-party "smurfing" into a funnel account (FinCEN Advisory FIN-2014-A005).

**High-risk jurisdictions.** Three regimes are deliberately modeled with different severities, because they carry different obligations:

- *OFAC comprehensive programs* (Iran, North Korea, Cuba, Syria, plus embargoed Ukrainian regions) — in production these are **interdicted at payment screening and blocked/rejected**, not merely alerted. The engine flags them CRITICAL.
- *Russia/Belarus* — sanctioned under broad **sectoral and list-based** programs (E.O. 14024/14038), not a comprehensive country embargo. Treating "Russia" like "Iran" is a common modeling error; here it routes to a lower-severity sanctions-screening referral.
- *FATF lists* — the "Call for Action" blacklist (Iran, DPRK, Myanmar) flags per-transaction; the "Increased Monitoring" greylist only flags a **pattern** of corridor activity, because a single wire touching a greylist country is ordinary international banking.

**Beneficial ownership.** The FinCEN CDD Rule (31 CFR 1010.230) requires identifying each natural person owning **25% or more** of a legal-entity customer; the Corporate Transparency Act (31 U.S.C. § 5336) extends beneficial-ownership reporting to FinCEN. The engine implements the shell-company typologies from FATF Recommendation 24 and the FATF/Egmont *Concealment of Beneficial Ownership* study (2018): no identifiable 25% owner, opaque ownership chains, nominee owners, secrecy-haven registration with domestic-only activity, and round-dollar pass-through (conduit) behavior.

## Rule catalog

| ID | Name | Regulatory basis | Severity | Base |
|----|------|------------------|----------|------|
| R-STRUCT-001 | Sub-threshold cash deposit pattern | 31 CFR 1010.311; 31 U.S.C. 5324(a)(3) | HIGH | 70 |
| R-STRUCT-002 | Same-day multi-account aggregation under CTR | 31 CFR 1010.313(b); 31 U.S.C. 5324 | HIGH | 70 |
| R-STRUCT-003 | Smurfing / funnel account | 31 U.S.C. 5324; FinCEN FIN-2014-A005 | HIGH | 75 |
| R-JURIS-001 | OFAC sanctioned-jurisdiction exposure | 31 CFR Parts 560/510/515/542; E.O. 13685/14065; IEEPA | CRITICAL (HIGH for RU/BY) | 95 / 65 |
| R-JURIS-002 | FATF blacklist counterparty | FATF Call for Action; 31 U.S.C. 5318A | HIGH | 80 |
| R-JURIS-003 | FATF greylist corridor activity | FATF Increased Monitoring; FFIEC Manual | MEDIUM | 45 |
| R-BO-001 | No identifiable 25% beneficial owner / opaque chain | 31 CFR 1010.230; 31 U.S.C. 5336 (CTA) | MEDIUM | 50 (+10) |
| R-BO-002 | Nominee directors/shareholders | FATF Rec 24; FATF/Egmont (2018); CDD control prong | MEDIUM | 55 |
| R-BO-003 | Secrecy-haven registration, domestic-only activity | FinCEN shell-company guidance (2006); FATF Rec 24 | HIGH | 60 |
| R-BO-004 | Round-dollar pass-through activity | FFIEC Manual funds-transfer red flags; FATF Rec 24 | HIGH | 65 |

Print the full catalog with parameters: `python -m aml_engine rules`

## Architecture

```
generator.py ──> engine.py ──────> scoring.py ──> report.py
 seeded synthetic    rules/            alert scores      console report
 data + planted      R-STRUCT-001..3   customer scores   alerts.json
 scenarios           R-JURIS-001..3    severity tiers    flagged_transactions.csv
 (ground truth       R-BO-001..4       SAR worklist      sar_worklist.csv
  kept separate)
```

Design choices worth noting:

- **Ground truth is isolated from detection.** Rules see only transactions, accounts, customers, and reference data. The labels for planted scenarios live in a separate structure consumed only by the evaluation report and the tests — so the recall and false-positive numbers can't cheat.
- **`Decimal` end-to-end for money.** Threshold logic like "exactly $10,000.00 is *not* structuring" (the CTR applies to transactions of *more than* $10,000) depends on exact arithmetic; amounts never pass through float, including the CSV round-trip.
- **Each rule is a small documented class** with its citation rendered into every alert and export, and shared indexing is precomputed once so rules stay simple and roughly O(n).
- **Scoring is dominant-rule-plus-corroboration**, not summation: an alert's score is its rule's base score plus a small bump per additional distinct rule firing on the same customer, so four medium-severity hits can never outrank one OFAC hit. A customer's score starts at their worst alert and adds breadth and static risk factors (greylist home country, high-risk industry, new relationship).

## Sample output

```
==============================================================================
AML TRANSACTION FLAGGING ENGINE — DETECTION REPORT
==============================================================================
Dataset: 215 customers, 215 accounts, 5135 transactions (2024-12-31 to 2025-03-31)

ALERTS BY RULE (16 alerts at LOW+)
------------------------------------------------------------------------------
R-STRUCT-001  Sub-threshold cash deposit pattern  [3 alert(s)]
          31 CFR 1010.311 (CTR threshold); 31 U.S.C. 5324(a)(3) (structuring)
R-STRUCT-003  Smurfing / funnel account  [1 alert(s)]
          31 U.S.C. 5324; FinCEN Advisory FIN-2014-A005 (funnel accounts)
...

SAR-CANDIDATE WORKLIST (top 9 of 9 HIGH+ customers)
------------------------------------------------------------------------------
SCORE  TIER      CUSTOMER                          RULES                       FLAGGED
  100  CRITICAL  Maverick Global Holdings LLC (C0  R-BO-001, R-BO-002, R-B  $324,000.00
   95  CRITICAL  Priya Okafor (C000210)            R-JURIS-001               $21,879.22
   75  HIGH      Linda Hernandez (C000204)         R-STRUCT-003              $30,215.54
   70  HIGH      Elena Smith (C000201)             R-STRUCT-001              $52,633.36
...

VALIDATION AGAINST PLANTED SCENARIOS
------------------------------------------------------------------------------
[DETECTED] S000001 structuring          R-STRUCT-001:Y
[DETECTED] S000004 smurfing             R-STRUCT-003:Y
[DETECTED] S000005 ofac_wire            R-JURIS-001:Y
[DETECTED] S000009 shell_passthrough    R-BO-001:Y, R-BO-002:Y, R-BO-003:Y, R-BO-004:Y
...
Scenario recall: 10/10 (100%)
Transactions flagged outside planted scenarios: 0
```

## Usage

```bash
# Full pipeline: generate → detect → score → report (+ exports)
python -m aml_engine run --seed 42 --out output/

# Tune the population or observation window
python -m aml_engine run --seed 7 --customers 500 --days 180

# Only show CRITICAL alerts; hide the validation section
python -m aml_engine run --min-severity critical --no-eval

# Generate raw transactions to CSV, then detect from file
python -m aml_engine generate --seed 42 --out output/transactions.csv
python -m aml_engine detect --input output/transactions.csv --out output/

# Print the rule catalog with citations
python -m aml_engine rules
```

The same seed always produces byte-identical data and results.

### Exports (`--out`)

| File | Contents |
|------|----------|
| `alerts.json` | Every alert with rule ID, citation, severity, base/final score, tier, transaction IDs, and an investigator-style narrative |
| `flagged_transactions.csv` | One row per flagged transaction with the rules that hit it |
| `sar_worklist.csv` | HIGH+ customers ranked by score, with rules fired, flagged dollar volume, activity dates, and concatenated narratives |

## Testing

```bash
pip install pytest
python -m pytest
```

71 tests cover each rule against hand-built fixtures (firing on planted patterns, staying silent on clean data, and boundary cases — e.g., a deposit of exactly $10,000.00 must **not** flag as structuring, while $9,999.99 must; an exactly-25.0% owner satisfies the CDD prong), generator reproducibility, the false-positive guard (a fully benign population must produce zero HIGH/CRITICAL alerts), scoring properties, and the CLI end-to-end.

## What I'd add next

- Sanctions **name screening** with fuzzy matching against an SDN-style list (the current rules screen jurisdictions, not parties)
- Velocity and rapid-movement rules (turnover ratio, dormant-account reactivation)
- SQLite persistence and alert disposition workflow (open → investigating → SAR filed / closed) to mirror case management
- Configurable rule parameters via a YAML/TOML policy file, as production systems tune thresholds per risk appetite
