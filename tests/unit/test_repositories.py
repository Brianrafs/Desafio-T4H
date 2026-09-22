from datetime import UTC, datetime
from decimal import Decimal

import pytest

from banco_agil.models.domain import CreditRequest
from banco_agil.models.errors import RepositoryError, ScoreRangeNotFoundError
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.repositories.score_range_repository import ScoreRangeRepository


def test_customer_updates(data_dir):
    repository = CustomerRepository(data_dir)
    customer = repository.require("00000000001")
    customer.score_credito = 600
    customer.limite_credito = Decimal("5000")
    repository.save(customer)
    assert repository.require(customer.cpf) == customer
    assert repository.find("00000000003") is None


def test_requests_preserve_history(data_dir):
    repository = CreditRequestRepository(data_dir)
    request = CreditRequest(
        cpf_cliente="00000000001",
        data_hora_solicitacao=datetime.now(UTC),
        limite_atual=1000,
        novo_limite_solicitado=4000,
    )
    repository.add(request)
    assert repository.read()[0].status_pedido == "pendente"
    request.status_pedido = "rejeitado"
    repository.save(request)
    assert repository.read()[0].status_pedido == "rejeitado"


def test_ranges(data_dir):
    repository = ScoreRangeRepository(data_dir)
    assert repository.for_score(499).limite_maximo == 2000
    assert repository.for_score(500).limite_maximo == 5000
    assert repository.for_score(1000).limite_maximo == 20000
    with pytest.raises(ScoreRangeNotFoundError):
        repository.for_score(1001)
    rows = repository.read()
    rows[1].score_min = 299
    repository.write(rows)
    with pytest.raises(RepositoryError):
        repository.read()


@pytest.mark.parametrize("contents", ["wrong\n", "cpf,nome\n1,Demo\n", "\xff"])
def test_malformed_csv(data_dir, contents):
    repository = CustomerRepository(data_dir)
    repository.path.write_bytes(contents.encode("latin-1"))
    with pytest.raises(RepositoryError):
        repository.read()


def test_missing_file(tmp_path):
    with pytest.raises(RepositoryError):
        CustomerRepository(tmp_path).read()


def test_atomic_write_failure_preserves_original(data_dir, monkeypatch):
    repository = CustomerRepository(data_dir)
    original = repository.path.read_bytes()
    rows = repository.read()
    rows[0].score_credito = 999

    def fail_replace(source, target):
        assert source.parent == target.parent
        raise OSError("Falha simulada")

    monkeypatch.setattr("banco_agil.repositories.csv_repository.os.replace", fail_replace)
    with pytest.raises(RepositoryError):
        repository.write(rows)
    assert repository.path.read_bytes() == original
    assert not list(data_dir.glob("*.tmp"))
