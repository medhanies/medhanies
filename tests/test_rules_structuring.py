from aml_engine.models import TxnType
from aml_engine.rules.structuring import (
    SameDayAggregationRule,
    SmurfingFunnelRule,
    SubThresholdCashPatternRule,
)
from tests.conftest import make_account, make_ctx, make_customer, make_txn


class TestSubThresholdCashPattern:
    rule = SubThresholdCashPatternRule()

    def test_fires_on_planted_pattern(self):
        txns = [
            make_txn("T1", amount="9200.00", offset_hours=0),
            make_txn("T2", amount="8800.00", offset_hours=20),
            make_txn("T3", amount="9500.00", offset_hours=40),
        ]
        hits = self.rule.evaluate(make_ctx(txns))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-STRUCT-001"
        assert sorted(hits[0].txn_ids) == ["T1", "T2", "T3"]
        assert hits[0].severity.value == "HIGH"

    def test_silent_on_clean_data(self, clean_transactions):
        assert self.rule.evaluate(make_ctx(clean_transactions)) == []

    def test_exactly_10000_is_not_structuring(self):
        # A $10,000.00 deposit is not "just under" the threshold; 31 CFR
        # 1010.311 requires a CTR only for MORE than $10,000.
        txns = [
            make_txn("T1", amount="10000.00", offset_hours=0),
            make_txn("T2", amount="10000.00", offset_hours=20),
            make_txn("T3", amount="10000.00", offset_hours=40),
        ]
        assert self.rule.evaluate(make_ctx(txns)) == []

    def test_9999_99_is_in_band(self):
        txns = [
            make_txn("T1", amount="9999.99", offset_hours=0),
            make_txn("T2", amount="9999.99", offset_hours=20),
            make_txn("T3", amount="9999.99", offset_hours=40),
        ]
        assert len(self.rule.evaluate(make_ctx(txns))) == 1

    def test_two_deposits_below_minimum_count(self):
        txns = [
            make_txn("T1", amount="9500.00", offset_hours=0),
            make_txn("T2", amount="9500.00", offset_hours=10),
        ]
        assert self.rule.evaluate(make_ctx(txns)) == []

    def test_deposits_outside_72h_window_do_not_cluster(self):
        txns = [
            make_txn("T1", amount="9500.00", offset_hours=0),
            make_txn("T2", amount="9500.00", offset_hours=100),
            make_txn("T3", amount="9500.00", offset_hours=200),
        ]
        assert self.rule.evaluate(make_ctx(txns)) == []

    def test_overlapping_windows_merge_to_one_hit(self):
        txns = [
            make_txn(f"T{i}", amount="9000.00", offset_hours=i * 12) for i in range(6)
        ]
        hits = self.rule.evaluate(make_ctx(txns))
        assert len(hits) == 1
        assert len(hits[0].txn_ids) == 6


class TestSameDayAggregation:
    rule = SameDayAggregationRule()

    def test_fires_on_multi_account_daily_pattern(self):
        # $4,600 + $4,600 = $9,200/day across two accounts, on 3 days.
        txns = []
        for day in range(3):
            txns.append(
                make_txn(
                    f"Ta{day}", amount="4600.00", account_id="A1",
                    offset_hours=day * 24,
                )
            )
            txns.append(
                make_txn(
                    f"Tb{day}", amount="4600.00", account_id="A2",
                    offset_hours=day * 24 + 2,
                )
            )
        customer = make_customer("C1")
        accounts = [make_account("A1", "C1"), make_account("A2", "C1")]
        hits = self.rule.evaluate(make_ctx(txns, [customer], accounts))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-STRUCT-002"
        assert len(hits[0].txn_ids) == 6

    def test_silent_on_clean_data(self, clean_transactions):
        assert self.rule.evaluate(make_ctx(clean_transactions)) == []

    def test_two_qualifying_days_insufficient(self):
        txns = []
        for day in range(2):
            txns.append(make_txn(f"T{day}", amount="9000.00", offset_hours=day * 24))
        assert self.rule.evaluate(make_ctx(txns)) == []

    def test_days_spread_beyond_span_do_not_qualify(self):
        txns = [
            make_txn("T1", amount="9000.00", offset_hours=0),
            make_txn("T2", amount="9000.00", offset_hours=20 * 24),
            make_txn("T3", amount="9000.00", offset_hours=40 * 24),
        ]
        assert self.rule.evaluate(make_ctx(txns)) == []


class TestSmurfingFunnel:
    rule = SmurfingFunnelRule()

    def test_fires_on_funnel_pattern(self):
        txns = [
            make_txn(
                f"T{i}",
                amount="6000.00",
                txn_type=TxnType.WIRE_OUT,
                account_id=f"A{i}",
                customer_id=f"C{i}",
                counterparty_account_id="FUNNEL",
                offset_hours=i * 24,
            )
            for i in range(1, 4)
        ]
        customers = [make_customer(f"C{i}") for i in range(1, 4)] + [make_customer("C9")]
        accounts = [make_account(f"A{i}", f"C{i}") for i in range(1, 4)] + [
            make_account("FUNNEL", "C9")
        ]
        hits = self.rule.evaluate(make_ctx(txns, customers, accounts))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-STRUCT-003"
        assert hits[0].customer_id == "C9"  # attaches to the funnel owner
        assert hits[0].account_id == "FUNNEL"

    def test_two_originators_insufficient(self):
        txns = [
            make_txn(
                f"T{i}",
                amount="9000.00",
                txn_type=TxnType.WIRE_OUT,
                account_id=f"A{i}",
                customer_id=f"C{i}",
                counterparty_account_id="FUNNEL",
                offset_hours=i * 10,
            )
            for i in range(1, 3)
        ]
        customers = [make_customer(f"C{i}") for i in range(1, 3)] + [make_customer("C9")]
        accounts = [make_account(f"A{i}", f"C{i}") for i in range(1, 3)] + [
            make_account("FUNNEL", "C9")
        ]
        assert self.rule.evaluate(make_ctx(txns, customers, accounts)) == []

    def test_aggregate_below_minimum_insufficient(self):
        # 3 originators but only $3,000 total — below the $15,000 floor.
        txns = [
            make_txn(
                f"T{i}",
                amount="1000.00",
                txn_type=TxnType.WIRE_OUT,
                account_id=f"A{i}",
                customer_id=f"C{i}",
                counterparty_account_id="FUNNEL",
                offset_hours=i * 10,
            )
            for i in range(1, 4)
        ]
        customers = [make_customer(f"C{i}") for i in range(1, 4)] + [make_customer("C9")]
        accounts = [make_account(f"A{i}", f"C{i}") for i in range(1, 4)] + [
            make_account("FUNNEL", "C9")
        ]
        assert self.rule.evaluate(make_ctx(txns, customers, accounts)) == []

    def test_silent_on_clean_data(self, clean_transactions):
        assert self.rule.evaluate(make_ctx(clean_transactions)) == []
