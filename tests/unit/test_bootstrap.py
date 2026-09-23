from pathlib import Path

import pytest

from banco_agil.models.domain import CreditRequest
from banco_agil.models.errors import RepositoryError
from banco_agil.repositories.bootstrap import initialize_demo_data, reset_demo_data
from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository

SOURCE = Path(__file__).parents[2] / "data"


def test_reset_demo_data_restores_customers_and_requests(tmp_path):
    initialize_demo_data(SOURCE, tmp_path)
    customers = CustomerRepository(tmp_path)
    customer = customers.require("00000000001")
    customer.limite_credito = 2000
    customer.score_credito = 900
    customers.save(customer)
    requests = CreditRequestRepository(tmp_path)
    requests.add(
        CreditRequest(
            cpf_cliente=customer.cpf,
            data_hora_solicitacao="2026-09-23T12:00:00Z",
            limite_atual=1000,
            novo_limite_solicitado=2000,
        )
    )

    reset_demo_data(SOURCE, tmp_path)

    restored = customers.require("00000000001")
    assert restored.limite_credito == 1000
    assert restored.score_credito == 400
    assert requests.read() == []


def test_reset_demo_data_preserves_unrelated_files(tmp_path):
    initialize_demo_data(SOURCE, tmp_path)
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("preservar", encoding="utf-8")

    reset_demo_data(SOURCE, tmp_path)

    assert unrelated.read_text(encoding="utf-8") == "preservar"


def test_invalid_later_seed_leaves_all_runtime_files_unchanged(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    initialize_demo_data(SOURCE, source)
    initialize_demo_data(SOURCE, target)
    customers = CustomerRepository(target)
    customer = customers.require("00000000001")
    customer.limite_credito = 2000
    customers.save(customer)
    original = {path.name: path.read_bytes() for path in target.iterdir()}
    (source / "solicitacoes_aumento_limite.csv").write_text("invalid", encoding="utf-8")
    with pytest.raises(RepositoryError):
        reset_demo_data(source, target)
    assert {path.name: path.read_bytes() for path in target.iterdir()} == original
