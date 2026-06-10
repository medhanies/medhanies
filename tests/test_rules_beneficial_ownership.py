from aml_engine.models import BeneficialOwner, TxnType
from aml_engine.rules.beneficial_ownership import (
    NoIdentifiableBeneficialOwnerRule,
    NomineeOwnerRule,
    RoundDollarPassThroughRule,
    SecrecyHavenShellRule,
)
from tests.conftest import make_account, make_ctx, make_customer, make_txn


class TestNoIdentifiableBeneficialOwner:
    rule = NoIdentifiableBeneficialOwnerRule()

    def test_fires_when_no_owner_reaches_25_pct(self):
        customer = make_customer(
            "C1",
            business=True,
            beneficial_owners=[
                BeneficialOwner("A", 20.0),
                BeneficialOwner("B", 20.0),
                BeneficialOwner("C", 20.0),
            ],
        )
        hits = self.rule.evaluate(make_ctx([], [customer], []))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-BO-001"
        assert hits[0].base_score == 50

    def test_exactly_25_pct_owner_satisfies_cdd_prong(self):
        # The CDD Rule threshold is "25 percent or more" — exactly 25.0%
        # is an identifiable beneficial owner, so no hit.
        customer = make_customer(
            "C1", business=True, beneficial_owners=[BeneficialOwner("A", 25.0)]
        )
        assert self.rule.evaluate(make_ctx([], [customer], [])) == []

    def test_deep_chain_fires(self):
        customer = make_customer(
            "C1",
            business=True,
            ownership_chain_depth=3,
            beneficial_owners=[BeneficialOwner("A", 60.0)],
        )
        hits = self.rule.evaluate(make_ctx([], [customer], []))
        assert len(hits) == 1

    def test_both_conditions_raise_score(self):
        customer = make_customer(
            "C1",
            business=True,
            ownership_chain_depth=4,
            beneficial_owners=[BeneficialOwner("A", 10.0)],
        )
        hits = self.rule.evaluate(make_ctx([], [customer], []))
        assert hits[0].base_score == 60

    def test_individuals_exempt(self):
        customer = make_customer("C1")
        assert self.rule.evaluate(make_ctx([], [customer], [])) == []

    def test_clean_business_silent(self):
        customer = make_customer("C1", business=True)
        assert self.rule.evaluate(make_ctx([], [customer], [])) == []


class TestNomineeOwner:
    rule = NomineeOwnerRule()

    def test_fires_on_nominee(self):
        customer = make_customer(
            "C1",
            business=True,
            beneficial_owners=[BeneficialOwner("Nom Inee", 100.0, is_nominee=True)],
        )
        hits = self.rule.evaluate(make_ctx([], [customer], []))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-BO-002"

    def test_silent_without_nominee(self):
        customer = make_customer("C1", business=True)
        assert self.rule.evaluate(make_ctx([], [customer], [])) == []


class TestSecrecyHavenShell:
    rule = SecrecyHavenShellRule()

    @staticmethod
    def _shell(**overrides):
        defaults = dict(
            business=True,
            registration_country="VG",
            has_physical_address=False,
        )
        defaults.update(overrides)
        return make_customer("C1", **defaults)

    def test_fires_on_shell_profile(self):
        txns = [make_txn(f"T{i}", amount="5000.00", txn_type=TxnType.WIRE_IN, offset_hours=i) for i in range(3)]
        hits = self.rule.evaluate(make_ctx(txns, [self._shell()], [make_account()]))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-BO-003"

    def test_physical_address_negates(self):
        txns = [make_txn("T1", amount="5000.00")]
        customer = self._shell(has_physical_address=True)
        assert self.rule.evaluate(make_ctx(txns, [customer], [make_account()])) == []

    def test_foreign_activity_negates(self):
        # Mostly cross-border volume → offshore registration has an
        # apparent business purpose; rule requires >=90% domestic.
        txns = [
            make_txn(
                "T1",
                amount="50000.00",
                txn_type=TxnType.WIRE_OUT,
                beneficiary_country="DE",
            ),
            make_txn("T2", amount="1000.00"),
        ]
        assert self.rule.evaluate(make_ctx(txns, [self._shell()], [make_account()])) == []

    def test_us_registration_negates(self):
        txns = [make_txn("T1", amount="5000.00")]
        customer = self._shell(registration_country="US")
        assert self.rule.evaluate(make_ctx(txns, [customer], [make_account()])) == []


class TestRoundDollarPassThrough:
    rule = RoundDollarPassThroughRule()

    @staticmethod
    def _pair(n, *, amount="40000", offset_days=0, out_gap_hours=24):
        base = offset_days * 24
        return [
            make_txn(
                f"Tin{n}", amount=amount, txn_type=TxnType.WIRE_IN, offset_hours=base
            ),
            make_txn(
                f"Tout{n}",
                amount=amount,
                txn_type=TxnType.WIRE_OUT,
                offset_hours=base + out_gap_hours,
            ),
        ]

    def _ctx(self, txns):
        customer = make_customer("C1", business=True)
        return make_ctx(txns, [customer], [make_account()])

    def test_fires_on_two_pairs(self):
        txns = self._pair(1) + self._pair(2, offset_days=7)
        hits = self.rule.evaluate(self._ctx(txns))
        assert len(hits) == 1
        assert hits[0].rule_id == "R-BO-004"
        assert len(hits[0].txn_ids) == 4

    def test_single_pair_insufficient(self):
        assert self.rule.evaluate(self._ctx(self._pair(1))) == []

    def test_non_round_amounts_silent(self):
        txns = self._pair(1, amount="40123.45") + self._pair(2, amount="38777.10", offset_days=7)
        assert self.rule.evaluate(self._ctx(txns)) == []

    def test_small_round_amounts_silent(self):
        # Round but below the $20,000 floor.
        txns = self._pair(1, amount="5000") + self._pair(2, amount="5000", offset_days=7)
        assert self.rule.evaluate(self._ctx(txns)) == []

    def test_slow_exit_silent(self):
        # Funds leave after 5 days — not pass-through behavior.
        txns = self._pair(1, out_gap_hours=120) + self._pair(2, offset_days=7, out_gap_hours=120)
        assert self.rule.evaluate(self._ctx(txns)) == []

    def test_individual_accounts_exempt(self):
        txns = self._pair(1) + self._pair(2, offset_days=7)
        customer = make_customer("C1")  # individual
        assert self.rule.evaluate(make_ctx(txns, [customer], [make_account()])) == []
