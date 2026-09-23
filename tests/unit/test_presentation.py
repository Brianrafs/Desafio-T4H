import pytest

from banco_agil.models.responses import FlowOutcome, OutcomeDirective, UserTone
from banco_agil.responses.briefs import build_response_brief
from banco_agil.responses.renderer import render_response


@pytest.mark.parametrize(
    "event,next_step,questions,expected",
    [
        ("welcome", "idle", 1, ("**Lia**", "Consultar", "aumento", "cotação")),
        ("show_options", "idle", 1, ("Consultar", "aumento", "cotação")),
        ("conversation_closed", "finished", 0, ("encerrada", "Nova conversa")),
    ],
)
def test_catalog_fallback_preserves_capabilities_and_closure(event, next_step, questions, expected):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event=event),),
        specialist="triage",
        next_step=next_step,
        expected_questions=questions,
    )
    response = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert response.used_fallback
    assert response.text.count("?") == questions
    for phrase in expected:
        assert phrase in response.text
