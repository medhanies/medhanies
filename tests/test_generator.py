from aml_engine.engine import run_detection
from aml_engine.generator import generate_dataset
from aml_engine.models import Severity


def small_dataset(seed=7):
    return generate_dataset(seed=seed, n_customers=40, days=60)


class TestReproducibility:
    def test_same_seed_identical_output(self):
        a = small_dataset(seed=11)
        b = small_dataset(seed=11)
        assert a.transactions == b.transactions
        assert a.customers == b.customers
        assert a.ground_truth == b.ground_truth

    def test_different_seed_different_output(self):
        a = small_dataset(seed=11)
        b = small_dataset(seed=12)
        assert a.transactions != b.transactions


class TestGroundTruthIntegrity:
    def test_planted_txn_ids_exist_in_dataset(self):
        ds = small_dataset()
        all_ids = {t.txn_id for t in ds.transactions}
        for gt in ds.ground_truth:
            assert set(gt.txn_ids) <= all_ids

    def test_planted_customers_exist(self):
        ds = small_dataset()
        all_ids = {c.customer_id for c in ds.customers}
        for gt in ds.ground_truth:
            assert set(gt.customer_ids) <= all_ids

    def test_every_account_has_a_customer(self):
        ds = small_dataset()
        customer_ids = {c.customer_id for c in ds.customers}
        assert all(a.customer_id in customer_ids for a in ds.accounts)


class TestDetectionOnGeneratedData:
    def test_full_recall_on_planted_scenarios(self):
        ds = generate_dataset(seed=42)
        result = run_detection(ds.transactions, ds.accounts, ds.customers)
        for gt in ds.ground_truth:
            for rule_id in gt.expected_rule_ids:
                assert any(
                    a.rule_id == rule_id and set(a.txn_ids) & set(gt.txn_ids)
                    for a in result.alerts
                ), f"{gt.scenario_id} ({gt.pattern_name}) missed by {rule_id}"

    def test_benign_population_produces_no_high_alerts(self):
        """False-positive guard: pure benign data must stay quiet.

        Build a dataset, strip every transaction belonging to a planted
        scenario, and require that nothing at HIGH or CRITICAL fires on
        what remains.
        """
        ds = generate_dataset(seed=42)
        planted_txns = {tid for gt in ds.ground_truth for tid in gt.txn_ids}
        planted_customers = {cid for gt in ds.ground_truth for cid in gt.customer_ids}
        benign_txns = [t for t in ds.transactions if t.txn_id not in planted_txns]
        benign_customers = [
            c for c in ds.customers if c.customer_id not in planted_customers
        ]
        result = run_detection(benign_txns, ds.accounts, benign_customers)
        noisy = [
            a for a in result.alerts if a.tier in (Severity.HIGH, Severity.CRITICAL)
        ]
        assert noisy == [], [a.narrative for a in noisy]


class TestCsvRoundTrip:
    def test_decimal_survives_round_trip(self, tmp_path):
        from aml_engine.models import read_transactions_csv

        ds = small_dataset()
        path = tmp_path / "txns.csv"
        ds.write_transactions_csv(path)
        loaded = read_transactions_csv(path)
        assert loaded == ds.transactions
