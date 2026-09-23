"""Catálogo fechado de fatos, políticas e mensagens locais de contingência."""

from pydantic import Field

from banco_agil.models.domain import InformationTopic, Model
from banco_agil.models.errors import (
    ExchangeServiceUnavailableError,
    LLMError,
    LLMStructuredOutputError,
    RepositoryError,
    ScoreRangeNotFoundError,
)
from banco_agil.models.responses import (
    CriticalFailureCode,
    NextStep,
    ResponseAction,
    ResponseEvent,
    ResponsePolicy,
)

OPTIONS = (
    "- **Consultar meu limite** de crédito\n"
    "- **Pedir um aumento** de limite\n"
    "- **Ver uma cotação** — dólar (USD), euro (EUR) ou libra (GBP)\n"
)
WELCOME = (
    "Oi! Eu sou a **Lia**, sua assistente do **Banco Ágil**. "
    "Estou aqui para ajudar você, uma etapa de cada vez.\n\n"
    + OPTIONS
    + "\n\nPor onde você gostaria de começar?"
)
CLOSED = (
    "Nossa conversa foi encerrada. Foi bom ter você por aqui!\n\n"
    "Quando precisar, é só clicar em **Nova conversa**. Até mais!\n\n**Lia · Banco Ágil**"
)


class InformationDefinition(Model):
    communication_goal: str
    fallback: str


# Catálogo fechado de fatos públicos; detalhes internos não entram no brief.
INFORMATION_TOPICS: dict[InformationTopic, InformationDefinition] = {
    InformationTopic.CAPABILITIES: InformationDefinition(
        communication_goal=(
            "Explique que pode consultar limite, avaliar aumento e consultar cotação de "
            "compra de dólar, euro ou libra."
        ),
        fallback=(
            "Posso ajudar você a **consultar seu limite de crédito**, pedir uma "
            "**avaliação de aumento** e consultar a cotação de **dólar, euro ou libra**."
        ),
    ),
    InformationTopic.CREDIT_EVALUATION: InformationDefinition(
        communication_goal=(
            "Explique que o limite total solicitado deve superar o atual e respeitar o "
            "máximo da faixa do perfil. Se não aprovado inicialmente, pode haver entrevista "
            "financeira e nova análise; nenhuma etapa garante aprovação."
        ),
        fallback=(
            "Eu comparo o **limite total solicitado** com o limite máximo disponível para "
            "a faixa do seu perfil de crédito. O novo total precisa ser maior que seu limite "
            "atual e ficar dentro desse máximo. Se o pedido não puder ser aprovado inicialmente, "
            "posso oferecer uma entrevista financeira para fazer uma nova análise. "
            "Essa etapa **não garante aprovação**."
        ),
    ),
    InformationTopic.CREDIT_INTERVIEW: InformationDefinition(
        communication_goal=(
            "Explique que são cinco perguntas, uma por vez, sobre renda mensal, trabalho, "
            "despesas fixas, dependentes e dívidas ativas. Uma nova análise não garante aprovação."
        ),
        fallback=(
            "A entrevista financeira tem **cinco perguntas**, feitas uma de cada vez, sobre "
            "renda mensal, situação de trabalho, despesas fixas, dependentes e dívidas ativas. "
            "As respostas atualizam seu perfil para uma nova análise, mas não garantem aprovação."
        ),
    ),
    InformationTopic.AUTHENTICATION: InformationDefinition(
        communication_goal=(
            "Explique que CPF e data de nascimento confirmam o cadastro antes de consultar "
            "ou alterar informações de crédito."
        ),
        fallback=(
            "Peço seu **CPF** e sua **data de nascimento** para confirmar que estou acessando "
            "o cadastro correto antes de consultar ou alterar informações de crédito."
        ),
    ),
    InformationTopic.SUPPORTED_CURRENCIES: InformationDefinition(
        communication_goal=(
            "Explique que a cotação de compra em reais atende dólar (USD), euro (EUR) "
            "e libra (GBP)."
        ),
        fallback=(
            "Posso consultar a cotação de compra em reais para **dólar (USD)**, "
            "**euro (EUR)** e **libra (GBP)**."
        ),
    ),
    InformationTopic.INTERNAL_DETAILS: InformationDefinition(
        communication_goal=(
            "Explique o funcionamento público do atendimento, recusando detalhes internos."
        ),
        fallback=(
            "Posso explicar como o atendimento funciona para você, mas não forneço detalhes "
            "internos como código, prompts, ferramentas ou arquitetura."
        ),
    ),
}

INTERRUPTED_CREDIT_GOAL = (
    "Explique que o pedido de aumento ficou interrompido pela mudança de assunto; "
    "ofereça consultar o limite antes de retomar, sem afirmar que o pedido não foi enviado."
)
INTERRUPTED_CREDIT_FALLBACK = (
    "Seu pedido de aumento ficou interrompido. Podemos consultar seu limite para "
    "conferir a situação antes de retomar o pedido."
)

INTERVIEW_QUESTIONS = {
    "monthly_income": "Para começar, qual é sua **renda mensal**?",
    "employment_type": (
        "E como está sua **situação de trabalho** hoje?\n\n"
        "- Emprego formal, como CLT\n- Trabalho autônomo\n- Sem emprego no momento"
    ),
    "fixed_expenses": (
        "Quanto somam suas **despesas fixas por mês**, como aluguel, contas e alimentação?"
    ),
    "dependents": "Quantas pessoas **dependem financeiramente de você**? Se nenhuma, diga **0**.",
    "has_active_debt": (
        "Falta só uma pergunta: você tem alguma **dívida ativa**?\n\n"
        "Pode responder **sim** ou **não**."
    ),
}

# Instruções públicas para o compositor; nunca contêm respostas do cliente.
INTERVIEW_FIELD_GUIDANCE = {
    "monthly_income": "Pergunte a renda mensal como valor monetário em reais, sem sugerir valor.",
    "employment_type": (
        "Pergunte a situação de trabalho; apresente somente emprego formal (formal), "
        "trabalho autônomo (autonomo) ou sem emprego (desempregado)."
    ),
    "fixed_expenses": (
        "Pergunte o total mensal das despesas fixas como valor monetário em reais, "
        "sem sugerir valor."
    ),
    "dependents": (
        "Pergunte quantos dependentes financeiros; a resposta deve ser inteiro não negativo "
        "(zero se nenhum)."
    ),
    "has_active_debt": "Pergunte se há dívida ativa; a resposta é sim ou não.",
}

PENDING_QUESTIONS = {
    NextStep.AWAIT_CPF: "Pode me informar seu **CPF**?",
    NextStep.AWAIT_BIRTH_DATE: "Qual é sua **data de nascimento**? Use o formato **dia/mês/ano**.",
    NextStep.AWAIT_REQUESTED_LIMIT: "Qual **limite total** você gostaria de ter?",
    NextStep.AWAIT_INTERVIEW_CONFIRMATION: "Quer seguir com a **entrevista financeira**?",
    NextStep.AWAIT_CURRENCY: "Qual moeda você gostaria de consultar: **USD, EUR ou GBP**?",
}

# A pergunta livre só é aceita se seu assunto corresponder à etapa decidida
# pelo Flow. Os demais assuntos sensíveis são proibidos na mesma pergunta.
QUESTION_SUBJECTS = {
    "cpf": r"\bcpf\b",
    "birth_date": r"\b(?:nascimento|nasceu)\b",
    "requested_limit": r"\b(?:limite|valor solicitado)\b",
    "interview_confirmation": r"\b(?:entrevista|continuar|seguir)\b",
    "monthly_income": r"\b(?:renda|salário|ganha)\b",
    "employment_type": r"\b(?:trabalho|emprego|profissão|ocupação)\b",
    "fixed_expenses": r"\b(?:despesas?|gastos?|custos?)\b",
    "dependents": r"\b(?:dependentes?|dependem)\b",
    "has_active_debt": r"\b(?:d[ií]vidas?|endividad[oa])\b",
    "currency": r"\b(?:moeda|cotação|dólar|euro|libra|usd|eur|gbp)\b",
    "options": r"\b(?:começar|opç(?:ão|ões)|prefere|ajudar|fazer)\b",
    "invalid_input": r"\b(?:contar|repetir|explicar|tentar|dizer)\b",
}

SENSITIVE_QUESTION_SUBJECTS = frozenset(
    {
        "cpf",
        "birth_date",
        "requested_limit",
        "monthly_income",
        "employment_type",
        "fixed_expenses",
        "dependents",
        "has_active_debt",
        "currency",
    }
)

STEP_QUESTION_SUBJECT = {
    NextStep.AWAIT_CPF: "cpf",
    NextStep.AWAIT_BIRTH_DATE: "birth_date",
    NextStep.AWAIT_REQUESTED_LIMIT: "requested_limit",
    NextStep.AWAIT_INTERVIEW_CONFIRMATION: "interview_confirmation",
    NextStep.AWAIT_CURRENCY: "currency",
}

EVENT_QUESTION_SUBJECT = {
    ResponseEvent.WELCOME: "options",
    ResponseEvent.SHOW_OPTIONS: "options",
    ResponseEvent.REQUEST_CPF: "cpf",
    ResponseEvent.REQUEST_BIRTH_DATE: "birth_date",
    ResponseEvent.REQUEST_CREDIT_LIMIT: "requested_limit",
    ResponseEvent.CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW: "interview_confirmation",
    ResponseEvent.REQUEST_CURRENCY: "currency",
    ResponseEvent.EXCHANGE_QUOTE_FOUND: "currency",
    ResponseEvent.UNSUPPORTED_CURRENCY: "currency",
    ResponseEvent.INVALID_INPUT: "invalid_input",
}

INVALID_INPUT_STATEMENT = "Não consegui entender esse dado."


class EventDefinition(Model):
    communication_goal: str
    policy: ResponsePolicy
    allowed_actions: tuple[ResponseAction, ...] = ()
    constraints: tuple[str, ...] = ()
    fallback: str = Field(min_length=1)


FINANCIAL_LITERAL = r"R\$\s*\d"
NO_APPROVAL = (
    r"\baprov(?:ad[oa]s?|amos|ou|ei|am|ação)\b",
    r"\bgarantid[oa]s?\b",
)
NO_REJECTION = (
    r"\b(?:rejeit|reprov|neg|recus)(?:ad[oa]s?|amos|ou|ei|am)\b",
    r"\bn[aã]o\s+(?:(?:foi|est[aá]|consegui|conseguimos|pude|podemos)\s+)?aprov\w*\b",
)

EVENT_DEFINITIONS: dict[ResponseEvent, EventDefinition] = {
    ResponseEvent.WELCOME: EventDefinition(
        communication_goal="Apresente Lia e as três operações disponíveis.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        allowed_actions=(
            ResponseAction.CONSULT_CREDIT_LIMIT,
            ResponseAction.REQUEST_CREDIT_INCREASE,
            ResponseAction.CONSULT_EXCHANGE_RATE,
        ),
        fallback=WELCOME,
    ),
    ResponseEvent.SHOW_OPTIONS: EventDefinition(
        communication_goal="Mostre as opções sem repetir a apresentação inicial.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        allowed_actions=(
            ResponseAction.CONSULT_CREDIT_LIMIT,
            ResponseAction.REQUEST_CREDIT_INCREASE,
            ResponseAction.CONSULT_EXCHANGE_RATE,
        ),
        fallback="Estou aqui com você. Qual destas opções você prefere?\n\n" + OPTIONS,
    ),
    ResponseEvent.REQUEST_CPF: EventDefinition(
        communication_goal="Peça somente o CPF para confirmar a identidade.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback=(
            "Para cuidar do seu pedido, preciso primeiro confirmar sua identidade.\n\n"
            "Pode me informar seu **CPF**?"
        ),
    ),
    ResponseEvent.REQUEST_BIRTH_DATE: EventDefinition(
        communication_goal="Peça somente a data de nascimento em dia/mês/ano.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback="Pode me informar sua **data de nascimento** no formato **dia/mês/ano**?",
    ),
    ResponseEvent.AUTHENTICATION_SUCCEEDED: EventDefinition(
        communication_goal="Confirme a identidade pelo primeiro nome, sem expor credenciais.",
        policy=ResponsePolicy(
            required_placeholders=frozenset({"customer_first_name"}),
            allowed_placeholders=frozenset({"customer_first_name"}),
            expected_questions=0,
            forbidden_patterns=(FINANCIAL_LITERAL,),
        ),
        fallback="Pronto, {{customer_first_name}}. Confirmei sua identidade.",
    ),
    ResponseEvent.AUTHENTICATION_RETRY: EventDefinition(
        communication_goal="Explique a divergência sem repetir CPF ou nascimento.",
        policy=ResponsePolicy(expected_questions=0, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback="Os dados não coincidiram com o cadastro. Vamos conferir juntos.",
    ),
    ResponseEvent.CREDIT_LIMIT_FOUND: EventDefinition(
        communication_goal=(
            "Informe o limite atual confirmado e ofereça ajuda sem prometer aumento."
        ),
        policy=ResponsePolicy(
            required_placeholders=frozenset({"current_limit"}),
            allowed_placeholders=frozenset({"current_limit"}),
            expected_questions=0,
            forbidden_patterns=(*NO_APPROVAL, FINANCIAL_LITERAL),
        ),
        allowed_actions=(ResponseAction.REQUEST_CREDIT_INCREASE,),
        fallback=(
            "Seu limite de crédito atual é **{{current_limit}}**.\n\n"
            "Se quiser, também posso avaliar um aumento para você."
        ),
    ),
    ResponseEvent.REQUEST_CREDIT_LIMIT: EventDefinition(
        communication_goal="Peça o limite total desejado, não apenas o acréscimo.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback=(
            "Qual **limite total** você gostaria de ter?\n\n"
            "Me diga o valor final desejado, não apenas quanto quer acrescentar."
        ),
    ),
    ResponseEvent.CREDIT_INCREASE_APPROVED: EventDefinition(
        communication_goal="Informe aprovação confirmada e novo limite disponível.",
        policy=ResponsePolicy(
            required_placeholders=frozenset({"new_limit"}),
            allowed_placeholders=frozenset({"new_limit"}),
            expected_questions=0,
            forbidden_patterns=(*NO_REJECTION, FINANCIAL_LITERAL),
        ),
        fallback=(
            "Boa notícia: seu pedido foi **aprovado**.\n\n"
            "Seu novo limite é **{{new_limit}}** e já está disponível."
        ),
    ),
    ResponseEvent.CREDIT_INCREASE_REJECTED_OFFER_INTERVIEW: EventDefinition(
        communication_goal="Informe a reprovação sem julgamento e ofereça a entrevista financeira.",
        policy=ResponsePolicy(
            allowed_placeholders=frozenset({"current_limit"}),
            expected_questions=1,
            forbidden_patterns=(*NO_APPROVAL, FINANCIAL_LITERAL),
        ),
        allowed_actions=(ResponseAction.START_CREDIT_INTERVIEW,),
        fallback=(
            "Não consegui aprovar esse valor agora, então seu limite continua o mesmo.\n\n"
            "Podemos fazer uma **entrevista financeira rápida** e analisar novamente com "
            "informações atualizadas. **Quer continuar?**"
        ),
    ),
    ResponseEvent.CREDIT_INCREASE_REJECTED_FINAL: EventDefinition(
        communication_goal="Informe reprovação final sem oferecer outra entrevista.",
        policy=ResponsePolicy(
            expected_questions=0, forbidden_patterns=(*NO_APPROVAL, FINANCIAL_LITERAL)
        ),
        allowed_actions=(
            ResponseAction.CONSULT_CREDIT_LIMIT,
            ResponseAction.CONSULT_EXCHANGE_RATE,
        ),
        fallback=(
            "Não consegui aprovar esse valor agora, então seu limite continua o mesmo.\n\n"
            "Se quiser, posso consultar seu limite ou ajudar com uma cotação."
        ),
    ),
    ResponseEvent.INTERVIEW_STARTED: EventDefinition(
        communication_goal="Explique as cinco perguntas, sem decidir ou pedir dados extras.",
        policy=ResponsePolicy(expected_questions=0, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback=(
            "Vamos olhar sua situação com mais cuidado. "
            "São **cinco perguntas rápidas**, uma de cada vez."
        ),
    ),
    ResponseEvent.INTERVIEW_QUESTION: EventDefinition(
        communication_goal="Faça somente a pergunta do campo pendente da entrevista.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback="Para começar, qual é sua **renda mensal**?",
    ),
    ResponseEvent.INTERVIEW_REANALYSIS_APPROVED: EventDefinition(
        communication_goal="Informe o resultado aprovado após a entrevista.",
        policy=ResponsePolicy(
            required_placeholders=frozenset({"new_limit"}),
            allowed_placeholders=frozenset({"new_limit"}),
            expected_questions=0,
            forbidden_patterns=(*NO_REJECTION, FINANCIAL_LITERAL),
        ),
        fallback=(
            "Obrigada por responder às perguntas. Com as informações atualizadas, "
            "seu pedido foi **aprovado**.\n\n"
            "Seu novo limite é **{{new_limit}}** e já está disponível."
        ),
    ),
    ResponseEvent.INTERVIEW_REANALYSIS_REJECTED: EventDefinition(
        communication_goal="Informe reprovação da reanálise sem oferecer nova entrevista.",
        policy=ResponsePolicy(
            expected_questions=0, forbidden_patterns=(*NO_APPROVAL, FINANCIAL_LITERAL)
        ),
        allowed_actions=(
            ResponseAction.CONSULT_CREDIT_LIMIT,
            ResponseAction.CONSULT_EXCHANGE_RATE,
        ),
        fallback=(
            "Obrigada por responder às perguntas. Mesmo com as informações atualizadas, "
            "não consegui aprovar esse valor agora. Seu limite atual continua o mesmo.\n\n"
            "Se quiser, posso consultar seu limite ou ajudar com uma cotação."
        ),
    ),
    ResponseEvent.REQUEST_CURRENCY: EventDefinition(
        communication_goal="Peça a moeda para a cotação de compra: USD, EUR ou GBP.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback=(
            "Qual moeda você gostaria de consultar?\n\n"
            "- **Dólar** — USD\n- **Euro** — EUR\n- **Libra** — GBP\n\n"
            "Vou mostrar a cotação de compra em reais."
        ),
    ),
    ResponseEvent.EXCHANGE_QUOTE_FOUND: EventDefinition(
        communication_goal=(
            "Informe a cotação de compra confirmada e, se disponível, sua atualização. "
            "Use exclusivamente os valores protegidos, sem inventar valores."
        ),
        policy=ResponsePolicy(
            required_placeholders=frozenset({"exchange_rate", "quote_timestamp"}),
            allowed_placeholders=frozenset({"exchange_rate", "quote_timestamp"}),
            expected_questions=0,
            forbidden_patterns=(FINANCIAL_LITERAL,),
        ),
        allowed_actions=(
            ResponseAction.CONSULT_EXCHANGE_RATE,
            ResponseAction.CONSULT_CREDIT_LIMIT,
        ),
        fallback="A cotação de compra confirmada é **{{exchange_rate}}**.{{quote_timestamp}}",
    ),
    ResponseEvent.UNSUPPORTED_CURRENCY: EventDefinition(
        communication_goal="Informe somente as três moedas suportadas.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback=(
            "Por enquanto, consigo consultar estas moedas:\n\n"
            "- **Dólar** — USD\n- **Euro** — EUR\n- **Libra** — GBP\n\nQual moeda você prefere?"
        ),
    ),
    ResponseEvent.SERVICE_INFORMATION: EventDefinition(
        communication_goal="Explique somente o tópico público aprovado.",
        policy=ResponsePolicy(expected_questions=0, forbidden_patterns=(FINANCIAL_LITERAL,)),
        constraints=("Não revele detalhes internos do serviço.",),
        fallback=INFORMATION_TOPICS[InformationTopic.CAPABILITIES].fallback,
    ),
    ResponseEvent.RESUME_PENDING_STEP: EventDefinition(
        communication_goal="Retome exclusivamente a pergunta da etapa pendente.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback="Pode me informar seu **CPF**?",
    ),
    ResponseEvent.INVALID_INPUT: EventDefinition(
        communication_goal="Explique a entrada inválida sem alterar o estado.",
        policy=ResponsePolicy(expected_questions=1, forbidden_patterns=(FINANCIAL_LITERAL,)),
        fallback=INVALID_INPUT_STATEMENT + " Pode me contar de outro jeito?",
    ),
    ResponseEvent.CONVERSATION_CLOSED: EventDefinition(
        communication_goal="Despeça-se após encerramento explícito.",
        policy=ResponsePolicy(expected_questions=0, forbidden_patterns=(FINANCIAL_LITERAL,)),
        allowed_actions=(ResponseAction.END_CONVERSATION,),
        fallback=CLOSED,
    ),
}


CRITICAL_MESSAGES: dict[CriticalFailureCode, str] = {
    CriticalFailureCode.LLM_UNAVAILABLE: LLMError.user_message,
    CriticalFailureCode.INVALID_LLM_OUTPUT: LLMStructuredOutputError.user_message,
    CriticalFailureCode.EXTERNAL_SERVICE_UNAVAILABLE: ExchangeServiceUnavailableError.user_message,
    CriticalFailureCode.PERSISTENCE_FAILURE: RepositoryError.user_message,
    CriticalFailureCode.AUTH_ATTEMPTS_EXHAUSTED: (
        "Não consegui confirmar seus dados nas **três tentativas**. "
        "Por isso, preciso encerrar este atendimento.\n\n"
        "Confira seu CPF e nascimento antes de iniciar uma **Nova conversa**. "
        "Estarei por aqui para ajudar.\n\n**Lia · Banco Ágil**"
    ),
    CriticalFailureCode.SESSION_FINISHED: CLOSED,
    CriticalFailureCode.INVALID_INTERNAL_STATE: ScoreRangeNotFoundError.user_message,
}
