"""Beneficial-ownership and shell-company red-flag rules.

The FinCEN CDD Rule (31 CFR 1010.230) requires covered institutions to
identify each natural person owning 25% or more of a legal-entity customer
plus one individual with managerial control; the Corporate Transparency Act
(31 U.S.C. 5336) extends beneficial-ownership reporting to FinCEN itself.
FATF Recommendation 24 and the joint FATF/Egmont study "Concealment of
Beneficial Ownership" (2018) catalog the typologies modeled here: opaque
ownership chains, nominee arrangements, secrecy-haven registration, and
pass-through (conduit) transaction behavior.

These are entity-level rules: each hit attaches to the customer and, where
relevant, the transactions evidencing the behavior.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aml_engine.models import RuleHit, Severity, Transaction, TxnType
from aml_engine.reference_data import (
    BENEFICIAL_OWNER_PCT_THRESHOLD,
    SECRECY_HAVENS,
)
from aml_engine.rules import Rule, RuleContext


class NoIdentifiableBeneficialOwnerRule(Rule):
    """R-BO-001 — no identifiable 25% beneficial owner / opaque chain.

    Fires for business customers where no natural person reaches the CDD
    Rule's 25% ownership prong, or where the ownership chain runs three or
    more layers deep. Both conditions together raise the score.
    """

    rule_id = "R-BO-001"
    name = "No identifiable 25% beneficial owner / opaque ownership chain"
    citation = (
        "FinCEN CDD Rule, 31 CFR 1010.230 (25% ownership prong); "
        "Corporate Transparency Act, 31 U.S.C. 5336"
    )
    severity = Severity.MEDIUM
    base_score = 50
    description = (
        "Business customer with no natural person at or above 25% ownership, "
        "or an ownership chain three or more layers deep."
    )

    CHAIN_DEPTH_THRESHOLD = 3
    BOTH_CONDITIONS_BONUS = 10

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for customer in ctx.customers:
            if not customer.is_business:
                continue
            no_qualifying_owner = not any(
                o.ownership_pct >= BENEFICIAL_OWNER_PCT_THRESHOLD
                for o in customer.beneficial_owners
            )
            deep_chain = customer.ownership_chain_depth >= self.CHAIN_DEPTH_THRESHOLD
            if not (no_qualifying_owner or deep_chain):
                continue
            reasons = []
            if no_qualifying_owner:
                reasons.append(
                    "no natural person meets the 25% beneficial-ownership threshold"
                )
            if deep_chain:
                reasons.append(
                    f"ownership chain is {customer.ownership_chain_depth} layers deep"
                )
            score = self.base_score
            if no_qualifying_owner and deep_chain:
                score += self.BOTH_CONDITIONS_BONUS
            recent = ctx.by_customer.get(customer.customer_id, [])
            hits.append(
                self.make_hit(
                    txn_ids=[t.txn_id for t in recent],
                    customer_id=customer.customer_id,
                    base_score=score,
                    narrative=(
                        f"Entity {customer.name} ({customer.entity_type}): "
                        f"{' and '.join(reasons)}. Ownership cannot be traced to an "
                        f"identifiable natural person as contemplated by the CDD Rule."
                    ),
                )
            )
        return hits


class NomineeOwnerRule(Rule):
    """R-BO-002 — nominee directors or shareholders on the ownership record.

    Nominee arrangements are a primary concealment technique in the
    FATF/Egmont beneficial-ownership typologies.
    """

    rule_id = "R-BO-002"
    name = "Nominee directors/shareholders"
    citation = (
        "FATF Recommendation 24; FATF/Egmont Group, 'Concealment of Beneficial "
        "Ownership' (2018); FinCEN CDD Rule control prong, 31 CFR 1010.230"
    )
    severity = Severity.MEDIUM
    base_score = 55
    description = "Business customer whose ownership record includes nominee owners."

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for customer in ctx.customers:
            if not customer.is_business:
                continue
            nominees = [o for o in customer.beneficial_owners if o.is_nominee]
            if not nominees:
                continue
            names = ", ".join(o.owner_name for o in nominees)
            recent = ctx.by_customer.get(customer.customer_id, [])
            hits.append(
                self.make_hit(
                    txn_ids=[t.txn_id for t in recent],
                    customer_id=customer.customer_id,
                    narrative=(
                        f"Entity {customer.name} lists nominee owner(s) {names}, "
                        f"obscuring the true beneficial owner(s) — a primary "
                        f"concealment typology under FATF Recommendation 24."
                    ),
                )
            )
        return hits


class SecrecyHavenShellRule(Rule):
    """R-BO-003 — secrecy-haven registration with domestic-only activity.

    A company registered in a secrecy jurisdiction whose transactions are
    almost entirely U.S.-domestic, and which lacks a physical address, shows
    the classic shell profile: the offshore registration serves no apparent
    business purpose other than opacity.
    """

    rule_id = "R-BO-003"
    name = "Secrecy-haven registration with domestic-only activity"
    citation = (
        "FinCEN guidance on shell-company risk (2006); FATF Recommendation 24; "
        "FFIEC BSA/AML Examination Manual — business entities red flags"
    )
    severity = Severity.HIGH
    base_score = 60
    description = (
        "Business registered in a secrecy haven, with at least 90% domestic "
        "transaction volume and no physical address on record."
    )

    DOMESTIC_VOLUME_THRESHOLD = 0.9

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for customer in ctx.customers:
            if not customer.is_business:
                continue
            if customer.registration_country not in SECRECY_HAVENS:
                continue
            if customer.has_physical_address:
                continue
            txns = ctx.by_customer.get(customer.customer_id, [])
            if not txns:
                continue
            total = sum(t.amount for t in txns)
            domestic = sum(
                t.amount
                for t in txns
                if t.originator_country == "US" and t.beneficiary_country == "US"
            )
            if total == 0 or domestic / total < Decimal(str(self.DOMESTIC_VOLUME_THRESHOLD)):
                continue
            hits.append(
                self.make_hit(
                    txn_ids=[t.txn_id for t in txns],
                    customer_id=customer.customer_id,
                    narrative=(
                        f"Entity {customer.name} is registered in "
                        f"{customer.registration_country} (secrecy jurisdiction) with no "
                        f"physical address, yet {domestic / total:.0%} of its "
                        f"${total:,.2f} transaction volume is U.S.-domestic. Offshore "
                        f"registration appears to serve no purpose other than opacity."
                    ),
                )
            )
        return hits


class RoundDollarPassThroughRule(Rule):
    """R-BO-004 — round-dollar pass-through (conduit) behavior.

    Funds that enter and promptly exit an account in large round amounts,
    with the account retaining little or nothing, indicate the entity is a
    conduit rather than an operating business — a red flag in the FFIEC
    manual's funds-transfer section.

    Detection: per business account, wire-in events where at least 90% of
    the amount exits via wire-out within 72 hours, both legs are round
    multiples of $1,000 of at least $20,000, and at least two such in/out
    pairs occur within 30 days.
    """

    rule_id = "R-BO-004"
    name = "Round-dollar pass-through activity"
    citation = (
        "FFIEC BSA/AML Examination Manual — funds transfers red flags "
        "(pass-through/conduit activity, round-dollar wires); FATF Rec 24"
    )
    severity = Severity.HIGH
    base_score = 65
    description = (
        "Two or more round-dollar wire-in/wire-out pairs (>= $20,000, 90% "
        "pass-through within 72 hours) on one business account in 30 days."
    )

    EXIT_WINDOW = timedelta(hours=72)
    PAIR_WINDOW = timedelta(days=30)
    MIN_AMOUNT = Decimal("20000")
    ROUND_UNIT = Decimal("1000")
    PASS_THROUGH_RATIO = Decimal("0.9")
    MIN_PAIRS = 2

    def _is_round(self, amount: Decimal) -> bool:
        return amount >= self.MIN_AMOUNT and amount % self.ROUND_UNIT == 0

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for account_id, txns in ctx.by_account.items():
            account = ctx.account_by_id.get(account_id)
            if account is None:
                continue
            customer = ctx.customer_by_id.get(account.customer_id)
            if customer is None or not customer.is_business:
                continue
            wires_in = [
                t for t in txns if t.txn_type == TxnType.WIRE_IN and self._is_round(t.amount)
            ]
            wires_out = [
                t for t in txns if t.txn_type == TxnType.WIRE_OUT and self._is_round(t.amount)
            ]
            pairs: list[tuple[Transaction, Transaction]] = []
            used_out: set[str] = set()
            for win in wires_in:
                for wout in wires_out:
                    if wout.txn_id in used_out:
                        continue
                    delta = wout.timestamp - win.timestamp
                    if timedelta(0) <= delta <= self.EXIT_WINDOW and (
                        wout.amount >= win.amount * self.PASS_THROUGH_RATIO
                    ):
                        pairs.append((win, wout))
                        used_out.add(wout.txn_id)
                        break
            if len(pairs) < self.MIN_PAIRS:
                continue
            span = pairs[-1][1].timestamp - pairs[0][0].timestamp
            if span > self.PAIR_WINDOW:
                continue
            txn_ids = [t.txn_id for pair in pairs for t in pair]
            total_in = sum(win.amount for win, _ in pairs)
            hits.append(
                self.make_hit(
                    txn_ids=txn_ids,
                    customer_id=customer.customer_id,
                    account_id=account_id,
                    narrative=(
                        f"Account {account_id} ({customer.name}) shows {len(pairs)} "
                        f"round-dollar wire-in/wire-out pairs totaling ${total_in:,.2f} "
                        f"inbound, with funds exiting within 72 hours of receipt. "
                        f"Account behaves as a pass-through conduit rather than an "
                        f"operating business."
                    ),
                )
            )
        return hits
