"""Projeção pública e sem valores protegidos de fatos decididos pelo Flow."""

from banco_agil.models.domain import InformationTopic
from banco_agil.models.responses import (
    FlowOutcome,
    NextStep,
    OutcomeDirective,
    ResponseBrief,
    ResponseDirective,
    ResponseEvent,
    SafeConversationSummary,
    UserTone,
)
from banco_agil.responses.catalog import (
    EVENT_DEFINITIONS,
    INFORMATION_TOPICS,
    INTERRUPTED_CREDIT_GOAL,
    INTERVIEW_FIELD_GUIDANCE,
)


def _public_context(
    outcome: FlowOutcome, directive: OutcomeDirective
) -> dict[str, str | int | bool]:
    if directive.event == ResponseEvent.SERVICE_INFORMATION:
        try:
            topic = InformationTopic(directive.public_context["topic"])
            if topic not in INFORMATION_TOPICS:
                raise ValueError("Tópico público inválido")
        except (KeyError, ValueError):
            raise ValueError("Tópico público inválido") from None
        return {"topic": topic.value}
    if directive.event == ResponseEvent.EXCHANGE_QUOTE_FOUND:
        interrupted = directive.public_context.get("credit_request_interrupted", False)
        if type(interrupted) is not bool:
            raise ValueError("Contexto público inválido")
        return {"credit_request_interrupted": True} if interrupted else {}
    if directive.event == ResponseEvent.INTERVIEW_QUESTION or (
        directive.event == ResponseEvent.RESUME_PENDING_STEP
        and outcome.next_step == NextStep.AWAIT_INTERVIEW_FIELD
    ):
        field = directive.public_context.get("field")
        if field not in INTERVIEW_FIELD_GUIDANCE:
            raise ValueError("Campo de entrevista inválido")
        return {"field": field, "field_guidance": INTERVIEW_FIELD_GUIDANCE[field]}
    return directive.public_context


def _response_directive(outcome: FlowOutcome, item: OutcomeDirective) -> ResponseDirective:
    context = _public_context(outcome, item)
    goal = EVENT_DEFINITIONS[item.event].communication_goal
    if item.event == ResponseEvent.SERVICE_INFORMATION:
        goal = INFORMATION_TOPICS[InformationTopic(context["topic"])].communication_goal
    if item.event == ResponseEvent.EXCHANGE_QUOTE_FOUND and context.get(
        "credit_request_interrupted"
    ):
        goal += " " + INTERRUPTED_CREDIT_GOAL
    return ResponseDirective(event=item.event, communication_goal=goal, public_context=context)


def build_response_brief(outcome: FlowOutcome, user_tone: UserTone) -> ResponseBrief:
    definitions = [EVENT_DEFINITIONS[item.event] for item in outcome.directives]
    return ResponseBrief(
        specialist=outcome.specialist,
        directives=tuple(_response_directive(outcome, item) for item in outcome.directives),
        required_placeholders=frozenset().union(
            *(item.policy.required_placeholders for item in definitions)
        ),
        allowed_placeholders=frozenset().union(
            *(item.policy.allowed_placeholders for item in definitions)
        )
        & outcome.protected_values.keys(),
        allowed_actions=tuple(
            dict.fromkeys(action for item in definitions for action in item.allowed_actions)
        ),
        next_step=outcome.next_step,
        expected_questions=outcome.expected_questions,
        user_tone=user_tone,
        constraints=tuple(dict.fromkeys(c for item in definitions for c in item.constraints)),
    )


def safe_summary(outcome: FlowOutcome, brief: ResponseBrief) -> SafeConversationSummary:
    return SafeConversationSummary(
        events=tuple(item.event for item in outcome.directives),
        specialist=outcome.specialist,
        actions_offered=brief.allowed_actions,
        next_step=outcome.next_step,
    )
