"""Keep the automated suite independent of local or inherited API credentials."""
import pytest


@pytest.fixture(autouse=True)
def isolate_openai_credentials(monkeypatch):
    # AppTest executes app.py, whose normal startup reloads the local .env.
    # python-dotenv 1.2.4 supports this flag and skips opening that file.
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
