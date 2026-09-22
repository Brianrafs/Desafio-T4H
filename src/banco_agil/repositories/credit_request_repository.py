from pathlib import Path

from banco_agil.models.domain import CreditRequest
from banco_agil.models.errors import RepositoryError
from banco_agil.repositories.csv_repository import CsvRepository


class CreditRequestRepository(CsvRepository[CreditRequest]):
    def __init__(self, directory: Path):
        super().__init__(directory / "solicitacoes_aumento_limite.csv", CreditRequest)

    @staticmethod
    def key(request: CreditRequest):
        return request.cpf_cliente, request.data_hora_solicitacao

    def read(self) -> list[CreditRequest]:
        records = super().read()
        if len({self.key(row) for row in records}) != len(records):
            raise RepositoryError()
        return records

    def add(self, request: CreditRequest) -> None:
        records = self.read()
        if any(self.key(row) == self.key(request) for row in records):
            raise RepositoryError()
        self.write([*records, request])

    def save(self, request: CreditRequest) -> None:
        records = self.read()
        if not any(self.key(row) == self.key(request) for row in records):
            raise RepositoryError()
        self.write([request if self.key(row) == self.key(request) else row for row in records])
