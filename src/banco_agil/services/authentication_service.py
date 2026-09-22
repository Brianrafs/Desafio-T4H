import re
from datetime import date

from banco_agil.models.domain import Customer
from banco_agil.repositories.customer_repository import CustomerRepository


class AuthenticationService:
    def __init__(self, customers: CustomerRepository):
        self.customers = customers

    def authenticate(self, cpf: str, birth_date: date) -> Customer | None:
        normalized = re.sub(r"[.\-\s]", "", cpf)
        if not re.fullmatch(r"[0-9]{11}", normalized):
            return None
        customer = self.customers.find(normalized)
        if customer is not None and customer.data_nascimento == birth_date:
            return customer
        return None
