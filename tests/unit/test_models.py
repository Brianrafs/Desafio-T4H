from decimal import Decimal

import pytest
from pydantic import ValidationError

from banco_agil.models.domain import Customer, FinancialProfile, ScoreRange
from banco_agil.models.state import CreditInterviewContext, SessionState


@pytest.mark.parametrize("limit", ["-1", "1.001", "NaN", "Infinity"])
def test_invalid_money(limit):
    with pytest.raises(ValidationError):
        Customer(
            cpf="00000000001",
            nome="Demo",
            data_nascimento="1990-01-01",
            limite_credito=limit,
            score_credito=500,
        )


def test_state_is_independent():
    first, second = SessionState(), SessionState()
    first.credit.requested_limit = Decimal("2000")
    assert second.credit.requested_limit is None
    assert first.id != second.id


def test_zero_and_false_are_collected_fields():
    context = CreditInterviewContext(
        monthly_income=0,
        employment_type="desempregado",
        fixed_expenses=0,
        dependents=0,
        has_active_debt=False,
    )
    assert context.is_complete()


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_invalid_dependents(value):
    with pytest.raises(ValidationError):
        FinancialProfile(
            monthly_income=0,
            employment_type="formal",
            fixed_expenses=0,
            dependents=value,
            has_active_debt=False,
        )


def test_reversed_score_range():
    with pytest.raises(ValidationError):
        ScoreRange(score_min=500, score_max=400, limite_maximo=1000)
