import pytest

from banco_agil.models.errors import RepositoryError
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.services.credit_service import CreditService


def test_get_limit(data_dir):
    assert CreditService(CustomerRepository(data_dir)).get_limit("00000000001") == 1000


def test_unknown_customer(data_dir):
    with pytest.raises(RepositoryError):
        CreditService(CustomerRepository(data_dir)).get_limit("00000000099")
