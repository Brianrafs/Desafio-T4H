import pytest

from banco_agil.presentation import WELCOME, with_lia_voice


def test_lia_presents_capabilities_in_markdown():
    assert "**Lia**" in WELCOME
    assert "\n\n- **" in WELCOME
    for capability in ("Consultar", "aumento", "cotação"):
        assert capability in WELCOME


def test_contextual_acknowledgement_preserves_authoritative_body():
    body = "Seu limite é **R$ 1.000,00**."
    assert with_lia_voice(body, "Entendo sua dúvida, vamos olhar isso juntos.") == (
        "Entendo sua dúvida, vamos olhar isso juntos.\n\n" + body
    )


@pytest.mark.parametrize(
    "opening",
    [
        "Aprovei seu limite!",
        "Seu score é ótimo",
        "Entre em https://example.com",
        "Seu limite é R$ 9999",
        "Informe seu CPF",
        "Entendido, vamos aumentar seu limite.",
        "<script>alert()</script>",
    ],
)
def test_acknowledgement_cannot_replace_facts_or_ask_for_credentials(opening):
    assert with_lia_voice("Resultado confirmado pelo serviço.", opening) == (
        "Resultado confirmado pelo serviço."
    )


@pytest.mark.parametrize(
    "opening",
    [
        "Entendi.",
        "Certo!",
        "Perfeito.",
        "Claro.",
        "Vamos lá!",
        "Combinado.",
        "Vamos conferir isso juntos.",
    ],
)
def test_generic_acknowledgement_is_not_added_to_every_reply(opening):
    body = "Seu limite atual é **R$ 1.000,00**."

    assert with_lia_voice(body, opening) == body
