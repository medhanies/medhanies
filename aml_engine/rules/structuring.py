"""Structuring rules.

Structuring — breaking cash transactions into amounts below the $10,000
Currency Transaction Report threshold to evade BSA reporting — is a federal
crime under 31 U.S.C. § 5324 regardless of whether the underlying funds are
legitimate. These rules implement the three classic presentations: repeated
sub-threshold deposits into one account, same-owner aggregation across
accounts, and third-party "smurfing" into a funnel account.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aml_engine.models import CASH_IN_TYPES, RuleHit, Severity, Transaction
from aml_engine.reference_data import (
    CTR_THRESHOLD,
    STRUCTURING_BAND_HIGH,
    STRUCTURING_BAND_LOW,
)
from aml_engine.rules import Rule, RuleContext


def _in_structuring_band(txn: Transaction) -> bool:
    # Band is [low, high): exactly $10,000.00 is NOT "just under" the
    # threshold (and 31 CFR 1010.311 itself only requires a CTR for
    # transactions of MORE than $10,000).
    return STRUCTURING_BAND_LOW <= txn.amount < STRUCTURING_BAND_HIGH


def _merge_clusters(clusters: list[list[Transaction]]) -> list[list[Transaction]]:
    """Merge clusters that share any transaction so one scheme yields one hit."""
    merged: list[dict[str, Transaction]] = []
    for cluster in clusters:
        ids = {t.txn_id for t in cluster}
        absorbed = None
        for existing in merged:
            if ids & existing.keys():
                existing.update({t.txn_id: t for t in cluster})
                absorbed = existing
                break
        if absorbed is None:
            merged.append({t.txn_id: t for t in cluster})
    return [sorted(group.values(), key=lambda t: t.timestamp) for group in merged]


class SubThresholdCashPatternRule(Rule):
    """R-STRUCT-001 — repeated just-under-threshold cash deposits.

    Detection: within any 72-hour window on a single account, three or more
    cash deposits each in the $7,000–$9,999.99 band whose aggregate exceeds
    $10,000. Overlapping windows are merged so one scheme produces one hit.
    """

    rule_id = "R-STRUCT-001"
    name = "Sub-threshold cash deposit pattern"
    citation = "31 CFR 1010.311 (CTR threshold); 31 U.S.C. 5324(a)(3) (structuring)"
    severity = Severity.HIGH
    base_score = 70
    description = (
        "Three or more cash deposits of $7,000–$9,999.99 into one account "
        "within 72 hours, aggregating over $10,000 — the classic pattern of "
        "splitting reportable cash to evade CTR filing."
    )

    WINDOW = timedelta(hours=72)
    MIN_COUNT = 3

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for account_id, txns in ctx.by_account.items():
            band_deposits = [
                t for t in txns if t.txn_type in CASH_IN_TYPES and _in_structuring_band(t)
            ]
            clusters: list[list[Transaction]] = []
            for i, start in enumerate(band_deposits):
                window = [
                    t
                    for t in band_deposits[i:]
                    if t.timestamp - start.timestamp <= self.WINDOW
                ]
                if (
                    len(window) >= self.MIN_COUNT
                    and sum(t.amount for t in window) > CTR_THRESHOLD
                ):
                    clusters.append(window)
            for cluster in _merge_clusters(clusters):
                total = sum(t.amount for t in cluster)
                first, last = cluster[0], cluster[-1]
                hits.append(
                    self.make_hit(
                        txn_ids=[t.txn_id for t in cluster],
                        customer_id=first.customer_id,
                        account_id=account_id,
                        narrative=(
                            f"{len(cluster)} cash deposits totaling ${total:,.2f}, each "
                            f"individually below the $10,000 CTR threshold, made to account "
                            f"{account_id} between {first.timestamp:%Y-%m-%d %H:%M} and "
                            f"{last.timestamp:%Y-%m-%d %H:%M}. Pattern is consistent with "
                            f"structuring to evade currency transaction reporting."
                        ),
                    )
                )
        return hits


class SameDayAggregationRule(Rule):
    """R-STRUCT-002 — multi-account same-day cash aggregation just under CTR.

    31 CFR 1010.313(b) requires banks to aggregate same-business-day currency
    transactions by or on behalf of the same person. A customer whose
    combined daily cash-in repeatedly lands just under $10,000 across
    multiple accounts is evading that aggregation.

    Detection: per customer, calendar-day cash-deposit totals in the
    $8,000–$9,999.99 band on three or more days within any 14-day span.
    """

    rule_id = "R-STRUCT-002"
    name = "Same-day multi-account aggregation under CTR threshold"
    citation = "31 CFR 1010.313(b) (same-day aggregation); 31 U.S.C. 5324"
    severity = Severity.HIGH
    base_score = 70
    description = (
        "Customer's aggregate daily cash deposits across all accounts land "
        "in $8,000–$9,999.99 on three or more days within two weeks."
    )

    DAILY_BAND_LOW = Decimal("8000")
    DAILY_BAND_HIGH = CTR_THRESHOLD  # exclusive
    MIN_DAYS = 3
    SPAN = timedelta(days=14)

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for customer_id, txns in ctx.by_customer.items():
            daily: dict = {}
            for t in txns:
                if t.txn_type in CASH_IN_TYPES:
                    day = t.timestamp.date()
                    total, ids = daily.get(day, (Decimal("0"), []))
                    daily[day] = (total + t.amount, ids + [t.txn_id])
            band_days = sorted(
                (day, total, ids)
                for day, (total, ids) in daily.items()
                if self.DAILY_BAND_LOW <= total < self.DAILY_BAND_HIGH
            )
            # Slide over qualifying days looking for MIN_DAYS within SPAN;
            # greedily take the longest run so one scheme yields one hit.
            i = 0
            while i < len(band_days):
                run = [band_days[i]]
                j = i + 1
                while j < len(band_days) and (
                    band_days[j][0] - run[0][0] <= self.SPAN
                ):
                    run.append(band_days[j])
                    j += 1
                if len(run) >= self.MIN_DAYS:
                    txn_ids = [tid for _, _, ids in run for tid in ids]
                    total = sum(t for _, t, _ in run)
                    hits.append(
                        self.make_hit(
                            txn_ids=txn_ids,
                            customer_id=customer_id,
                            narrative=(
                                f"Aggregate daily cash deposits of $8,000–$9,999.99 on "
                                f"{len(run)} days between {run[0][0]} and {run[-1][0]} "
                                f"(combined ${total:,.2f}), spread across the customer's "
                                f"accounts. Consistent with structuring around same-day "
                                f"aggregation under 31 CFR 1010.313(b)."
                            ),
                        )
                    )
                i = j if len(run) >= self.MIN_DAYS else i + 1
        return hits


class SmurfingFunnelRule(Rule):
    """R-STRUCT-003 — smurfing / funnel-account activity.

    Multiple unrelated originators each sending sub-threshold amounts into
    one beneficiary account is the funnel-account typology described in
    FinCEN Advisory FIN-2014-A005.

    Detection: per beneficiary account, within a rolling 7-day window,
    transfers from three or more distinct originating customers, each
    transfer under $10,000, aggregating to $15,000 or more.
    """

    rule_id = "R-STRUCT-003"
    name = "Smurfing / funnel account"
    citation = "31 U.S.C. 5324; FinCEN Advisory FIN-2014-A005 (funnel accounts)"
    severity = Severity.HIGH
    base_score = 75
    description = (
        "Three or more distinct originators send sub-$10,000 transfers into "
        "one account within 7 days, aggregating $15,000 or more."
    )

    WINDOW = timedelta(days=7)
    MIN_ORIGINATORS = 3
    MIN_AGGREGATE = Decimal("15000")
    PER_TXN_MAX = CTR_THRESHOLD  # exclusive

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for beneficiary_account_id, inbound in ctx.inbound_by_counterparty.items():
            beneficiary = ctx.account_by_id.get(beneficiary_account_id)
            if beneficiary is None:
                continue
            eligible = [
                t
                for t in inbound
                if t.amount < self.PER_TXN_MAX and t.customer_id != beneficiary.customer_id
            ]
            best: list[Transaction] = []
            for i, start in enumerate(eligible):
                window = [
                    t
                    for t in eligible[i:]
                    if t.timestamp - start.timestamp <= self.WINDOW
                ]
                originators = {t.customer_id for t in window}
                if (
                    len(originators) >= self.MIN_ORIGINATORS
                    and sum(t.amount for t in window) >= self.MIN_AGGREGATE
                    and len(window) > len(best)
                ):
                    best = window
            if best:
                originators = sorted({t.customer_id for t in best})
                total = sum(t.amount for t in best)
                hits.append(
                    self.make_hit(
                        txn_ids=[t.txn_id for t in best],
                        customer_id=beneficiary.customer_id,
                        account_id=beneficiary_account_id,
                        narrative=(
                            f"Account {beneficiary_account_id} received {len(best)} "
                            f"sub-$10,000 transfers totaling ${total:,.2f} from "
                            f"{len(originators)} distinct originators within 7 days "
                            f"({', '.join(originators)}). Consistent with the funnel-"
                            f"account typology in FinCEN Advisory FIN-2014-A005."
                        ),
                    )
                )
        return hits
