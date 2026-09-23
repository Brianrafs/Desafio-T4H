import pytest

from banco_agil.models.responses import (
    CriticalFailureCode,
    FlowOutcome,
    GeneratedMessage,
    OutcomeDirective,
    ResponseAction,
    ResponseEvent,
    UserTone,
)
from banco_agil.responses.briefs import build_response_brief, safe_summary
from banco_agil.responses.catalog import CRITICAL_MESSAGES, EVENT_DEFINITIONS
from banco_agil.responses.renderer import render_response


@pytest.mark.parametrize(
    "next_step,expected,absent",
    [("await_cpf", "CPF", "nascimento"), ("await_birth_date", "nascimento", "CPF")],
)
def test_retry_fallback_only_asks_the_pending_authentication_field(next_step, expected, absent):
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="authentication_retry", public_context={"remaining_attempts": 2}
            ),
            OutcomeDirective(event="resume_pending_step"),
        ),
        specialist="triage",
        next_step=next_step,
        expected_questions=1,
    )
    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)
    assert rendered.used_fallback
    assert rendered.text.count("?") == 1
    assert expected in rendered.text
    assert absent not in rendered.text
    assert "Tentativas restantes: **2**" in rendered.text


def test_every_response_event_has_definition_and_fallback():
    assert set(EVENT_DEFINITIONS) == set(ResponseEvent)
    assert all(definition.fallback for definition in EVENT_DEFINITIONS.values())


def test_every_critical_failure_has_fixed_message():
    assert set(CRITICAL_MESSAGES) == set(CriticalFailureCode)
    assert all(CRITICAL_MESSAGES.values())


def test_brief_contains_placeholder_name_but_not_protected_value():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_limit_found"),),
        specialist="credit",
        protected_values={"current_limit": "R$ 2.500,00"},
        next_step="idle",
    )

    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    serialized = brief.model_dump_json()
    assert "current_limit" in serialized
    assert "2.500" not in serialized


def test_brief_copies_current_specialist_from_outcome():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="service_information", public_context={"topic": "capabilities"}),
        ),
        specialist="exchange",
        next_step="idle",
    )

    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    assert brief.specialist.value == "exchange"
    assert '"specialist":"exchange"' in brief.model_dump_json()


@pytest.fixture
def credit_limit_response():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_limit_found"),),
        specialist="credit",
        protected_values={"current_limit": "R$ 2.500,00"},
        next_step="idle",
    )
    return outcome, build_response_brief(outcome, UserTone.NEUTRAL)


@pytest.mark.parametrize(
    "text,reason",
    [
        ("Seu limite é {{current_limit}} e {{unknown}}.", "unknown_placeholder"),
        ("Seu limite foi consultado.", "missing_placeholder"),
        ("Seu limite é {{current_limit}} e R$ 9.999,99.", "policy_rejected"),
        ("Pedido aprovado. Limite: {{current_limit}}.", "policy_rejected"),
        ("{{current_limit}} e novamente {{current_limit}}.", "policy_rejected"),
        ("Use { {current_limit} }.", "missing_placeholder"),
    ],
)
def test_invalid_generated_message_uses_fallback(credit_limit_response, text, reason):
    outcome, brief = credit_limit_response

    rendered = render_response(outcome, brief, GeneratedMessage(text=text))

    assert rendered.used_fallback
    assert rendered.fallback_reason == reason
    assert "9.999" not in rendered.text


def test_valid_message_inserts_only_confirmed_protected_value(credit_limit_response):
    outcome, brief = credit_limit_response

    rendered = render_response(
        outcome, brief, GeneratedMessage(text="Seu limite: {{current_limit}}.")
    )

    assert rendered.text == "Seu limite: R$ 2.500,00."
    assert not rendered.used_fallback
    assert rendered.fallback_reason is None


@pytest.mark.parametrize(
    "literal",
    [
        "99999 reais",
        "noventa e nove mil reais",
        "20%",
        "vinte por cento",
        "$99999",
        "€ 99999",
        "£ 99999",
        "¥99999",
        "USD 99999",
        "99999",
    ],
)
def test_generated_financial_literals_outside_placeholders_are_rejected(
    credit_limit_response, literal
):
    outcome, brief = credit_limit_response

    rendered = render_response(
        outcome,
        brief,
        GeneratedMessage(text="Seu limite: {{current_limit}}. Valor adicional: " + literal + "."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert literal not in rendered.text


@pytest.mark.parametrize(
    "event,context,next_step,text",
    [
        (
            "authentication_retry",
            {"remaining_attempts": 2},
            "await_cpf",
            "Os dados não coincidiram. Restam 2 tentativas.",
        ),
        (
            "interview_question",
            {"field": "dependents"},
            "await_interview_field",
            "Quantos dependentes você tem? Se nenhum, diga 0.",
        ),
        (
            "interview_started",
            {},
            "await_interview_field",
            "São 5 perguntas, uma por vez.",
        ),
    ],
)
def test_public_numeric_guidance_is_preserved(event, context, next_step, text):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event=event, public_context=context),),
        specialist="triage" if event == "authentication_retry" else "credit_interview",
        next_step=next_step,
        expected_questions=text.count("?"),
    )

    rendered = render_response(
        outcome, build_response_brief(outcome, UserTone.NEUTRAL), GeneratedMessage(text=text)
    )

    assert not rendered.used_fallback
    assert rendered.text == text


@pytest.mark.parametrize(
    "text",
    [
        "Os dados não coincidiram. Restam 9 tentativas.",
        "Os dados não coincidiram. Restam 2 tentativas. Taxa de 2%.",
        "Os dados não coincidiram. Limite adicional: 2.",
    ],
)
def test_public_count_does_not_authorize_other_numbers_or_financial_claims(text):
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="authentication_retry", public_context={"remaining_attempts": 2}
            ),
        ),
        specialist="triage",
        next_step="await_cpf",
    )

    rendered = render_response(
        outcome, build_response_brief(outcome, UserTone.NEUTRAL), GeneratedMessage(text=text)
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "Tentativas restantes: **2**" in rendered.text


@pytest.mark.parametrize(
    "text",
    [
        "Seu limite: {{{current_limit}}}.",
        "Seu limite: \\{{current_limit}}.",
        "Seu limite: {{current_limit}.",
        "Seu limite: {{CURRENT_LIMIT}}.",
    ],
)
def test_malformed_or_escaped_marker_never_reaches_user(credit_limit_response, text):
    outcome, brief = credit_limit_response

    rendered = render_response(outcome, brief, GeneratedMessage(text=text))

    assert rendered.used_fallback
    assert "{" not in rendered.text
    assert "R$ 2.500,00" in rendered.text


def test_generated_message_rejects_extra_question_when_none_authorized(credit_limit_response):
    outcome, brief = credit_limit_response

    rendered = render_response(outcome, brief, GeneratedMessage(text="Limite: {{current_limit}}?"))

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"


def test_composed_brief_preserves_event_order_and_deduplicates_actions():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="credit_limit_found"),
            OutcomeDirective(event="show_options"),
        ),
        specialist="credit",
        next_step="idle",
    )

    brief = build_response_brief(outcome, UserTone.CONCERNED)

    assert tuple(item.event for item in brief.directives) == (
        ResponseEvent.CREDIT_LIMIT_FOUND,
        ResponseEvent.SHOW_OPTIONS,
    )
    assert brief.allowed_actions.count(ResponseAction.REQUEST_CREDIT_INCREASE) == 1
    assert brief.user_tone is UserTone.CONCERNED


def test_safe_summary_describes_events_not_protected_values(credit_limit_response):
    outcome, brief = credit_limit_response

    summary = safe_summary(outcome, brief)

    assert summary.events == (ResponseEvent.CREDIT_LIMIT_FOUND,)
    assert summary.specialist.value == "credit"
    assert summary.next_step.value == "idle"
    assert summary.actions_offered == (ResponseAction.REQUEST_CREDIT_INCREASE,)
    assert "2.500" not in summary.model_dump_json()


def test_missing_protected_value_does_not_expose_template(credit_limit_response):
    outcome, brief = credit_limit_response
    outcome.protected_values = {}

    with pytest.raises(ValueError, match="Valor protegido ausente") as exc_info:
        render_response(outcome, brief, GeneratedMessage(text="Segredo: {{current_limit}}"))

    assert "Segredo" not in str(exc_info.value)


def test_fallback_reason_is_preserved_without_generated_message(credit_limit_response):
    outcome, brief = credit_limit_response

    rendered = render_response(outcome, brief, None, fallback_reason="provider_unavailable")

    assert rendered.used_fallback
    assert rendered.fallback_reason == "provider_unavailable"
    assert rendered.text.count("R$ 2.500,00") == 1


def test_service_information_fallback_uses_approved_public_topic():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="service_information", public_context={"topic": "credit_interview"}
            ),
        ),
        specialist="triage",
        next_step="idle",
    )

    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert "cinco perguntas" in rendered.text
    assert "renda mensal" in rendered.text


def test_interview_question_fallback_uses_only_pending_field():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert "dependem financeiramente" in rendered.text
    assert "renda mensal" not in rendered.text
    assert rendered.text.count("?") == 1


def test_interview_employment_brief_includes_allowed_choices_without_private_values():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="interview_question",
                public_context={"field": "employment_type", "monthly_income": "R$ 8.000,00"},
            ),
        ),
        specialist="credit_interview",
        protected_values={"monthly_income": "R$ 8.000,00"},
        next_step="await_interview_field",
        expected_questions=1,
    )

    brief = build_response_brief(outcome, UserTone.NEUTRAL)
    guidance = brief.directives[0].public_context["field_guidance"]

    assert brief.directives[0].public_context["field"] == "employment_type"
    assert all(choice in guidance for choice in ("formal", "autonomo", "desempregado"))
    assert "8.000" not in brief.model_dump_json()


@pytest.mark.parametrize(
    "field,required_guidance",
    [
        ("monthly_income", "valor monetário"),
        ("fixed_expenses", "valor monetário"),
        ("dependents", "inteiro não negativo"),
        ("has_active_debt", "sim ou não"),
    ],
)
def test_interview_other_fields_have_public_answer_guidance(field, required_guidance):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="interview_question", public_context={"field": field}),),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    assert required_guidance in brief.directives[0].public_context["field_guidance"]


def test_resumed_interview_brief_receives_field_guidance():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="resume_pending_step", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    assert "inteiro não negativo" in brief.directives[0].public_context["field_guidance"]


def test_interview_brief_fails_closed_for_unknown_field():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "unknown"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    with pytest.raises(ValueError, match="^Campo de entrevista inválido$"):
        build_response_brief(outcome, UserTone.NEUTRAL)


def test_authentication_retry_displays_only_authorized_remaining_count():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="authentication_retry", public_context={"remaining_attempts": 2}
            ),
        ),
        specialist="triage",
        next_step="await_cpf",
        expected_questions=0,
    )

    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert "Tentativas restantes: **2**" in rendered.text


def test_invalid_catalog_template_fails_closed_without_model_text(
    monkeypatch, credit_limit_response
):
    outcome, brief = credit_limit_response
    definition = EVENT_DEFINITIONS[ResponseEvent.CREDIT_LIMIT_FOUND]
    monkeypatch.setitem(
        EVENT_DEFINITIONS,
        ResponseEvent.CREDIT_LIMIT_FOUND,
        definition.model_copy(update={"fallback": "Valor: {{wrong}}"}),
    )

    with pytest.raises(ValueError, match="Catálogo de respostas inválido") as exc_info:
        render_response(outcome, brief, GeneratedMessage(text="ATAQUE {{current_limit}}?"))

    assert "ATAQUE" not in str(exc_info.value)


def test_combined_authentication_and_limit_have_one_cohesive_fallback():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="authentication_succeeded"),
            OutcomeDirective(event="credit_limit_found"),
        ),
        specialist="credit",
        protected_values={
            "customer_first_name": "Ana",
            "current_limit": "R$ 2.500,00",
        },
        next_step="idle",
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    rendered = render_response(outcome, brief, generated=None)

    assert rendered.text.startswith("Pronto, Ana.")
    assert rendered.text.count("Ana") == 1
    assert rendered.text.count("R$ 2.500,00") == 1
    assert rendered.text.count("?") <= 1


def test_generated_authentication_then_limit_rejects_inverted_protected_fact_order():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="authentication_succeeded"),
            OutcomeDirective(event="credit_limit_found"),
        ),
        specialist="credit",
        protected_values={"customer_first_name": "Ana", "current_limit": "R$ 2.500,00"},
        next_step="idle",
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    rendered = render_response(
        outcome,
        brief,
        GeneratedMessage(text="Seu limite: {{current_limit}}. Olá, {{customer_first_name}}."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert rendered.text.index("Ana") < rendered.text.index("R$ 2.500,00")


def test_generated_authentication_then_limit_accepts_protected_fact_order():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="authentication_succeeded"),
            OutcomeDirective(event="credit_limit_found"),
        ),
        specialist="credit",
        protected_values={"customer_first_name": "Ana", "current_limit": "R$ 2.500,00"},
        next_step="idle",
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    rendered = render_response(
        outcome,
        brief,
        GeneratedMessage(text="Olá, {{customer_first_name}}. Seu limite: {{current_limit}}."),
    )

    assert not rendered.used_fallback
    assert rendered.text == "Olá, Ana. Seu limite: R$ 2.500,00."


def test_combined_information_and_resume_preserve_only_authorized_question():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="service_information", public_context={"topic": "supported_currencies"}
            ),
            OutcomeDirective(event="resume_pending_step"),
        ),
        specialist="exchange",
        next_step="await_currency",
        expected_questions=1,
    )
    brief = build_response_brief(outcome, UserTone.UNCERTAIN)

    rendered = render_response(outcome, brief, generated=None)

    assert rendered.text.startswith("Posso consultar a cotação de compra")
    assert rendered.text.endswith("**USD, EUR ou GBP**?")
    assert rendered.text.count("?") == 1


def test_generated_information_and_resume_without_question_uses_pending_fallback():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="service_information", public_context={"topic": "credit_evaluation"}
            ),
            OutcomeDirective(event="resume_pending_step"),
        ),
        specialist="credit",
        next_step="await_requested_limit",
        expected_questions=1,
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    rendered = render_response(
        outcome, brief, GeneratedMessage(text="Posso explicar a avaliação de crédito.")
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert rendered.text.count("?") == 1
    assert "limite total" in rendered.text


def test_generated_information_and_resume_with_one_authorized_question_is_accepted():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="service_information", public_context={"topic": "credit_evaluation"}
            ),
            OutcomeDirective(event="resume_pending_step"),
        ),
        specialist="credit",
        next_step="await_requested_limit",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(
            text="A entrevista não garante aprovação. Qual limite total deseja solicitar?"
        ),
    )

    assert not rendered.used_fallback
    assert rendered.text.count("?") == 1


def test_generated_completed_exchange_rejects_question_and_keeps_quote():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="exchange_quote_found"),),
        specialist="exchange",
        protected_values={"exchange_rate": "1 USD = R$ 5.0000", "quote_timestamp": ""},
        next_step="idle",
        expected_questions=0,
    )
    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Cotação: {{exchange_rate}}.{{quote_timestamp}} Qual moeda deseja?"),
    )

    assert rendered.used_fallback
    assert rendered.text.count("?") == 0
    assert "1 USD = R$ 5.0000" in rendered.text


def test_rejected_credit_never_accepts_approval_claim():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_increase_rejected_offer_interview"),),
        specialist="credit",
        next_step="await_interview_confirmation",
        expected_questions=1,
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)

    rendered = render_response(
        outcome,
        brief,
        GeneratedMessage(text="Aprovamos seu pedido. Quer continuar?"),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "Aprovamos" not in rendered.text


@pytest.mark.parametrize("event", ["credit_increase_approved", "interview_reanalysis_approved"])
@pytest.mark.parametrize(
    "claim",
    [
        "Seu pedido foi rejeitado.",
        "Pedido reprovado.",
        "Seu aumento foi negado.",
        "Seu pedido não foi aprovado.",
        "Seu pedido não foi **aprovado**.",
        "Não consegui aprovar seu pedido.",
    ],
)
def test_approved_credit_rejects_contradictory_rejection(event, claim):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event=event),),
        specialist="credit",
        protected_values={"new_limit": "R$ 2.000,00"},
        next_step="idle",
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text=claim + " Novo limite: {{new_limit}}."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "**aprovado**" in rendered.text
    assert "R$ 2.000,00" in rendered.text


@pytest.mark.parametrize("event", ["credit_increase_approved", "interview_reanalysis_approved"])
def test_approved_credit_preserves_confirmed_approval(event):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event=event),),
        specialist="credit",
        protected_values={"new_limit": "R$ 2.000,00"},
        next_step="idle",
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Seu pedido foi aprovado. Novo limite: {{new_limit}}."),
    )

    assert not rendered.used_fallback
    assert rendered.text == "Seu pedido foi aprovado. Novo limite: R$ 2.000,00."


@pytest.mark.parametrize(
    "offer",
    [
        "Podemos fazer outra entrevista financeira.",
        "Posso oferecer uma entrevista financeira.",
        "Inicie uma nova entrevista financeira.",
        "Uma nova entrevista está disponível para você.",
    ],
)
def test_final_rejection_does_not_accept_unauthorized_interview_offer(offer):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_increase_rejected_final"),),
        specialist="credit",
        next_step="idle",
    )
    brief = build_response_brief(outcome, UserTone.NEUTRAL)
    # A autorização vem do evento, não de um brief alargado.
    brief.allowed_actions += (ResponseAction.START_CREDIT_INTERVIEW,)

    rendered = render_response(outcome, brief, GeneratedMessage(text="Pedido rejeitado. " + offer))

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert offer not in rendered.text


def test_rejection_accepts_interview_offer_when_authorized():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="credit_increase_rejected_offer_interview"),),
        specialist="credit",
        next_step="await_interview_confirmation",
        expected_questions=1,
    )
    text = "Não consegui aprovar. Podemos fazer uma entrevista financeira. Quer continuar?"

    rendered = render_response(
        outcome, build_response_brief(outcome, UserTone.NEUTRAL), GeneratedMessage(text=text)
    )

    assert not rendered.used_fallback
    assert rendered.text == text


@pytest.mark.parametrize(
    "credential_request",
    [
        "Qual é sua renda mensal e sua senha?",
        "Qual é sua renda mensal e seu código de acesso?",
        "Qual é sua renda mensal e seu token?",
        "Qual é sua renda mensal e seu PIN?",
        "Qual é sua renda mensal e seu login?",
        "Qual é sua renda mensal e seu CVV?",
        "Qual é sua renda mensal? Informe sua senha.",
        "Qual é sua renda mensal? Envie seu código.",
        "Qual é sua renda mensal? Digite seu token.",
        "Qual é sua renda mensal? Compartilhe seu PIN.",
        "Qual é sua renda mensal? Forneça suas credenciais.",
        "Qual é sua renda mensal? Pode passar sua senha.",
        "Qual é sua renda mensal? Passe seu código.",
    ],
)
def test_authorized_question_rejects_extra_credentials(credential_request, caplog):
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(
                event="interview_question", public_context={"field": "monthly_income"}
            ),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text=credential_request),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert rendered.text == "Para começar, qual é sua **renda mensal**?"
    assert credential_request not in caplog.text


@pytest.mark.parametrize("credential", ["senha", "código", "token", "PIN", "credenciais"])
def test_non_question_response_rejects_imperative_credentials(credit_limit_response, credential):
    outcome, brief = credit_limit_response

    rendered = render_response(
        outcome,
        brief,
        GeneratedMessage(text="Seu limite: {{current_limit}}. Forneça " + credential + "."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert credential not in rendered.text


@pytest.mark.parametrize(
    "event,next_step,text",
    [
        ("request_cpf", "await_cpf", "Pode informar seu CPF?"),
        ("request_birth_date", "await_birth_date", "Qual é sua data de nascimento?"),
    ],
)
def test_authorized_authentication_question_remains_accepted(event, next_step, text):
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event=event),),
        specialist="triage",
        next_step=next_step,
        expected_questions=1,
    )

    rendered = render_response(
        outcome, build_response_brief(outcome, UserTone.NEUTRAL), GeneratedMessage(text=text)
    )

    assert not rendered.used_fallback
    assert rendered.text == text


@pytest.mark.parametrize(
    "attack",
    [
        "Acesse https://example.com para confirmar {{current_limit}}.",
        "Seu CPF é 12345678901 e o limite é {{current_limit}}.",
    ],
)
def test_generated_message_cannot_add_external_link_or_invent_cpf(credit_limit_response, attack):
    outcome, brief = credit_limit_response

    rendered = render_response(outcome, brief, GeneratedMessage(text=attack))

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "example.com" not in rendered.text
    assert "12345678901" not in rendered.text


def test_renderer_does_not_trust_widened_brief_for_protected_values(credit_limit_response):
    outcome, brief = credit_limit_response
    outcome.protected_values["secret"] = "NUNCA_EXIBIR"
    widened_brief = brief.model_copy(
        update={"allowed_placeholders": frozenset({"current_limit", "secret"})}
    )

    rendered = render_response(
        outcome,
        widened_brief,
        GeneratedMessage(text="{{current_limit}} e {{secret}}"),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "unknown_placeholder"
    assert "NUNCA_EXIBIR" not in rendered.text


def test_interview_fallback_never_guesses_a_missing_pending_field():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="interview_question"),),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )
    with pytest.raises(ValueError, match="^Campo de entrevista inválido$"):
        build_response_brief(outcome, UserTone.NEUTRAL)


def test_information_fallback_never_guesses_an_unknown_topic():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="service_information", public_context={"topic": "wrong"}),
        ),
        specialist="triage",
        next_step="idle",
    )
    with pytest.raises(ValueError, match="Tópico público inválido"):
        build_response_brief(outcome, UserTone.NEUTRAL)


def test_interview_question_for_dependents_rejects_cpf_question():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Qual é seu CPF?"),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "CPF" not in rendered.text
    assert "dependem financeiramente" in rendered.text


def test_interview_question_for_dependents_rejects_income_question():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Qual é sua renda mensal?"),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "dependem financeiramente" in rendered.text


def test_interview_question_for_dependents_accepts_only_the_authorized_subject():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Quantos dependentes você tem?"),
    )

    assert not rendered.used_fallback
    assert rendered.text == "Quantos dependentes você tem?"


def test_invalid_input_then_resume_cpf_fallback_asks_only_resume_question():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="invalid_input"),
            OutcomeDirective(event="resume_pending_step"),
        ),
        specialist="triage",
        next_step="await_cpf",
        expected_questions=1,
    )

    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert rendered.used_fallback
    assert rendered.text.startswith("Não consegui entender esse dado.")
    assert rendered.text.endswith("Pode me informar seu **CPF**?")
    assert rendered.text.count("?") == 1


def test_combined_fallback_preserves_repeated_directives_but_only_one_question():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="invalid_input"),
            OutcomeDirective(event="invalid_input"),
            OutcomeDirective(event="resume_pending_step"),
        ),
        specialist="triage",
        next_step="await_cpf",
        expected_questions=1,
    )

    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert rendered.text.count("Não consegui entender esse dado.") == 2
    assert rendered.text.count("CPF") == 1
    assert rendered.text.count("?") == 1


def test_interview_dependents_rejects_unauthorized_cpf_request_without_question_mark():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Me informe seu CPF."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "CPF" not in rendered.text


def test_interview_dependents_rejects_unrelated_request_after_valid_question():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Quantos dependentes você tem? Me informe seu CPF."),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"


def test_interview_dependents_rejects_other_field_in_intro():
    outcome = FlowOutcome(
        directives=(
            OutcomeDirective(event="interview_question", public_context={"field": "dependents"}),
        ),
        specialist="credit_interview",
        next_step="await_interview_field",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Vamos falar da sua renda. Quantos dependentes você tem?"),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"


def test_unsupported_currency_fallback_asks_a_self_contained_currency_question():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="unsupported_currency"),),
        specialist="exchange",
        next_step="await_currency",
        expected_questions=1,
    )

    rendered = render_response(outcome, build_response_brief(outcome, UserTone.NEUTRAL), None)

    assert rendered.used_fallback
    assert "**Dólar** — USD" in rendered.text
    assert rendered.text.endswith("Qual moeda você prefere?")
    assert rendered.text.count("?") == 1


def test_unsupported_currency_generated_message_rejects_other_subject():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="unsupported_currency"),),
        specialist="exchange",
        next_step="await_currency",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Qual é sua renda mensal?"),
    )

    assert rendered.used_fallback
    assert rendered.fallback_reason == "policy_rejected"
    assert "renda mensal" not in rendered.text


def test_unsupported_currency_generated_message_accepts_explicit_currency_subject():
    outcome = FlowOutcome(
        directives=(OutcomeDirective(event="unsupported_currency"),),
        specialist="exchange",
        next_step="await_currency",
        expected_questions=1,
    )

    rendered = render_response(
        outcome,
        build_response_brief(outcome, UserTone.NEUTRAL),
        GeneratedMessage(text="Posso consultar USD, EUR ou GBP. Qual moeda você prefere?"),
    )

    assert not rendered.used_fallback
    assert rendered.text.endswith("Qual moeda você prefere?")
