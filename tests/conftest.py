from pathlib import Path

import pytest

from banco_agil.repositories.bootstrap import initialize_demo_data


@pytest.fixture
def data_dir(tmp_path):
    initialize_demo_data(Path(__file__).parents[1] / "data", tmp_path)
    return tmp_path
