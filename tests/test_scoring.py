from datetime import date
from decimal import Decimal

from aml_engine.models import RuleHit, Severity
from aml_engine.scoring import (
    score_alerts,
    score_customers,
    tier_for_score,
)
from tests.conftest import make_customer, make_txn


def hit(rule_id, *, base_score, customer_id="C1", severity=Severity.MEDIUM, txn_ids=None):
    return RuleHit(
        rule_id=rule_id,
        rule_name=rule_id,
        citation="test",
        severity=severity,
        base_score=base_score,
        txn_ids=txn_ids or ["T1"],
        customer_id=customer_id,
        account_id=None,
        narrative="test narrative",
    )


class TestTiers:
    def test_boundaries(self):
        assert tier_for_score(85) == Severity.CRITICAL
        assert tier_for_score(84) == Severity.HIGH
        assert tier_for_score(65) == Severity.HIGH
        assert tier_for_score(64) == Severity.MEDIUM
        assert tier_for_score(40) == Severity.MEDIUM
        assert tier_for_score(39) == Severity.LOW
        assert tier_for_score(0) == Severity.LOW


class TestAlertScoring:
    def test_single_rule_keeps_base_score(self):
        alerts = score_alerts([hit("R-A", base_score=70)])
        assert alerts[0].final_score == 70

    def test_corroboration_bump(self):
        alerts = score_alerts(
            [hit("R-A", base_score=70), hit("R-B", base_score=50)]
        )
        by_rule = {a.rule_id: a for a in alerts}
        assert by_rule["R-A"].final_score == 80  # 70 + 10 for one other rule
        assert by_rule["R-B"].final_score == 60

    def test_capped_at_100(self):
        alerts = score_alerts(
            [hit("R-A", base_score=95), hit("R-B", base_score=50), hit("R-C", base_score=50)]
        )
        assert max(a.final_score for a in alerts) == 100

    def test_one_ofac_outranks_four_mediums(self):
        # Dominant-rule methodology: a single CRITICAL OFAC hit on one
        # customer must outrank four corroborating MEDIUM hits on another.
        ofac = score_alerts([hit("R-OFAC", base_score=95, customer_id="C1")])
        mediums = score_alerts(
            [hit(f"R-{i}", base_score=50, customer_id="C2") for i in range(4)]
        )
        assert max(a.final_score for a in ofac) > max(a.final_score for a in mediums)

    def test_same_rule_twice_is_not_corroboration(self):
        alerts = score_alerts(
            [hit("R-A", base_score=70), hit("R-A", base_score=70)]
        )
        assert all(a.final_score == 70 for a in alerts)


class TestCustomerScoring:
    def test_customer_never_scores_below_worst_alert(self):
        customer = make_customer("C1")
        txns = [make_txn("T1", amount="9000.00")]
        alerts = score_alerts([hit("R-A", base_score=70, txn_ids=["T1"])])
        risks = score_customers(alerts, [customer], txns, as_of=date(2025, 3, 31))
        assert risks[0].score >= 70

    def test_breadth_adds_points(self):
        customer = make_customer("C1")
        txns = [make_txn("T1", amount="9000.00")]
        one = score_customers(
            score_alerts([hit("R-A", base_score=70, txn_ids=["T1"])]),
            [customer], txns, as_of=date(2025, 3, 31),
        )
        two = score_customers(
            score_alerts(
                [hit("R-A", base_score=70, txn_ids=["T1"]),
                 hit("R-B", base_score=50, txn_ids=["T1"])]
            ),
            [customer], txns, as_of=date(2025, 3, 31),
        )
        assert two[0].score > one[0].score

    def test_static_risk_factors(self):
        txns = [make_txn("T1", amount="9000.00")]
        alerts = score_alerts([hit("R-A", base_score=50, txn_ids=["T1"])])
        plain = make_customer("C1")
        risky = make_customer(
            "C1",
            business=True,
            country="NG",  # FATF greylist home country
            industry_code="MSB",  # high-risk industry
            onboarding_date=date(2025, 3, 1),  # < 90 days before as_of
        )
        base = score_customers(alerts, [plain], txns, as_of=date(2025, 3, 31))[0].score
        elevated = score_customers(alerts, [risky], txns, as_of=date(2025, 3, 31))[0].score
        assert elevated == base + 15

    def test_flagged_amount_deduplicates_transactions(self):
        customer = make_customer("C1")
        txns = [make_txn("T1", amount="9000.00")]
        alerts = score_alerts(
            [hit("R-A", base_score=70, txn_ids=["T1"]),
             hit("R-B", base_score=50, txn_ids=["T1"])]
        )
        risks = score_customers(alerts, [customer], txns, as_of=date(2025, 3, 31))
        assert risks[0].flagged_amount == Decimal("9000.00")
