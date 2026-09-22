from datetime import date

import pytest

from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.authentication_service import AuthenticationService


@pytest.mark.parametrize("cpf", ["00000000001", "000.000.000-01", " 000.000.000-01 "])
def test_authentication_normalizes_cpf(data_dir, cpf):
    service = AuthenticationService(CustomerRepository(data_dir))
    assert service.authenticate(cpf, date(1990, 1, 15)).cpf == "00000000001"


@pytest.mark.parametrize(
    "cpf,birth",
    [
        ("00000000001", date(2000, 1, 1)),
        ("00000000009", date(1990, 1, 15)),
        ("abc00000000001", date(1990, 1, 15)),
        ("1", date(1990, 1, 15)),
    ],
)
def test_invalid_credentials(data_dir, cpf, birth):
    service = AuthenticationService(CustomerRepository(data_dir))
    assert service.authenticate(cpf, birth) is None
