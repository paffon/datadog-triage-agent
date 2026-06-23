import datadog_triage_agent


def test_package_imports() -> None:
    assert datadog_triage_agent.__version__ == "0.1.0"
