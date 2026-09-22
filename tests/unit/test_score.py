import pytest

from banco_agil.models.domain import FinancialProfile
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.credit_service import CreditService
from banco_agil.services.score_service import ScoreService


@pytest.mark.parametrize(
    "employment,dependents,debt,expected",
    [
        ("formal", 0, False, 530),
        ("autonomo", 1, False, 410),
        ("desempregado", 2, True, 0),
        ("formal", 7, True, 260),
    ],
)
def test_weights(employment, dependents, debt, expected):
    profile = FinancialProfile(
        monthly_income=1001,
        employment_type=employment,
        fixed_expenses=1000,
        dependents=dependents,
        has_active_debt=debt,
    )
    assert ScoreService.calculate(profile) == expected


def test_zero_expenses_and_upper_bound(data_dir):
    customers = CustomerRepository(data_dir)
    profile = FinancialProfile(
        monthly_income=10000,
        employment_type="formal",
        fixed_expenses=0,
        dependents=0,
        has_active_debt=False,
    )
    assert ScoreService(customers, CreditService(customers)).submit("00000000001", profile) == 1000
    assert customers.require("00000000001").score_credito == 1000
