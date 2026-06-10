"""Risk scoring: per-alert transaction scores and per-customer aggregates.

Methodology — dominant rule plus corroboration:

- A transaction-level alert score starts from the strongest rule that fired
  on any of its transactions and adds a small bump per additional distinct
  rule. This avoids naive summation, where four medium-severity hits would
  outrank a single OFAC hit.
- A customer's score starts at their worst alert (a customer is never less
  risky than their most serious alert) and adds breadth (additional
  distinct rules fired) and static entity risk factors, capped at 100.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from aml_engine.models import Alert, Customer, RuleHit, Severity, Transaction
from aml_engine.reference_data import FATF_GREYLIST, HIGH_RISK_INDUSTRIES

# --- Alert (transaction-level) scoring -------------------------------------

#: Bump added per additional distinct rule corroborating the same customer.
CORROBORATION_BUMP = 10

# --- Customer-level scoring -------------------------------------------------

#: Points per distinct rule beyond the first that fired for the customer.
BREADTH_POINTS = 8
#: Static risk factors (each adds points; capped by MAX_STATIC_RISK).
STATIC_GREYLIST_HOME = 5
STATIC_HIGH_RISK_INDUSTRY = 5
STATIC_NEW_RELATIONSHIP = 5
NEW_RELATIONSHIP_DAYS = 90
MAX_STATIC_RISK = 15

# --- Severity tiers ----------------------------------------------------------

TIER_CRITICAL = 85
TIER_HIGH = 65
TIER_MEDIUM = 40


def tier_for_score(score: int) -> Severity:
    if score >= TIER_CRITICAL:
        return Severity.CRITICAL
    if score >= TIER_HIGH:
        return Severity.HIGH
    if score >= TIER_MEDIUM:
        return Severity.MEDIUM
    return Severity.LOW


def score_alerts(hits: list[RuleHit]) -> list[Alert]:
    """Convert rule hits to scored alerts.

    Each alert's final score = its own base score + a corroboration bump for
    every *other* distinct rule that also fired on the same customer,
    capped at 100.
    """
    rules_per_customer: dict[str, set[str]] = defaultdict(set)
    for hit in hits:
        rules_per_customer[hit.customer_id].add(hit.rule_id)

    alerts: list[Alert] = []
    for hit in hits:
        n_other_rules = len(rules_per_customer[hit.customer_id]) - 1
        final = min(100, hit.base_score + CORROBORATION_BUMP * n_other_rules)
        alerts.append(Alert.from_hit(hit, final_score=final, tier=tier_for_score(final)))
    alerts.sort(key=lambda a: (-a.final_score, a.customer_id, a.rule_id))
    return alerts


@dataclass(slots=True)
class CustomerRisk:
    """Aggregated, investigator-facing view of one customer's risk."""

    customer_id: str
    customer_name: str
    score: int
    tier: Severity
    rules_fired: list[str]
    alert_count: int
    flagged_amount: Decimal
    first_activity: date | None
    last_activity: date | None
    narratives: list[str] = field(default_factory=list)


def _static_risk(customer: Customer, as_of: date) -> int:
    points = 0
    if customer.country in FATF_GREYLIST:
        points += STATIC_GREYLIST_HOME
    if customer.industry_code in HIGH_RISK_INDUSTRIES:
        points += STATIC_HIGH_RISK_INDUSTRY
    if (as_of - customer.onboarding_date).days < NEW_RELATIONSHIP_DAYS:
        points += STATIC_NEW_RELATIONSHIP
    return min(points, MAX_STATIC_RISK)


def score_customers(
    alerts: list[Alert],
    customers: list[Customer],
    transactions: list[Transaction],
    as_of: date,
) -> list[CustomerRisk]:
    """Build per-customer risk records from scored alerts, highest first."""
    customer_by_id = {c.customer_id: c for c in customers}
    txn_by_id = {t.txn_id: t for t in transactions}
    by_customer: dict[str, list[Alert]] = defaultdict(list)
    for alert in alerts:
        by_customer[alert.customer_id].append(alert)

    results: list[CustomerRisk] = []
    for customer_id, cust_alerts in by_customer.items():
        customer = customer_by_id.get(customer_id)
        if customer is None:
            continue
        rules = sorted({a.rule_id for a in cust_alerts})
        max_alert = max(a.final_score for a in cust_alerts)
        raw = (
            max_alert
            + BREADTH_POINTS * (len(rules) - 1)
            + _static_risk(customer, as_of)
        )
        score = min(100, round(raw))

        flagged_ids = {tid for a in cust_alerts for tid in a.txn_ids}
        flagged_txns = [txn_by_id[tid] for tid in flagged_ids if tid in txn_by_id]
        dates = sorted(t.timestamp.date() for t in flagged_txns)
        results.append(
            CustomerRisk(
                customer_id=customer_id,
                customer_name=customer.name,
                score=score,
                tier=tier_for_score(score),
                rules_fired=rules,
                alert_count=len(cust_alerts),
                flagged_amount=sum((t.amount for t in flagged_txns), Decimal("0")),
                first_activity=dates[0] if dates else None,
                last_activity=dates[-1] if dates else None,
                narratives=[a.narrative for a in cust_alerts],
            )
        )
    results.sort(key=lambda r: (-r.score, r.customer_id))
    return results


def sar_worklist(customer_risks: list[CustomerRisk]) -> list[CustomerRisk]:
    """SAR-candidate worklist: customers at HIGH tier or above."""
    return [r for r in customer_risks if r.tier in (Severity.HIGH, Severity.CRITICAL)]
