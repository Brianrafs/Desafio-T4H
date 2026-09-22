import csv
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from banco_agil.models.domain import Model
from banco_agil.models.errors import RepositoryError


class CsvRepository[T: Model]:
    def __init__(self, path: Path, model: type[T]):
        self.path, self.model = path, model

    def read(self) -> list[T]:
        try:
            with self.path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if reader.fieldnames != list(self.model.model_fields):
                    raise ValueError("Cabeçalho inválido")
                return [self.model.model_validate(row) for row in reader]
        except (OSError, ValueError, csv.Error, ValidationError) as exc:
            raise RepositoryError() from exc

    def write(self, records: list[T]) -> None:
        temporary = None
        try:
            validated = [self.model.model_validate(row.model_dump()) for row in records]
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                writer = csv.DictWriter(stream, fieldnames=list(self.model.model_fields))
                writer.writeheader()
                writer.writerows(row.model_dump(mode="json") for row in validated)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError, csv.Error, ValidationError) as exc:
            raise RepositoryError() from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
