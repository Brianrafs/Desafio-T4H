import pytest
from pydantic import ValidationError

from banco_agil.models.responses import (
    CriticalFailure,
    FlowOutcome,
    GeneratedMessage,
    OutcomeDirective,
    RenderedResponse,
    ResponseBrief,
    ResponseDirective,
    ResponseEvent,
    ResponsePolicy,
    SafeConversationSummary,
)


def test_flow_outcome_requires_at_least_one_directive():
    with pytest.raises(ValidationError):
        FlowOutcome(
            directives=(),
            specialist="credit",
            protected_values={},
            next_step="idle",
        )


def test_generated_message_has_hard_length_limit():
    with pytest.raises(ValidationError):
        GeneratedMessage(text="x" * 701)


def test_response_event_contains_every_approved_event():
    assert {item.value for item in ResponseEvent} == {
        "welcome",
        "show_options",
        "request_cpf",
        "request_birth_date",
        "authentication_succeeded",
        "authentication_retry",
        "credit_limit_found",
        "request_credit_limit",
        "credit_increase_approved",
        "credit_increase_rejected_offer_interview",
        "credit_increase_rejected_final",
        "interview_started",
        "interview_question",
        "interview_reanalysis_approved",
        "interview_reanalysis_rejected",
        "request_currency",
        "exchange_quote_found",
        "unsupported_currency",
        "service_information",
        "resume_pending_step",
        "invalid_input",
        "conversation_closed",
    }


def test_outcome_directive_forbids_unknown_properties():
    with pytest.raises(ValidationError):
        OutcomeDirective(event="welcome", public_context={}, text="não permitido")


@pytest.mark.parametrize("expected_questions", [-1, 2])
def test_flow_outcome_rejects_invalid_question_count(expected_questions):
    with pytest.raises(ValidationError):
        FlowOutcome(
            directives=(OutcomeDirective(event="welcome"),),
            specialist="triage",
            next_step="idle",
            expected_questions=expected_questions,
        )


def test_flow_outcome_defaults_protected_values_and_question_count():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="welcome"),),
        specialist="triage",
        next_step="idle",
    )
    assert outcome.protected_values == {}
    assert outcome.expected_questions == 0


def test_response_brief_requires_at_least_one_directive():
    with pytest.raises(ValidationError):
        ResponseBrief(
            directives=(),
            specialist="triage",
            next_step="idle",
            expected_questions=0,
            user_tone="neutral",
        )


def test_response_brief_requires_current_specialist():
    with pytest.raises(ValidationError):
        ResponseBrief(
            directives=(
                ResponseDirective(event="show_options", communication_goal="Mostre opções"),
            ),
            next_step="idle",
            expected_questions=0,
            user_tone="neutral",
        )


def test_response_brief_preserves_structured_directives_and_defaults():
    brief = ResponseBrief(
        directives=(ResponseDirective(event="request_cpf", communication_goal="Pedir CPF"),),
        specialist="triage",
        next_step="await_cpf",
        expected_questions=1,
        user_tone="uncertain",
    )
    assert brief.directives[0].event is ResponseEvent.REQUEST_CPF
    assert brief.required_placeholders == frozenset()
    assert brief.allowed_actions == ()
    assert brief.user_tone.value == "uncertain"


@pytest.mark.parametrize("expected_questions", [-1, 2])
def test_response_policy_rejects_invalid_question_count(expected_questions):
    with pytest.raises(ValidationError):
        ResponsePolicy(expected_questions=expected_questions)


def test_response_policy_rejects_nonpositive_max_length():
    with pytest.raises(ValidationError):
        ResponsePolicy(expected_questions=0, max_length=0)


def test_generated_text_cannot_be_empty():
    with pytest.raises(ValidationError):
        GeneratedMessage(text="")


def test_rendered_text_cannot_be_empty():
    with pytest.raises(ValidationError):
        RenderedResponse(text="", used_fallback=False)


def test_safe_conversation_summary_requires_event():
    with pytest.raises(ValidationError):
        SafeConversationSummary(events=(), specialist="triage", next_step="idle")


def test_critical_failure_rejects_unknown_code():
    with pytest.raises(ValidationError):
        CriticalFailure(code="unknown_failure")
