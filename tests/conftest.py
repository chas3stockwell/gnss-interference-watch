"""Load each Lambda by file path so the shared ``handler.py`` name does not collide."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared" / "python"))


def load_handler(module_name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def planner():
    return load_handler("planner_handler", "collect/planner/handler.py")


@pytest.fixture(scope="session")
def reader():
    return load_handler("reader_handler", "collect/reader/handler.py")


@pytest.fixture(scope="session")
def detector():
    return load_handler("detector_handler", "detect/detector/handler.py")


@pytest.fixture(scope="session")
def request_handler():
    return load_handler("request_handler_mod", "detect/request_handler/handler.py")


@pytest.fixture(scope="session")
def cross_checker():
    return load_handler("cross_checker_handler", "alert-show/cross_checker/handler.py")


@pytest.fixture(scope="session")
def alert_api():
    return load_handler("alert_api_handler", "alert-show/api_handler/handler.py")
