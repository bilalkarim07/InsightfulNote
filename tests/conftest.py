import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that hit real external services")
    config.addinivalue_line("markers", "live: marks tests that require network access")