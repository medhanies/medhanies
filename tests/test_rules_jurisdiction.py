from aml_engine.models import TxnType
from aml_engine.rules.jurisdiction import (
    FatfBlacklistRule,
    FatfGreylistCorridorRule,
    OfacJurisdictionRule,
)
from tests.conftest import make_ctx, make_txn


def wire(txn_id, country, *, amount="5000.00", offset_hours=0, outbound=True, customer_id="C1"):
    return make_txn(
        txn_id,
        amount=amount,
        txn_type=TxnType.WIRE_OUT if outbound else TxnType.WIRE_IN,
        customer_id=customer_id,
        account_id="A1",
        offset_hours=offset_hours,
        originator_country="US" if outbound else country,
        beneficiary_country=country if outbound else "US",
    )


class TestOfacJurisdiction:
    rule = OfacJurisdictionRule()

    def test_comprehensive_country_fires_critical(self):
        hits = self.rule.evaluate(make_ctx([wire("T1", "IR")]))
        assert len(hits) == 1
        assert hits[0].severity.value == "CRITICAL"
        assert hits[0].base_score == 95

    def test_embargoed_region_fires_critical(self):
        hits = self.rule.evaluate(make_ctx([wire("T1", "UA-CRI")]))
        assert len(hits) == 1
        assert hits[0].severity.value == "CRITICAL"

    def test_russia_sectoral_fires_high_not_critical(self):
        # RU is sectoral/list-based (E.O. 14024), not a comprehensive
        # embargo — must flag at reduced severity, not CRITICAL.
        hits = self.rule.evaluate(make_ctx([wire("T1", "RU")]))
        assert len(hits) == 1
        assert hits[0].severity.value == "HIGH"
        assert hits[0].base_score == 65

    def test_inbound_wire_also_fires(self):
        hits = self.rule.evaluate(make_ctx([wire("T1", "KP", outbound=False)]))
        assert len(hits) == 1

    def test_benign_country_silent(self):
        assert self.rule.evaluate(make_ctx([wire("T1", "GB")])) == []

    def test_non_wire_types_ignored(self):
        txn = make_txn("T1", amount="5000.00", beneficiary_country="IR")
        assert txn.txn_type == TxnType.CASH_DEPOSIT
        assert self.rule.evaluate(make_ctx([txn])) == []


class TestFatfBlacklist:
    rule = FatfBlacklistRule()

    def test_myanmar_fires(self):
        hits = self.rule.evaluate(make_ctx([wire("T1", "MM")]))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-JURIS-002"

    def test_iran_skipped_as_ofac_covered(self):
        # IR is on both lists; R-JURIS-001 owns it at CRITICAL, so this
        # rule must not double-alert.
        assert self.rule.evaluate(make_ctx([wire("T1", "IR")])) == []

    def test_greylist_country_silent(self):
        assert self.rule.evaluate(make_ctx([wire("T1", "NG")])) == []


class TestFatfGreylistCorridor:
    rule = FatfGreylistCorridorRule()

    def test_single_greylist_wire_is_not_flagged(self):
        # One wire involving a greylist country is routine banking.
        assert self.rule.evaluate(make_ctx([wire("T1", "NG")])) == []

    def test_three_wires_in_window_fire(self):
        txns = [wire(f"T{i}", "NG", offset_hours=i * 24 * 5) for i in range(3)]
        hits = self.rule.evaluate(make_ctx(txns))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-JURIS-003"
        assert len(hits[0].txn_ids) == 3

    def test_large_aggregate_fires_with_fewer_wires(self):
        txns = [
            wire("T1", "VN", amount="30000.00", offset_hours=0),
            wire("T2", "VN", amount="25000.00", offset_hours=48),
        ]
        hits = self.rule.evaluate(make_ctx(txns))
        assert len(hits) == 1

    def test_wires_outside_window_do_not_aggregate(self):
        txns = [wire(f"T{i}", "KE", offset_hours=i * 24 * 35) for i in range(3)]
        assert self.rule.evaluate(make_ctx(txns)) == []

    def test_blacklist_wire_not_counted_toward_greylist_pattern(self):
        txns = [wire(f"T{i}", "IR", offset_hours=i * 24) for i in range(3)]
        assert self.rule.evaluate(make_ctx(txns)) == []
