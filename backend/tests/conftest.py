import os
import sys
from pathlib import Path

import pytest

os.environ["PREDICTLAB_NO_PERSIST"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.synthetic import build_demo_dataset  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(scope="session")
def demo():
    return build_demo_dataset()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
