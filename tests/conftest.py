"""Shared fixtures: hand-built deterministic data for rule tests.

Rules are tested against explicit hand-crafted transactions, not generator
output, so rule tests stay independent of generator internals.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from aml_engine.models import (
    Account,
    BeneficialOwner,
    Channel,
    Customer,
    EntityType,
    Transaction,
    TxnType,
)
from aml_engine.rules import RuleContext

BASE_TS = datetime(2025, 3, 1, 10, 0, 0)


def make_txn(
    txn_id: str,
    *,
    amount: str,
    txn_type: TxnType = TxnType.CASH_DEPOSIT,
    account_id: str = "A1",
    customer_id: str = "C1",
    offset_hours: float = 0,
    channel: Channel = Channel.BRANCH,
    counterparty_account_id: str | None = None,
    originator_country: str = "US",
    beneficiary_country: str = "US",
) -> Transaction:
    return Transaction(
        txn_id=txn_id,
        timestamp=BASE_TS + timedelta(hours=offset_hours),
        account_id=account_id,
        customer_id=customer_id,
        txn_type=txn_type,
        channel=channel,
        amount=Decimal(amount),
        counterparty_account_id=counterparty_account_id,
        originator_country=originator_country,
        beneficiary_country=beneficiary_country,
    )


def make_customer(
    customer_id: str = "C1",
    *,
    business: bool = False,
    **overrides,
) -> Customer:
    defaults: dict = {
        "name": f"Customer {customer_id}",
        "entity_type": EntityType.LLC if business else EntityType.INDIVIDUAL,
        "country": "US",
        "onboarding_date": date(2020, 1, 15),
    }
    if business:
        defaults.update(
            registration_country="US",
            formation_date=date(2019, 6, 1),
            ownership_chain_depth=1,
            beneficial_owners=[BeneficialOwner("Jane Founder", 100.0)],
            has_physical_address=True,
            industry_code="CONSULTING",
        )
    defaults.update(overrides)
    return Customer(customer_id=customer_id, **defaults)


def make_account(account_id: str = "A1", customer_id: str = "C1") -> Account:
    return Account(
        account_id=account_id, customer_id=customer_id, opened_date=date(2020, 1, 15)
    )


def make_ctx(
    transactions: list[Transaction],
    customers: list[Customer] | None = None,
    accounts: list[Account] | None = None,
) -> RuleContext:
    if customers is None:
        customers = [make_customer(cid) for cid in {t.customer_id for t in transactions}]
    if accounts is None:
        pairs = {(t.account_id, t.customer_id) for t in transactions}
        accounts = [make_account(aid, cid) for aid, cid in pairs]
    return RuleContext(transactions=transactions, accounts=accounts, customers=customers)


@pytest.fixture
def clean_transactions() -> list[Transaction]:
    """Unremarkable activity that no rule should flag."""
    return [
        make_txn("T1", amount="1500.00", offset_hours=0),
        make_txn("T2", amount="320.50", txn_type=TxnType.CHECK, offset_hours=24),
        make_txn("T3", amount="2200.00", txn_type=TxnType.ACH, offset_hours=48),
        make_txn(
            "T4",
            amount="4000.00",
            txn_type=TxnType.WIRE_OUT,
            offset_hours=72,
            beneficiary_country="GB",
        ),
        make_txn("T5", amount="900.00", txn_type=TxnType.CASH_WITHDRAWAL, offset_hours=96),
    ]
