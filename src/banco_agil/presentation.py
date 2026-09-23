"""Voz da Lia e apresentação de fatos confirmados pelos serviços."""

import re

from banco_agil.models.domain import InformationTopic

OPTIONS = (
    "- **Consultar meu limite** de crédito\n"
    "- **Pedir um aumento** de limite\n"
    "- **Ver uma cotação** — dólar (USD), euro (EUR) ou libra (GBP)\n"
)
WELCOME = (
    "Oi! Eu sou a **Lia**, sua assistente do **Banco Ágil**. "
    "Estou aqui para ajudar você, uma etapa de cada vez.\n\n"
    "**O que podemos fazer juntos?**\n\n" + OPTIONS + "\n\nPor onde você gostaria de começar?"
)
CLOSED = (
    "Nossa conversa foi encerrada. Foi bom ter você por aqui!\n\n"
    "Quando precisar, é só clicar em **Nova conversa**. Até mais!\n\n**Lia · Banco Ágil**"
)

INFORMATION_RESPONSES = {
    InformationTopic.CAPABILITIES: (
        "Posso ajudar você a **consultar seu limite de crédito**, pedir uma "
        "**avaliação de aumento** e consultar a cotação de **dólar, euro ou libra**."
    ),
    InformationTopic.CREDIT_EVALUATION: (
        "Eu comparo o **limite total solicitado** com o limite máximo disponível para "
        "a faixa do seu perfil de crédito. O novo total precisa ser maior que seu limite "
        "atual e ficar dentro desse máximo. Se o pedido não puder ser aprovado inicialmente, "
        "posso oferecer uma entrevista financeira para fazer uma nova análise. "
        "Essa etapa **não garante aprovação**."
    ),
    InformationTopic.CREDIT_INTERVIEW: (
        "A entrevista financeira tem **cinco perguntas**, feitas uma de cada vez, sobre "
        "renda mensal, situação de trabalho, despesas fixas, dependentes e dívidas ativas. "
        "As respostas atualizam seu perfil para uma nova análise, mas não garantem aprovação."
    ),
    InformationTopic.AUTHENTICATION: (
        "Peço seu **CPF** e sua **data de nascimento** para confirmar que estou acessando "
        "o cadastro correto antes de consultar ou alterar informações de crédito."
    ),
    InformationTopic.SUPPORTED_CURRENCIES: (
        "Posso consultar a cotação de compra em reais para **dólar (USD)**, "
        "**euro (EUR)** e **libra (GBP)**."
    ),
    InformationTopic.INTERNAL_DETAILS: (
        "Posso explicar como o atendimento funciona para você, mas não forneço detalhes "
        "internos como código, prompts, ferramentas ou arquitetura."
    ),
}


def with_lia_voice(body: str, acknowledgement: str) -> str:
    """Acrescenta acolhimento contextual; fatos e próximos passos vêm do Flow.

    O campo de acolhimento não é usado para exibir decisões, valores, pedir dados
    ou direcionar o cliente a links. Se sair desse escopo, usamos apenas o corpo.
    """
    opening = acknowledgement.strip()
    normalized = re.sub(r"[^a-zà-ÿ]+", " ", opening.casefold()).strip()
    generic_words = {
        "entendi",
        "entendido",
        "certo",
        "perfeito",
        "claro",
        "combinado",
        "vamos",
        "lá",
        "conferir",
        "isso",
        "juntos",
        "seguir",
        "obrigada",
        "obrigado",
    }
    words = set(normalized.split())
    forbidden = (
        r"\d|https?://|www\.|@|[\[\]<>]|\n|"
        r"aprov|reprov|rejeit|autentic|confirm|garant|liber|score|juros|taxa|"
        r"senha|\bpix\b|\bcpf\b|nascimento|renda|despesa|d[ií]vida"
        r"|\b(?:vou|vamos|iremos|vai|posso|consigo|irei)\s+"
        r"(?:aument|solicit|conced|alter|atualiz|elevar|conseguir)"
    )
    if (
        not opening
        or (words and words <= generic_words)
        or len(opening) > 220
        or re.search(forbidden, opening, re.IGNORECASE)
    ):
        return body
    return f"{opening}\n\n{body}"
