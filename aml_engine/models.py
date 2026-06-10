"""Core data model: customers, accounts, transactions, rule hits, alerts.

Money is always ``decimal.Decimal``. Amounts must never pass through float
(including CSV round-trips) — binary floating point cannot represent values
like 9999.99 exactly, and threshold rules such as the $10,000 CTR boundary
depend on exact comparisons.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path


class TxnType(StrEnum):
    CASH_DEPOSIT = "CASH_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    WIRE_IN = "WIRE_IN"
    WIRE_OUT = "WIRE_OUT"
    ACH = "ACH"
    CHECK = "CHECK"


#: Transaction types that count as "cash in" for CTR aggregation purposes
#: (31 CFR 1010.313 aggregates currency transactions, not monetary
#: instruments or electronic transfers).
CASH_IN_TYPES = frozenset({TxnType.CASH_DEPOSIT})

#: Transaction types relevant to cross-border jurisdiction screening.
WIRE_TYPES = frozenset({TxnType.WIRE_IN, TxnType.WIRE_OUT})


class Channel(StrEnum):
    BRANCH = "BRANCH"
    ATM = "ATM"
    ONLINE = "ONLINE"
    MOBILE = "MOBILE"


class EntityType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    LLC = "LLC"
    CORP = "CORP"
    TRUST = "TRUST"
    PARTNERSHIP = "PARTNERSHIP"
    MSB = "MSB"


#: Entity types that are legal entities subject to beneficial-ownership
#: collection under the CDD Rule (31 CFR 1010.230).
BUSINESS_ENTITY_TYPES = frozenset(
    {EntityType.LLC, EntityType.CORP, EntityType.TRUST, EntityType.PARTNERSHIP, EntityType.MSB}
)


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


#: Ordering helper: higher value = more severe.
SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


@dataclass(slots=True)
class BeneficialOwner:
    """A natural person (or nominee) on an entity's ownership record."""

    owner_name: str
    ownership_pct: float
    is_nominee: bool = False
    country: str = "US"


@dataclass(slots=True)
class Customer:
    customer_id: str
    name: str
    entity_type: EntityType
    country: str  # ISO 3166-1 alpha-2 country of residence / operations
    onboarding_date: date
    # Business-entity fields; None / empty for individuals.
    registration_country: str | None = None
    formation_date: date | None = None
    ownership_chain_depth: int = 0  # layers between entity and natural persons
    beneficial_owners: list[BeneficialOwner] = field(default_factory=list)
    has_physical_address: bool = True
    industry_code: str | None = None

    @property
    def is_business(self) -> bool:
        return self.entity_type in BUSINESS_ENTITY_TYPES


@dataclass(slots=True)
class Account:
    account_id: str
    customer_id: str
    opened_date: date
    account_type: str = "checking"  # "checking" | "business"


@dataclass(slots=True)
class Transaction:
    txn_id: str
    timestamp: datetime
    account_id: str
    customer_id: str
    txn_type: TxnType
    channel: Channel
    amount: Decimal
    currency: str = "USD"
    counterparty_name: str = ""
    # Set when the counterparty is another account at this institution —
    # this is what lets the smurfing rule link originators to a funnel.
    counterparty_account_id: str | None = None
    originator_country: str = "US"
    beneficiary_country: str = "US"
    memo: str = ""


@dataclass(slots=True)
class GroundTruth:
    """Label for one planted suspicious scenario.

    Produced only by the data generator and consumed only by the evaluation
    report and the test suite. Detection rules never see this structure —
    that separation is what makes recall/false-positive numbers honest.
    """

    scenario_id: str
    pattern_name: str
    customer_ids: list[str]
    txn_ids: list[str]
    expected_rule_ids: list[str]


@dataclass(slots=True)
class RuleHit:
    """One firing of one rule, before scoring."""

    rule_id: str
    rule_name: str
    citation: str
    severity: Severity
    base_score: int
    txn_ids: list[str]
    customer_id: str
    account_id: str | None
    narrative: str  # investigator-style explanation of what was observed


# Alert carries the same fields as RuleHit plus final scoring output.
# Fields are repeated rather than inherited because slotted dataclass
# inheritance complicates field ordering for no practical gain here.
@dataclass(slots=True)
class Alert:
    rule_id: str
    rule_name: str
    citation: str
    severity: Severity
    base_score: int
    txn_ids: list[str]
    customer_id: str
    account_id: str | None
    narrative: str
    final_score: int
    tier: Severity

    @classmethod
    def from_hit(cls, hit: RuleHit, final_score: int, tier: Severity) -> "Alert":
        return cls(
            rule_id=hit.rule_id,
            rule_name=hit.rule_name,
            citation=hit.citation,
            severity=hit.severity,
            base_score=hit.base_score,
            txn_ids=list(hit.txn_ids),
            customer_id=hit.customer_id,
            account_id=hit.account_id,
            narrative=hit.narrative,
            final_score=final_score,
            tier=tier,
        )


_TXN_CSV_FIELDS = [
    "txn_id",
    "timestamp",
    "account_id",
    "customer_id",
    "txn_type",
    "channel",
    "amount",
    "currency",
    "counterparty_name",
    "counterparty_account_id",
    "originator_country",
    "beneficiary_country",
    "memo",
]


@dataclass(slots=True)
class Dataset:
    customers: list[Customer]
    accounts: list[Account]
    transactions: list[Transaction]
    ground_truth: list[GroundTruth] = field(default_factory=list)

    def write_transactions_csv(self, path: Path) -> None:
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_TXN_CSV_FIELDS)
            writer.writeheader()
            for t in self.transactions:
                writer.writerow(
                    {
                        "txn_id": t.txn_id,
                        "timestamp": t.timestamp.isoformat(),
                        "account_id": t.account_id,
                        "customer_id": t.customer_id,
                        "txn_type": t.txn_type.value,
                        "channel": t.channel.value,
                        # str(Decimal) is exact; never cast through float.
                        "amount": str(t.amount),
                        "currency": t.currency,
                        "counterparty_name": t.counterparty_name,
                        "counterparty_account_id": t.counterparty_account_id or "",
                        "originator_country": t.originator_country,
                        "beneficiary_country": t.beneficiary_country,
                        "memo": t.memo,
                    }
                )


def read_transactions_csv(path: Path) -> list[Transaction]:
    transactions: list[Transaction] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            transactions.append(
                Transaction(
                    txn_id=row["txn_id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    account_id=row["account_id"],
                    customer_id=row["customer_id"],
                    txn_type=TxnType(row["txn_type"]),
                    channel=Channel(row["channel"]),
                    amount=Decimal(row["amount"]),
                    currency=row["currency"],
                    counterparty_name=row["counterparty_name"],
                    counterparty_account_id=row["counterparty_account_id"] or None,
                    originator_country=row["originator_country"],
                    beneficiary_country=row["beneficiary_country"],
                    memo=row["memo"],
                )
            )
    return transactions
