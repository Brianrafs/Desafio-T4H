from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
CPF = Annotated[str, Field(pattern=r"^[0-9]{11}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CreditRequestStatus(StrEnum):
    PENDING = "pendente"
    APPROVED = "aprovado"
    REJECTED = "rejeitado"


class EmploymentType(StrEnum):
    FORMAL = "formal"
    SELF_EMPLOYED = "autonomo"
    UNEMPLOYED = "desempregado"


class SupportedCurrency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class Customer(Model):
    cpf: CPF
    nome: str = Field(min_length=1)
    data_nascimento: date
    limite_credito: Money
    score_credito: int = Field(ge=0, le=1000)


class ScoreRange(Model):
    score_min: int = Field(ge=0, le=1000)
    score_max: int = Field(ge=0, le=1000)
    limite_maximo: Money

    @model_validator(mode="after")
    def ordered(self):
        if self.score_min > self.score_max:
            raise ValueError("Faixa de score invertida")
        return self


class CreditRequest(Model):
    cpf_cliente: CPF
    data_hora_solicitacao: datetime
    limite_atual: Money
    novo_limite_solicitado: PositiveMoney
    status_pedido: CreditRequestStatus = CreditRequestStatus.PENDING


class FinancialProfile(Model):
    monthly_income: Money
    employment_type: EmploymentType
    fixed_expenses: Money
    dependents: int = Field(ge=0, strict=True)
    has_active_debt: bool = Field(strict=True)


class ExchangeRate(Model):
    currency: SupportedCurrency
    bid: Decimal = Field(gt=0, allow_inf_nan=False)
    quoted_at: datetime | None = None
