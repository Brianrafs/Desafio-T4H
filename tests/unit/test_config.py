from banco_agil.config import Settings


def test_secrets_are_not_exposed(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "segredo-de-teste")
    settings = Settings(_env_file=None)
    assert settings.groq_api_key.get_secret_value() == "segredo-de-teste"
    assert "segredo-de-teste" not in repr(settings)
