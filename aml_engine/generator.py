"""Seeded synthetic data generator with planted suspicious scenarios.

All randomness flows through a single ``random.Random(seed)`` instance —
never the module-level ``random`` functions — so a given seed always
produces a byte-identical dataset. Each planted scenario returns a
:class:`GroundTruth` record naming the transactions involved and the rule
IDs expected to fire; ground truth is kept apart from the data handed to
detection so evaluation stays honest.

Benign traffic is shaped to give the rules true negatives to ignore:
ordinary cash deposits are kept clear of the structuring band, and a few
legitimate foreign wires go to non-listed countries.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from aml_engine.models import (
    Account,
    BeneficialOwner,
    Channel,
    Customer,
    Dataset,
    EntityType,
    GroundTruth,
    Transaction,
    TxnType,
)

FIRST_NAMES = [
    "James", "Maria", "Robert", "Linda", "Michael", "Sara", "David", "Karen",
    "Daniel", "Nancy", "Kevin", "Amara", "Luis", "Elena", "Samuel", "Ruth",
    "Tesfay", "Selam", "Omar", "Priya", "Chen", "Fatima", "Yosef", "Hana",
]
LAST_NAMES = [
    "Smith", "Johnson", "Garcia", "Nguyen", "Patel", "Kim", "Hernandez",
    "Brown", "Davis", "Martinez", "Lopez", "Wilson", "Anderson", "Taylor",
    "Gebremedhin", "Haile", "Ali", "Khan", "Chen", "Okafor", "Mensah",
]
BUSINESS_STEMS = [
    "Lonestar", "Trinity", "Metroplex", "BlueBonnet", "Prairie", "Summit",
    "Crescent", "Pinnacle", "Heritage", "Frontier", "Cedar", "Maverick",
]
BUSINESS_SUFFIXES = {
    EntityType.LLC: "LLC",
    EntityType.CORP: "Inc.",
    EntityType.TRUST: "Trust",
    EntityType.PARTNERSHIP: "LP",
    EntityType.MSB: "Money Services",
}
INDUSTRIES = [
    "RETAIL", "RESTAURANT", "CONSULTING", "CONSTRUCTION", "HEALTHCARE",
    "LOGISTICS", "REAL_ESTATE", "IMPORT_EXPORT", "MSB",
]
#: Countries used for benign foreign wires — deliberately not on any OFAC,
#: FATF, or secrecy-haven list so they exercise the rules' true negatives.
BENIGN_FOREIGN = ["CA", "GB", "DE", "MX", "JP", "FR", "AU", "IN", "BR", "KR"]
MERCHANTS = [
    "HEB Grocery", "Shell Oil", "Home Depot", "Amazon Marketplace",
    "Southwest Airlines", "AT&T", "Oncor Energy", "Kroger", "Costco",
]
EMPLOYERS = [
    "Lakeside ISD Payroll", "Baylor Health Payroll", "City of Dallas Payroll",
    "TXU Energy Payroll", "Pinnacle Logistics Payroll",
]


def _cents(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class _Builder:
    """Mutable state threaded through generation: rng, id counters, output."""

    def __init__(self, seed: int, days: int) -> None:
        self.rng = random.Random(seed)
        self.end_date = date(2025, 3, 31)  # fixed anchor keeps output stable
        self.start_date = self.end_date - timedelta(days=days)
        self.customers: list[Customer] = []
        self.accounts: list[Account] = []
        self.transactions: list[Transaction] = []
        self.ground_truth: list[GroundTruth] = []
        self._counters = {"C": 0, "A": 0, "T": 0, "S": 0}

    def next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}{self._counters[prefix]:06d}"

    def random_ts(self, day: date) -> datetime:
        return datetime(
            day.year, day.month, day.day,
            self.rng.randint(8, 19), self.rng.randint(0, 59), self.rng.randint(0, 59),
        )

    def random_day(self, first: date | None = None, last: date | None = None) -> date:
        first = first or self.start_date
        last = last or self.end_date
        return first + timedelta(days=self.rng.randint(0, (last - first).days))

    def add_customer(self, *, business: bool = False, **overrides) -> Customer:
        if business:
            entity_type = overrides.pop(
                "entity_type",
                self.rng.choice([EntityType.LLC, EntityType.CORP, EntityType.PARTNERSHIP]),
            )
            name = overrides.pop(
                "name",
                f"{self.rng.choice(BUSINESS_STEMS)} "
                f"{self.rng.choice(['Trading', 'Holdings', 'Services', 'Group', 'Ventures'])} "
                f"{BUSINESS_SUFFIXES[entity_type]}",
            )
            owners = overrides.pop(
                "beneficial_owners",
                [
                    BeneficialOwner(
                        owner_name=f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}",
                        ownership_pct=float(self.rng.choice([100.0, 60.0, 51.0, 40.0])),
                    )
                ],
            )
            customer = Customer(
                customer_id=self.next_id("C"),
                name=name,
                entity_type=entity_type,
                country=overrides.pop("country", "US"),
                onboarding_date=overrides.pop(
                    "onboarding_date", self.random_day(self.start_date - timedelta(days=1500))
                ),
                registration_country=overrides.pop("registration_country", "US"),
                formation_date=overrides.pop(
                    "formation_date", self.random_day(self.start_date - timedelta(days=2000))
                ),
                ownership_chain_depth=overrides.pop("ownership_chain_depth", 1),
                beneficial_owners=owners,
                has_physical_address=overrides.pop("has_physical_address", True),
                industry_code=overrides.pop("industry_code", self.rng.choice(INDUSTRIES)),
            )
        else:
            customer = Customer(
                customer_id=self.next_id("C"),
                name=overrides.pop(
                    "name", f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"
                ),
                entity_type=EntityType.INDIVIDUAL,
                country=overrides.pop("country", "US"),
                onboarding_date=overrides.pop(
                    "onboarding_date", self.random_day(self.start_date - timedelta(days=3000))
                ),
            )
        assert not overrides, f"unused overrides: {overrides}"
        self.customers.append(customer)
        return customer

    def add_account(self, customer: Customer) -> Account:
        account = Account(
            account_id=self.next_id("A"),
            customer_id=customer.customer_id,
            opened_date=customer.onboarding_date,
            account_type="business" if customer.is_business else "checking",
        )
        self.accounts.append(account)
        return account

    def add_txn(self, **kwargs) -> Transaction:
        txn = Transaction(txn_id=self.next_id("T"), **kwargs)
        self.transactions.append(txn)
        return txn

    def new_scenario_id(self) -> str:
        return self.next_id("S")


# ---------------------------------------------------------------------------
# Benign traffic
# ---------------------------------------------------------------------------

def _generate_benign(b: _Builder, account: Account, customer: Customer) -> None:
    rng = b.rng
    n_txns = rng.randint(15, 35)
    for _ in range(n_txns):
        day = b.random_day()
        kind = rng.random()
        if kind < 0.30:  # salary / recurring ACH credit
            b.add_txn(
                timestamp=b.random_ts(day),
                account_id=account.account_id,
                customer_id=customer.customer_id,
                txn_type=TxnType.ACH,
                channel=Channel.ONLINE,
                amount=_cents(rng.uniform(800, 4500)),
                counterparty_name=rng.choice(EMPLOYERS),
                memo="payroll" if not customer.is_business else "receivable",
            )
        elif kind < 0.55:  # card-settled / check spending
            b.add_txn(
                timestamp=b.random_ts(day),
                account_id=account.account_id,
                customer_id=customer.customer_id,
                txn_type=TxnType.CHECK,
                channel=Channel.ONLINE,
                amount=_cents(rng.uniform(20, 1200)),
                counterparty_name=rng.choice(MERCHANTS),
                memo="payment",
            )
        elif kind < 0.78:  # ordinary cash activity, clear of the band
            deposit = rng.random() < 0.6
            # Benign cash stays under $5,000 — comfortably outside the
            # $7,000–$9,999.99 structuring band by construction.
            b.add_txn(
                timestamp=b.random_ts(day),
                account_id=account.account_id,
                customer_id=customer.customer_id,
                txn_type=TxnType.CASH_DEPOSIT if deposit else TxnType.CASH_WITHDRAWAL,
                channel=rng.choice([Channel.BRANCH, Channel.ATM]),
                amount=_cents(rng.uniform(40, 4800)),
                memo="cash",
            )
        elif kind < 0.92:  # domestic wire
            outbound = rng.random() < 0.5
            b.add_txn(
                timestamp=b.random_ts(day),
                account_id=account.account_id,
                customer_id=customer.customer_id,
                txn_type=TxnType.WIRE_OUT if outbound else TxnType.WIRE_IN,
                channel=Channel.ONLINE,
                amount=_cents(rng.uniform(500, 18000)),
                counterparty_name=f"{rng.choice(LAST_NAMES)} {rng.choice(['Escrow', 'Title Co', 'Suppliers', 'Realty'])}",
                memo="wire",
            )
        else:  # legitimate foreign wire to a non-listed country
            country = rng.choice(BENIGN_FOREIGN)
            outbound = rng.random() < 0.5
            b.add_txn(
                timestamp=b.random_ts(day),
                account_id=account.account_id,
                customer_id=customer.customer_id,
                txn_type=TxnType.WIRE_OUT if outbound else TxnType.WIRE_IN,
                channel=Channel.ONLINE,
                amount=_cents(rng.uniform(300, 9000)),
                counterparty_name=f"{rng.choice(LAST_NAMES)} {rng.choice(['Ltd', 'GmbH', 'SA'])}",
                originator_country="US" if outbound else country,
                beneficiary_country=country if outbound else "US",
                memo="intl wire",
            )


# ---------------------------------------------------------------------------
# Scenario injectors — each returns a GroundTruth record
# ---------------------------------------------------------------------------

def inject_structuring(b: _Builder) -> GroundTruth:
    """3–6 cash deposits of $8,200–$9,700 into one account over 2–3 days."""
    customer = b.add_customer()
    account = b.add_account(customer)
    start = b.random_day(last=b.end_date - timedelta(days=5))
    n_deposits = b.rng.randint(4, 6)
    txn_ids = []
    for i in range(n_deposits):
        day = start + timedelta(days=b.rng.randint(0, 2))
        txn = b.add_txn(
            timestamp=b.random_ts(day),
            account_id=account.account_id,
            customer_id=customer.customer_id,
            txn_type=TxnType.CASH_DEPOSIT,
            channel=Channel.BRANCH,
            amount=_cents(b.rng.uniform(8200, 9700)),
            memo="cash deposit",
        )
        txn_ids.append(txn.txn_id)
    return GroundTruth(
        scenario_id=b.new_scenario_id(),
        pattern_name="structuring",
        customer_ids=[customer.customer_id],
        txn_ids=txn_ids,
        expected_rule_ids=["R-STRUCT-001"],
    )


def inject_smurfing(b: _Builder) -> GroundTruth:
    """Five originators funnel sub-$10k transfers to one beneficiary in 5 days."""
    beneficiary = b.add_customer()
    funnel = b.add_account(beneficiary)
    start = b.random_day(last=b.end_date - timedelta(days=7))
    txn_ids = []
    customer_ids = [beneficiary.customer_id]
    for _ in range(5):
        originator = b.add_customer()
        orig_account = b.add_account(originator)
        customer_ids.append(originator.customer_id)
        day = start + timedelta(days=b.rng.randint(0, 4))
        txn = b.add_txn(
            timestamp=b.random_ts(day),
            account_id=orig_account.account_id,
            customer_id=originator.customer_id,
            txn_type=TxnType.WIRE_OUT,
            channel=Channel.BRANCH,
            amount=_cents(b.rng.uniform(4000, 9000)),
            counterparty_name=beneficiary.name,
            counterparty_account_id=funnel.account_id,
            memo="transfer",
        )
        txn_ids.append(txn.txn_id)
    return GroundTruth(
        scenario_id=b.new_scenario_id(),
        pattern_name="smurfing",
        customer_ids=customer_ids,
        txn_ids=txn_ids,
        expected_rule_ids=["R-STRUCT-003"],
    )


def inject_ofac_wire(b: _Builder, country: str, expected_rule: str) -> GroundTruth:
    """One outbound wire whose beneficiary sits in a sanctioned jurisdiction."""
    customer = b.add_customer()
    account = b.add_account(customer)
    txn = b.add_txn(
        timestamp=b.random_ts(b.random_day()),
        account_id=account.account_id,
        customer_id=customer.customer_id,
        txn_type=TxnType.WIRE_OUT,
        channel=Channel.ONLINE,
        amount=_cents(b.rng.uniform(5000, 60000)),
        counterparty_name=f"{b.rng.choice(LAST_NAMES)} Trading Co",
        originator_country="US",
        beneficiary_country=country,
        memo="intl wire",
    )
    return GroundTruth(
        scenario_id=b.new_scenario_id(),
        pattern_name="ofac_wire",
        customer_ids=[customer.customer_id],
        txn_ids=[txn.txn_id],
        expected_rule_ids=[expected_rule],
    )


def inject_greylist_corridor(b: _Builder) -> GroundTruth:
    """Four wires to one FATF greylist country within three weeks."""
    customer = b.add_customer()
    account = b.add_account(customer)
    country = b.rng.choice(["NG", "VN", "KE", "LB"])
    start = b.random_day(last=b.end_date - timedelta(days=21))
    txn_ids = []
    for i in range(4):
        day = start + timedelta(days=b.rng.randint(i * 4, i * 4 + 3))
        txn = b.add_txn(
            timestamp=b.random_ts(day),
            account_id=account.account_id,
            customer_id=customer.customer_id,
            txn_type=TxnType.WIRE_OUT,
            channel=Channel.ONLINE,
            amount=_cents(b.rng.uniform(3000, 14000)),
            counterparty_name=f"{b.rng.choice(LAST_NAMES)} Imports",
            originator_country="US",
            beneficiary_country=country,
            memo="trade payment",
        )
        txn_ids.append(txn.txn_id)
    return GroundTruth(
        scenario_id=b.new_scenario_id(),
        pattern_name="greylist_corridor",
        customer_ids=[customer.customer_id],
        txn_ids=txn_ids,
        expected_rule_ids=["R-JURIS-003"],
    )


def inject_shell_passthrough(b: _Builder) -> GroundTruth:
    """Secrecy-haven shell with nominee owner doing round-dollar pass-throughs.

    Deliberately trips several beneficial-ownership rules at once to
    exercise customer-level score aggregation.
    """
    registration = b.rng.choice(["VG", "PA", "KY"])
    shell = b.add_customer(
        business=True,
        entity_type=EntityType.LLC,
        name=f"{b.rng.choice(BUSINESS_STEMS)} Global Holdings LLC",
        registration_country=registration,
        ownership_chain_depth=4,
        beneficial_owners=[
            BeneficialOwner(
                owner_name=f"{b.rng.choice(FIRST_NAMES)} {b.rng.choice(LAST_NAMES)}",
                ownership_pct=15.0,
                is_nominee=True,
                country=registration,
            )
        ],
        has_physical_address=False,
        industry_code="IMPORT_EXPORT",
        onboarding_date=b.end_date - timedelta(days=b.rng.randint(30, 80)),
    )
    account = b.add_account(shell)
    start = b.random_day(
        first=b.start_date + timedelta(days=5), last=b.end_date - timedelta(days=20)
    )
    txn_ids = []
    for i in range(b.rng.randint(2, 3)):
        in_day = start + timedelta(days=i * 7)
        amount = Decimal(b.rng.randrange(20, 90)) * Decimal("1000")
        wire_in = b.add_txn(
            timestamp=b.random_ts(in_day),
            account_id=account.account_id,
            customer_id=shell.customer_id,
            txn_type=TxnType.WIRE_IN,
            channel=Channel.ONLINE,
            amount=amount,
            counterparty_name=f"{b.rng.choice(BUSINESS_STEMS)} Capital Partners",
            memo="invoice settlement",
        )
        wire_out = b.add_txn(
            timestamp=b.random_ts(in_day + timedelta(days=1)),
            account_id=account.account_id,
            customer_id=shell.customer_id,
            txn_type=TxnType.WIRE_OUT,
            channel=Channel.ONLINE,
            amount=amount,
            counterparty_name=f"{b.rng.choice(BUSINESS_STEMS)} Distribution LLC",
            memo="invoice settlement",
        )
        txn_ids.extend([wire_in.txn_id, wire_out.txn_id])
    return GroundTruth(
        scenario_id=b.new_scenario_id(),
        pattern_name="shell_passthrough",
        customer_ids=[shell.customer_id],
        txn_ids=txn_ids,
        expected_rule_ids=["R-BO-001", "R-BO-002", "R-BO-003", "R-BO-004"],
    )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def generate_dataset(
    seed: int = 42,
    n_customers: int = 200,
    days: int = 90,
) -> Dataset:
    """Generate a reproducible synthetic dataset with planted scenarios."""
    b = _Builder(seed=seed, days=days)

    # Benign population. ~15% small businesses with clean ownership records.
    for _ in range(n_customers):
        business = b.rng.random() < 0.15
        customer = b.add_customer(business=business)
        account = b.add_account(customer)
        _generate_benign(b, account, customer)

    # Planted suspicious scenarios.
    for _ in range(3):
        b.ground_truth.append(inject_structuring(b))
    b.ground_truth.append(inject_smurfing(b))
    b.ground_truth.append(inject_ofac_wire(b, "IR", "R-JURIS-001"))
    b.ground_truth.append(inject_ofac_wire(b, "KP", "R-JURIS-001"))
    b.ground_truth.append(inject_ofac_wire(b, "RU", "R-JURIS-001"))
    b.ground_truth.append(inject_greylist_corridor(b))
    for _ in range(2):
        b.ground_truth.append(inject_shell_passthrough(b))

    b.transactions.sort(key=lambda t: (t.timestamp, t.txn_id))
    return Dataset(
        customers=b.customers,
        accounts=b.accounts,
        transactions=b.transactions,
        ground_truth=b.ground_truth,
    )
