"""Voz da Lia e apresentação de fatos confirmados pelos serviços."""

import re

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
NEXT_STEPS = "Quer aproveitar para fazer mais alguma coisa?\n\n" + OPTIONS
CLOSED = (
    "Nossa conversa foi encerrada. Foi bom ter você por aqui!\n\n"
    "Quando precisar, é só clicar em **Nova conversa**. Até mais!\n\n**Lia · Banco Ágil**"
)


def with_lia_voice(body: str, acknowledgement: str) -> str:
    """Acrescenta acolhimento contextual; fatos e próximos passos vêm do Flow.

    O campo de acolhimento não é usado para exibir decisões, valores, pedir dados
    ou direcionar o cliente a links. Se sair desse escopo, usamos apenas o corpo.
    """
    opening = acknowledgement.strip()
    forbidden = (
        r"\d|https?://|www\.|@|[\[\]<>]|\n|"
        r"aprov|reprov|rejeit|autentic|confirm|garant|liber|score|juros|taxa|"
        r"senha|\bpix\b|\bcpf\b|nascimento|renda|despesa|d[ií]vida"
        r"|\b(?:vou|vamos|iremos|vai|posso|consigo|irei)\s+"
        r"(?:aument|solicit|conced|alter|atualiz|elevar|conseguir)"
    )
    if not opening or len(opening) > 220 or re.search(forbidden, opening, re.IGNORECASE):
        return body
    return f"{opening}\n\n{body}"
