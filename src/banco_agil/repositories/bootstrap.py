from pathlib import Path

from banco_agil.repositories.credit_request_repository import CreditRequestRepository
from banco_agil.repositories.customer_repository import CustomerRepository
from banco_agil.repositories.score_range_repository import ScoreRangeRepository

REPOSITORY_TYPES = (CustomerRepository, ScoreRangeRepository, CreditRequestRepository)


def initialize_demo_data(source: Path, destination: Path) -> None:
    """Copia dados fictícios somente na primeira execução, preservando alterações."""
    destination.mkdir(parents=True, exist_ok=True)
    for repository in REPOSITORY_TYPES:
        target = repository(destination)
        if not target.path.exists():
            target.write(repository(source).read())
        target.read()


def reset_demo_data(source: Path, destination: Path) -> None:
    """Restaura somente os CSVs conhecidos, preservando outros arquivos."""
    validated = [(repository, repository(source).read()) for repository in REPOSITORY_TYPES]
    destination.mkdir(parents=True, exist_ok=True)
    for repository, rows in validated:
        repository(destination).write(rows)
