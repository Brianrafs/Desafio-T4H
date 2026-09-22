from banco_agil.models.domain import EmploymentType, FinancialProfile
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.credit_service import CreditService


class ScoreService:
    def __init__(self, customers: CustomerRepository, credit: CreditService):
        self.customers, self.credit = customers, credit

    @staticmethod
    def calculate(profile: FinancialProfile) -> int:
        employment = {
            EmploymentType.FORMAL: 300,
            EmploymentType.SELF_EMPLOYED: 200,
            EmploymentType.UNEMPLOYED: 0,
        }[profile.employment_type]
        dependents = (100, 80, 60, 30)[min(profile.dependents, 3)]
        debt = -100 if profile.has_active_debt else 100
        raw = profile.monthly_income / (profile.fixed_expenses + 1) * 30
        return min(1000, max(0, round(raw + employment + dependents + debt)))

    def submit(self, cpf: str, profile: FinancialProfile) -> int:
        self.credit.recover_pending(cpf)
        customer = self.customers.require(cpf)
        customer.score_credito = self.calculate(profile)
        self.customers.save(customer)
        return customer.score_credito
