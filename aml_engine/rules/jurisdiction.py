"""High-risk jurisdiction rules.

Three distinct regimes are modeled, because they carry very different
obligations:

1. OFAC comprehensive embargoes and embargoed regions — prohibited dealings;
   in production these are interdicted at payment screening, not merely
   monitored. Russia/Belarus are deliberately handled as a lower-severity
   branch because those programs are sectoral and list-based (E.O. 14024 /
   14038), not comprehensive country embargoes.
2. FATF "Call for Action" blacklist — enhanced scrutiny and, for some
   jurisdictions, countermeasures under 31 U.S.C. 5318A special measures.
3. FATF "Increased Monitoring" greylist — elevated geographic risk factor.
   A single greylist wire is ordinary international banking; only a pattern
   of corridor activity is flagged.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aml_engine.models import WIRE_TYPES, RuleHit, Severity, Transaction
from aml_engine.reference_data import (
    FATF_BLACKLIST,
    FATF_GREYLIST,
    OFAC_COMPREHENSIVE,
    OFAC_ELEVATED,
    OFAC_REGIONS,
)
from aml_engine.rules import Rule, RuleContext

OFAC_PROHIBITED = OFAC_COMPREHENSIVE | OFAC_REGIONS


def _foreign_countries(txn: Transaction) -> set[str]:
    return {c for c in (txn.originator_country, txn.beneficiary_country) if c != "US"}


class OfacJurisdictionRule(Rule):
    """R-JURIS-001 — wire exposure to OFAC-sanctioned jurisdictions.

    Comprehensive-program countries and embargoed regions fire CRITICAL.
    Russia/Belarus (sectoral programs) fire a HIGH-severity screening
    referral instead.
    """

    rule_id = "R-JURIS-001"
    name = "OFAC sanctioned-jurisdiction exposure"
    citation = (
        "31 CFR Parts 560 (Iran), 510 (North Korea), 515 (Cuba), 542 (Syria); "
        "E.O. 13685/14065 (embargoed Ukraine regions); IEEPA, 50 U.S.C. 1701 et seq."
    )
    severity = Severity.CRITICAL
    base_score = 95
    description = (
        "Wire activity involving a comprehensively sanctioned country or "
        "embargoed region; Russia/Belarus sectoral-program exposure is "
        "flagged at reduced severity for sanctions-screening referral."
    )

    ELEVATED_SEVERITY = Severity.HIGH
    ELEVATED_SCORE = 65

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for txn in ctx.txns_sorted:
            if txn.txn_type not in WIRE_TYPES:
                continue
            countries = _foreign_countries(txn)
            prohibited = countries & OFAC_PROHIBITED
            elevated = countries & OFAC_ELEVATED
            if prohibited:
                jur = ", ".join(sorted(prohibited))
                hits.append(
                    self.make_hit(
                        txn_ids=[txn.txn_id],
                        customer_id=txn.customer_id,
                        account_id=txn.account_id,
                        narrative=(
                            f"Wire of ${txn.amount:,.2f} on {txn.timestamp:%Y-%m-%d} "
                            f"involves OFAC comprehensively sanctioned jurisdiction(s) "
                            f"{jur} (counterparty: {txn.counterparty_name or 'unknown'}). "
                            f"In production this transaction would be blocked or rejected "
                            f"at screening and reported to OFAC, not merely alerted."
                        ),
                    )
                )
            elif elevated:
                jur = ", ".join(sorted(elevated))
                hits.append(
                    self.make_hit(
                        txn_ids=[txn.txn_id],
                        customer_id=txn.customer_id,
                        account_id=txn.account_id,
                        severity=self.ELEVATED_SEVERITY,
                        base_score=self.ELEVATED_SCORE,
                        narrative=(
                            f"Wire of ${txn.amount:,.2f} on {txn.timestamp:%Y-%m-%d} "
                            f"involves {jur}, subject to broad sectoral/list-based OFAC "
                            f"programs (not a comprehensive embargo). Refer for SDN and "
                            f"sectoral-sanctions screening of all parties."
                        ),
                    )
                )
        return hits


class FatfBlacklistRule(Rule):
    """R-JURIS-002 — counterparty in a FATF Call-for-Action jurisdiction.

    Skips transactions already flagged CRITICAL by R-JURIS-001 (Iran and
    North Korea are on both lists); Myanmar is the differentiating case.
    """

    rule_id = "R-JURIS-002"
    name = "FATF blacklist counterparty"
    citation = (
        'FATF "High-Risk Jurisdictions subject to a Call for Action" '
        "(Feb 2025: Iran, DPRK, Myanmar); 31 U.S.C. 5318A (special measures)"
    )
    severity = Severity.HIGH
    base_score = 80
    description = (
        "Wire to or from a FATF Call-for-Action jurisdiction not already "
        "covered by an OFAC comprehensive program."
    )

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for txn in ctx.txns_sorted:
            if txn.txn_type not in WIRE_TYPES:
                continue
            countries = _foreign_countries(txn)
            if countries & OFAC_PROHIBITED:
                continue  # already CRITICAL under R-JURIS-001
            listed = countries & FATF_BLACKLIST
            if listed:
                jur = ", ".join(sorted(listed))
                hits.append(
                    self.make_hit(
                        txn_ids=[txn.txn_id],
                        customer_id=txn.customer_id,
                        account_id=txn.account_id,
                        narrative=(
                            f"Wire of ${txn.amount:,.2f} on {txn.timestamp:%Y-%m-%d} "
                            f"involves {jur}, a FATF Call-for-Action jurisdiction "
                            f"requiring enhanced due diligence and potential "
                            f"countermeasures."
                        ),
                    )
                )
        return hits


class FatfGreylistCorridorRule(Rule):
    """R-JURIS-003 — pattern of activity through FATF greylist corridors.

    A single wire involving a greylist country is routine; the rule requires
    a per-customer pattern within a rolling 30-day window: three or more
    greylist wires, or greylist wire volume of $50,000 or more.
    """

    rule_id = "R-JURIS-003"
    name = "FATF greylist corridor activity"
    citation = (
        'FATF "Jurisdictions under Increased Monitoring" (Feb 2025 snapshot); '
        "FFIEC BSA/AML Examination Manual — geographic risk factors"
    )
    severity = Severity.MEDIUM
    base_score = 45
    description = (
        "Three or more wires, or $50,000+ aggregate volume, to/from FATF "
        "Increased Monitoring jurisdictions within 30 days for one customer."
    )

    WINDOW = timedelta(days=30)
    MIN_WIRES = 3
    MIN_AGGREGATE = Decimal("50000")

    def evaluate(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for customer_id, txns in ctx.by_customer.items():
            greylist_wires = [
                t
                for t in txns
                if t.txn_type in WIRE_TYPES
                and (_foreign_countries(t) & FATF_GREYLIST)
                and not (_foreign_countries(t) & (OFAC_PROHIBITED | FATF_BLACKLIST))
            ]
            best: list[Transaction] = []
            for i, start in enumerate(greylist_wires):
                window = [
                    t
                    for t in greylist_wires[i:]
                    if t.timestamp - start.timestamp <= self.WINDOW
                ]
                qualifies = (
                    len(window) >= self.MIN_WIRES
                    or sum(t.amount for t in window) >= self.MIN_AGGREGATE
                )
                if qualifies and len(window) > len(best):
                    best = window
            if best:
                countries = sorted({c for t in best for c in _foreign_countries(t) & FATF_GREYLIST})
                total = sum(t.amount for t in best)
                hits.append(
                    self.make_hit(
                        txn_ids=[t.txn_id for t in best],
                        customer_id=customer_id,
                        narrative=(
                            f"{len(best)} wires totaling ${total:,.2f} to/from FATF "
                            f"Increased-Monitoring jurisdiction(s) {', '.join(countries)} "
                            f"within 30 days. Repeated corridor activity elevates the "
                            f"customer's geographic risk profile."
                        ),
                    )
                )
        return hits
