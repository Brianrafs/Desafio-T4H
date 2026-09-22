from pathlib import Path

from banco_agil.models.domain import Customer
from banco_agil.models.errors import RepositoryError
from banco_agil.repositories.csv_repository import CsvRepository


class CustomerRepository(CsvRepository[Customer]):
    def __init__(self, directory: Path):
        super().__init__(directory / "clientes.csv", Customer)

    def read(self) -> list[Customer]:
        customers = super().read()
        if len({customer.cpf for customer in customers}) != len(customers):
            raise RepositoryError()
        return customers

    def find(self, cpf: str) -> Customer | None:
        return next((customer for customer in self.read() if customer.cpf == cpf), None)

    def require(self, cpf: str) -> Customer:
        customer = self.find(cpf)
        if customer is None:
            raise RepositoryError()
        return customer

    def save(self, customer: Customer) -> None:
        customers = self.read()
        if not any(row.cpf == customer.cpf for row in customers):
            raise RepositoryError()
        self.write([customer if row.cpf == customer.cpf else row for row in customers])
