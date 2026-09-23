"""Validação local de mensagens antes de interpolar dados confirmados."""

import re
from collections import Counter

from banco_agil.models.domain import InformationTopic
from banco_agil.models.responses import (
    FallbackReason,
    FlowOutcome,
    GeneratedMessage,
    NextStep,
    OutcomeDirective,
    RenderedResponse,
    ResponseAction,
    ResponseBrief,
    ResponseEvent,
    ResponsePolicy,
)
from banco_agil.responses.catalog import (
    EVENT_DEFINITIONS,
    EVENT_QUESTION_SUBJECT,
    INFORMATION_TOPICS,
    INTERRUPTED_CREDIT_FALLBACK,
    INTERVIEW_QUESTIONS,
    INVALID_INPUT_STATEMENT,
    PENDING_QUESTIONS,
    QUESTION_SUBJECTS,
    SENSITIVE_QUESTION_SUBJECTS,
    STEP_QUESTION_SUBJECT,
    EventDefinition,
)

PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
FINANCIAL_LITERAL_PATTERN = re.compile(
    r"[$€£¥%]|\bpor\s+cento\b|"
    r"\b(?:zero|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|"
    r"onze|doze|treze|catorze|quatorze|quinze|dezesseis|dezessete|dezoito|dezenove|"
    r"vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|"
    r"duzent[oa]s|trezent[oa]s|quatrocent[oa]s|quinhent[oa]s|seiscent[oa]s|"
    r"setecent[oa]s|oitocent[oa]s|novecent[oa]s|mil|milhão|milhões|bilhão|bilhões)"
    r"\s+(?:de\s+)?(?:reais|real|centavos?|d[oó]lares?|euros?|libras?|ienes?|usd|eur|gbp)\b",
    re.IGNORECASE,
)
UNSAFE_LITERAL_PATTERN = re.compile(r"https?://|www\.|(?<!\d)\d{11}(?!\d)", re.IGNORECASE)
INTERVIEW_OFFER_PATTERN = re.compile(
    r"\b(?:podemos|posso|ofere[cç]\w*|inici\w*|come[cç]\w*|faça|fazer|vamos)\b"
    r"[^.!?\n]*\bentrevista\b|"
    r"\b(?:nova|outra)\s+entrevista\b|"
    r"\bentrevista\b[^.!?\n]*\bdispon[ií]vel\b",
    re.IGNORECASE,
)
CREDENTIAL_PATTERN = re.compile(
    r"\b(?:senhas?|tokens?|pins?|logins?|credencia(?:l|is)|cvv|cvc|"
    r"palavra[- ]passe|chave\s+de\s+acesso)\b",
    re.IGNORECASE,
)
DATA_REQUEST_PATTERN = re.compile(
    r"\b(?:informe|envie|diga|responda|insira|conte|digite|compartilhe|forneça|"
    r"apresente|confirme|passe|mande|preciso|necessári[oa])\b",
    re.IGNORECASE,
)


def _public_number_patterns(outcome: FlowOutcome) -> tuple[str, ...]:
    """Autoriza contadores públicos no seu contexto, nunca valores isolados."""
    patterns = []
    for directive in outcome.directives:
        event, context = directive.event, directive.public_context
        if event == ResponseEvent.AUTHENTICATION_RETRY:
            remaining = context.get("remaining_attempts")
            if type(remaining) is int and 0 < remaining < 3:
                patterns.extend(
                    (
                        rf"\b{remaining}\s+tentativas?\b",
                        rf"\btentativas?\s+restantes?\s*:\s*{remaining}\b",
                    )
                )
        if event == ResponseEvent.INTERVIEW_QUESTION or (
            event == ResponseEvent.RESUME_PENDING_STEP
            and outcome.next_step == NextStep.AWAIT_INTERVIEW_FIELD
        ):
            if context.get("field") == "dependents":
                patterns.append(r"\b(?:diga|informe|responda)\s+0\b")
        if event == ResponseEvent.INTERVIEW_STARTED or (
            event == ResponseEvent.SERVICE_INFORMATION
            and context.get("topic") == InformationTopic.CREDIT_INTERVIEW
        ):
            patterns.append(r"\b5\s+perguntas\b")
    return tuple(patterns)


def _validate_template(
    text: str,
    required: frozenset[str],
    allowed: frozenset[str],
    expected_questions: int,
    policies: tuple[ResponsePolicy, ...],
    *,
    exact_questions: bool = False,
    public_number_patterns: tuple[str, ...] = (),
) -> FallbackReason | None:
    markers = PLACEHOLDER_PATTERN.findall(text)
    if any(marker not in allowed for marker in markers):
        return FallbackReason.UNKNOWN_PLACEHOLDER
    if not required.issubset(markers):
        return FallbackReason.MISSING_PLACEHOLDER
    if any(count > 1 for count in Counter(markers).values()):
        return FallbackReason.POLICY_REJECTED
    without_markers = PLACEHOLDER_PATTERN.sub("", text)
    if "{" in without_markers or "}" in without_markers or "\\{{" in text:
        return FallbackReason.POLICY_REJECTED
    question_count = text.count("?")
    if question_count > min(expected_questions, 1) or (
        exact_questions and question_count != expected_questions
    ):
        return FallbackReason.POLICY_REJECTED
    if len(text) > min(policy.max_length for policy in policies):
        return FallbackReason.POLICY_REJECTED
    plain_text = without_markers.replace("*", "")
    if FINANCIAL_LITERAL_PATTERN.search(plain_text):
        return FallbackReason.POLICY_REJECTED
    without_public_numbers = plain_text
    for pattern in public_number_patterns:
        without_public_numbers = re.sub(pattern, "", without_public_numbers, flags=re.IGNORECASE)
    if any(character.isnumeric() for character in without_public_numbers):
        return FallbackReason.POLICY_REJECTED
    if UNSAFE_LITERAL_PATTERN.search(without_markers):
        return FallbackReason.POLICY_REJECTED
    if any(
        re.search(pattern, plain_text, re.IGNORECASE)
        for policy in policies
        for pattern in policy.forbidden_patterns
    ):
        return FallbackReason.POLICY_REJECTED
    if any(
        not re.search(pattern, plain_text, re.IGNORECASE)
        for policy in policies
        for pattern in policy.required_patterns
    ):
        return FallbackReason.POLICY_REJECTED
    return None


def _fallback_for(directive: OutcomeDirective, next_step: NextStep) -> str:
    event = directive.event
    context = directive.public_context
    if (
        event == ResponseEvent.EXCHANGE_QUOTE_FOUND
        and context.get("credit_request_interrupted") is True
    ):
        return EVENT_DEFINITIONS[event].fallback + "\n\n" + INTERRUPTED_CREDIT_FALLBACK
    if event == ResponseEvent.SERVICE_INFORMATION:
        try:
            return INFORMATION_TOPICS[InformationTopic(context.get("topic"))].fallback
        except (ValueError, KeyError):
            raise ValueError("Contexto público inválido") from None
    if event == ResponseEvent.INTERVIEW_QUESTION:
        try:
            return INTERVIEW_QUESTIONS[context.get("field")]
        except KeyError:
            raise ValueError("Contexto público inválido") from None
    if event == ResponseEvent.RESUME_PENDING_STEP:
        if next_step == NextStep.AWAIT_INTERVIEW_FIELD:
            try:
                return INTERVIEW_QUESTIONS[context.get("field")]
            except KeyError:
                raise ValueError("Contexto público inválido") from None
        try:
            return PENDING_QUESTIONS[next_step]
        except KeyError:
            raise ValueError("Contexto público inválido") from None
    if event == ResponseEvent.AUTHENTICATION_RETRY:
        remaining = context.get("remaining_attempts")
        if type(remaining) is int and 0 < remaining < 3:
            return EVENT_DEFINITIONS[event].fallback + f"\n\nTentativas restantes: **{remaining}**."
    return EVENT_DEFINITIONS[event].fallback


def _interpolate(template: str, protected_values: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        value = protected_values.get(match.group(1))
        if value is None:
            raise ValueError("Valor protegido ausente")
        return value

    return PLACEHOLDER_PATTERN.sub(substitute, template)


def _authorized_question_subject(outcome: FlowOutcome) -> frozenset[str]:
    for directive in reversed(outcome.directives):
        if directive.event == ResponseEvent.RESUME_PENDING_STEP:
            if outcome.next_step == NextStep.AWAIT_INTERVIEW_FIELD:
                field = directive.public_context.get("field")
                return frozenset({field}) if field in INTERVIEW_QUESTIONS else frozenset()
            subject = STEP_QUESTION_SUBJECT.get(outcome.next_step)
            return frozenset({subject}) if subject else frozenset()
        if directive.event == ResponseEvent.INTERVIEW_QUESTION:
            field = directive.public_context.get("field")
            return frozenset({field}) if field in INTERVIEW_QUESTIONS else frozenset()
        if directive.event == ResponseEvent.AUTHENTICATION_RETRY:
            return frozenset({"cpf", "birth_date"})
        subject = EVENT_QUESTION_SUBJECT.get(directive.event)
        if subject:
            if directive.event == ResponseEvent.EXCHANGE_QUOTE_FOUND:
                return frozenset({subject, "requested_limit"})
            return frozenset({subject})
    return frozenset()


def _question_is_authorized(text: str, outcome: FlowOutcome) -> bool:
    if CREDENTIAL_PATTERN.search(text):
        return False
    subjects = _authorized_question_subject(outcome)
    if any(item.event == ResponseEvent.INTERVIEW_QUESTION for item in outcome.directives) and any(
        re.search(QUESTION_SUBJECTS[subject], text, re.IGNORECASE)
        for subject in SENSITIVE_QUESTION_SUBJECTS - subjects
    ):
        return False
    clauses = re.split(r"(?<=[.!?])\s+|\n+", text)
    for clause in clauses:
        if "?" not in clause and not DATA_REQUEST_PATTERN.search(clause):
            continue
        if re.search(r"\bc[oó]digos?\b", clause, re.IGNORECASE):
            return False
        if any(
            re.search(QUESTION_SUBJECTS[subject], clause, re.IGNORECASE)
            for subject in SENSITIVE_QUESTION_SUBJECTS - subjects
        ):
            return False
        if "?" in clause and (
            not subjects
            or not any(
                re.search(QUESTION_SUBJECTS[subject], clause, re.IGNORECASE) for subject in subjects
            )
        ):
            return False
    return True


def _required_markers_follow_directives(
    text: str, definitions: tuple[EventDefinition, ...]
) -> bool:
    positions = {match.group(1): match.start() for match in PLACEHOLDER_PATTERN.finditer(text)}
    previous_end = -1
    for definition in definitions:
        event_positions = [positions[name] for name in definition.policy.required_placeholders]
        if event_positions:
            if min(event_positions) < previous_end:
                return False
            previous_end = max(event_positions)
    return True


def _interview_offer_is_authorized(text: str, definitions: tuple[EventDefinition, ...]) -> bool:
    allowed = any(
        ResponseAction.START_CREDIT_INTERVIEW in definition.allowed_actions
        for definition in definitions
    )
    return allowed or INTERVIEW_OFFER_PATTERN.search(text) is None


def render_response(
    outcome: FlowOutcome,
    brief: ResponseBrief,
    generated: GeneratedMessage | None,
    fallback_reason: FallbackReason | None = None,
) -> RenderedResponse:
    """Rejeita texto inseguro; valida fallbacks locais antes de resolver valores."""
    if (
        tuple(item.event for item in outcome.directives)
        != tuple(item.event for item in brief.directives)
        or brief.next_step != outcome.next_step
        or brief.expected_questions != outcome.expected_questions
    ):
        raise ValueError("Brief de resposta incompatível")

    definitions = tuple(EVENT_DEFINITIONS[item.event] for item in outcome.directives)
    policies = tuple(item.policy for item in definitions)
    required = frozenset().union(*(policy.required_placeholders for policy in policies))
    allowed = frozenset().union(*(policy.allowed_placeholders for policy in policies))
    public_number_patterns = _public_number_patterns(outcome)

    if generated is not None:
        rejected = _validate_template(
            generated.text,
            required,
            allowed & outcome.protected_values.keys(),
            brief.expected_questions,
            policies,
            exact_questions=True,
            public_number_patterns=public_number_patterns,
        )
        if rejected is None and not _question_is_authorized(generated.text, outcome):
            rejected = FallbackReason.POLICY_REJECTED
        if rejected is None and not _interview_offer_is_authorized(generated.text, definitions):
            rejected = FallbackReason.POLICY_REJECTED
        if rejected is None and not _required_markers_follow_directives(
            generated.text, definitions
        ):
            rejected = FallbackReason.POLICY_REJECTED
        if rejected is None:
            return RenderedResponse(
                text=_interpolate(generated.text, outcome.protected_values),
                used_fallback=False,
            )
        fallback_reason = rejected

    has_resume = any(
        directive.event == ResponseEvent.RESUME_PENDING_STEP for directive in outcome.directives
    )
    blocks = tuple(
        INVALID_INPUT_STATEMENT
        if has_resume and directive.event == ResponseEvent.INVALID_INPUT
        else _fallback_for(directive, outcome.next_step)
        for directive in outcome.directives
    )
    for definition, block in zip(definitions, blocks, strict=True):
        # Um bloco pode ser declarativo; a pergunta única é exigida no conjunto.
        if _validate_template(
            block,
            definition.policy.required_placeholders,
            definition.policy.allowed_placeholders,
            definition.policy.expected_questions,
            (definition.policy,),
            public_number_patterns=public_number_patterns,
        ):
            raise ValueError("Catálogo de respostas inválido")
    template = "\n\n".join(blocks)
    if _validate_template(
        template,
        required,
        allowed,
        brief.expected_questions,
        policies,
        exact_questions=True,
        public_number_patterns=public_number_patterns,
    ) or not _question_is_authorized(template, outcome):
        raise ValueError("Catálogo de respostas inválido")
    return RenderedResponse(
        text=_interpolate(template, outcome.protected_values),
        used_fallback=True,
        fallback_reason=fallback_reason or FallbackReason.PROVIDER_UNAVAILABLE,
    )
