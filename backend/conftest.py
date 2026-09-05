"""conftest.py — configuration pytest globale du backend."""
import pytest


def pytest_configure(config):
    """Enregistre les marqueurs utilisés dans les tests unitaires internes."""
    config.addinivalue_line(
        "markers",
        "asyncio: marks async test functions to be run with pytest-asyncio",
    )
