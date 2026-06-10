"""Detection orchestrator: dataset in, scored alerts out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aml_engine.models import Account, Alert, Customer, Transaction
from aml_engine.rules import Rule, RuleContext, build_registry
from aml_engine.scoring import CustomerRisk, score_alerts, score_customers


@dataclass(slots=True)
class DetectionResult:
    alerts: list[Alert]
    customer_risks: list[CustomerRisk]


def run_detection(
    transactions: list[Transaction],
    accounts: list[Account],
    customers: list[Customer],
    rules: list[Rule] | None = None,
) -> DetectionResult:
    """Evaluate the rule catalog and score the results.

    Note the signature: detection sees only transactions, accounts,
    customers, and (via the rules) reference data. Ground-truth scenario
    labels are deliberately not accepted here.
    """
    ctx = RuleContext(transactions=transactions, accounts=accounts, customers=customers)
    hits = []
    for rule in rules if rules is not None else build_registry():
        hits.extend(rule.evaluate(ctx))

    alerts = score_alerts(hits)
    as_of = (
        max(t.timestamp.date() for t in transactions) if transactions else date.today()
    )
    customer_risks = score_customers(alerts, customers, transactions, as_of)
    return DetectionResult(alerts=alerts, customer_risks=customer_risks)
