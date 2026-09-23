from pathlib import Path

from banco_agil.models.domain import ScoreRange
from banco_agil.models.errors import RepositoryError, ScoreRangeNotFoundError
from banco_agil.repositories.csv_repository import CsvRepository


class ScoreRangeRepository(CsvRepository[ScoreRange]):
    def __init__(self, directory: Path):
        super().__init__(directory / "score_limite.csv", ScoreRange)

    def read(self) -> list[ScoreRange]:
        ranges = sorted(super().read(), key=lambda row: row.score_min)
        if not ranges or ranges[0].score_min != 0 or ranges[-1].score_max != 1000:
            raise RepositoryError()
        if any(
            left.score_max + 1 != right.score_min
            for left, right in zip(ranges, ranges[1:], strict=False)
        ):
            raise RepositoryError()
        return ranges

    def for_score(self, score: int) -> ScoreRange:
        for row in self.read():
            if row.score_min <= score <= row.score_max:
                return row
        raise ScoreRangeNotFoundError()
