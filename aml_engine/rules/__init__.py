"""Rule framework: base class, shared evaluation context, and registry.

Each detection rule is a small, documented class with a regulatory citation.
Rules receive a :class:`RuleContext` that exposes the dataset through
precomputed indexes (transactions sorted by time, grouped by account /
customer / counterparty) so individual rules stay simple and roughly O(n).

Rules never see ground-truth labels — only transactions, accounts,
customers, and reference data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field

from aml_engine.models import Account, Customer, RuleHit, Severity, Transaction


@dataclass
class RuleContext:
    """Read-only view of the dataset with shared indexes for rules."""

    transactions: list[Transaction]
    accounts: list[Account]
    customers: list[Customer]

    txns_sorted: list[Transaction] = field(init=False)
    by_account: dict[str, list[Transaction]] = field(init=False)
    by_customer: dict[str, list[Transaction]] = field(init=False)
    # Inbound transfers grouped by the *receiving* internal account
    # (counterparty_account_id on the sender's transaction).
    inbound_by_counterparty: dict[str, list[Transaction]] = field(init=False)
    account_by_id: dict[str, Account] = field(init=False)
    customer_by_id: dict[str, Customer] = field(init=False)

    def __post_init__(self) -> None:
        self.txns_sorted = sorted(self.transactions, key=lambda t: (t.timestamp, t.txn_id))
        self.by_account = defaultdict(list)
        self.by_customer = defaultdict(list)
        self.inbound_by_counterparty = defaultdict(list)
        for txn in self.txns_sorted:
            self.by_account[txn.account_id].append(txn)
            self.by_customer[txn.customer_id].append(txn)
            if txn.counterparty_account_id:
                self.inbound_by_counterparty[txn.counterparty_account_id].append(txn)
        self.account_by_id = {a.account_id: a for a in self.accounts}
        self.customer_by_id = {c.customer_id: c for c in self.customers}


class Rule(ABC):
    """Base class for all detection rules.

    Subclasses set the class attributes below and implement
    :meth:`evaluate`. ``citation`` is the regulatory basis and is rendered
    verbatim in reports and alert exports.
    """

    rule_id: str
    name: str
    citation: str
    severity: Severity
    base_score: int
    description: str

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        """Return one RuleHit per detected pattern instance."""

    def make_hit(
        self,
        *,
        txn_ids: list[str],
        customer_id: str,
        narrative: str,
        account_id: str | None = None,
        severity: Severity | None = None,
        base_score: int | None = None,
    ) -> RuleHit:
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.name,
            citation=self.citation,
            severity=severity or self.severity,
            base_score=base_score if base_score is not None else self.base_score,
            txn_ids=txn_ids,
            customer_id=customer_id,
            account_id=account_id,
            narrative=narrative,
        )


def build_registry() -> list[Rule]:
    """Instantiate the full rule catalog in evaluation order."""
    # Imported here to avoid circular imports at module load.
    from aml_engine.rules.beneficial_ownership import (
        NoIdentifiableBeneficialOwnerRule,
        NomineeOwnerRule,
        RoundDollarPassThroughRule,
        SecrecyHavenShellRule,
    )
    from aml_engine.rules.jurisdiction import (
        FatfBlacklistRule,
        FatfGreylistCorridorRule,
        OfacJurisdictionRule,
    )
    from aml_engine.rules.structuring import (
        SameDayAggregationRule,
        SmurfingFunnelRule,
        SubThresholdCashPatternRule,
    )

    return [
        SubThresholdCashPatternRule(),
        SameDayAggregationRule(),
        SmurfingFunnelRule(),
        OfacJurisdictionRule(),
        FatfBlacklistRule(),
        FatfGreylistCorridorRule(),
        NoIdentifiableBeneficialOwnerRule(),
        NomineeOwnerRule(),
        SecrecyHavenShellRule(),
        RoundDollarPassThroughRule(),
    ]
