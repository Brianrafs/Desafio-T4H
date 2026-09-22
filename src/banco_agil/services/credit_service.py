from decimal import Decimal

from banco_agil.repositories.customer_repository import CustomerRepository


class CreditService:
    def __init__(self, customers: CustomerRepository):
        self.customers = customers

    def get_limit(self, authenticated_cpf: str) -> Decimal:
        return self.customers.require(authenticated_cpf).limite_credito
