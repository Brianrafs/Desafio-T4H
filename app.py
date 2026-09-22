import asyncio

import streamlit as st

from banco_agil.bootstrap import create_conversation
from banco_agil.config import Settings
from banco_agil.models.errors import BankingError
from banco_agil.models.state import ConversationStatus

st.set_page_config(page_title="Banco Ágil | Atendimento", page_icon=":material/account_balance:")
st.title("Banco Ágil")
st.caption("Seu atendimento, em uma conversa.")

settings = Settings()

if "conversation" not in st.session_state:
    try:
        st.session_state.conversation = create_conversation(settings)
    except (BankingError, OSError):
        st.error("Não foi possível iniciar o atendimento. Verifique os dados e tente novamente.")
        st.stop()

st.session_state.setdefault(
    "messages",
    [
        {
            "role": "assistant",
            "content": (
                "Olá! Posso ajudar com seu limite de crédito ou uma cotação. Como posso ajudar?"
            ),
        }
    ],
)
conversation = st.session_state.conversation
finished = conversation.flow.state.status == ConversationStatus.FINISHED
configured = bool(settings.groq_api_key.get_secret_value())

with st.sidebar:
    st.subheader("Atendimento digital")
    st.write("Consulte seu limite, solicite um aumento ou confira cotações em reais.")
    st.caption("Demonstração com clientes fictícios.")
    with st.expander("Dados para experimentar"):
        st.write("**Ana** · CPF: 000.000.000-01 · Nascimento: 15/01/1990")
        st.write("**Bruno** · CPF: 000.000.000-02 · Nascimento: 20/05/1985")
    if st.button("Nova conversa", key="new_conversation", icon=":material/add:"):
        del st.session_state.conversation
        del st.session_state.messages
        st.rerun()
    if st.button("Encerrar atendimento", key="end_conversation", disabled=finished):
        reply = asyncio.run(conversation.send("encerrar"))
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

if not configured:
    st.info("Para ativar a conversa, configure GROQ_API_KEY no arquivo .env e recarregue a página.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

if finished:
    st.caption("Atendimento encerrado. Use “Nova conversa” para começar novamente.")

prompt = st.chat_input(
    "Escreva sua mensagem…",
    key="chat",
    disabled=finished or not configured,
    max_chars=4000,
    submit_mode="disable",
)
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"), st.spinner("Um instante…"):
        response = asyncio.run(conversation.send(prompt))
        st.write(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()
