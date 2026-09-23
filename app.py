import asyncio
from pathlib import Path

import streamlit as st

from banco_agil.bootstrap import create_conversation
from banco_agil.config import Settings
from banco_agil.models.errors import BankingError
from banco_agil.models.state import AgentType, ConversationStatus
from banco_agil.presentation import WELCOME
from banco_agil.repositories.bootstrap import reset_demo_data

st.set_page_config(page_title="Banco Ágil | Atendimento", page_icon=":material/account_balance:")
st.title("Banco Ágil")
st.caption("Converse com a Lia · Seu atendimento, em uma conversa.")
st.caption("Demonstração com dados fictícios. As mensagens do chat são processadas pela Groq.")

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
            "content": WELCOME,
        }
    ],
)
conversation = st.session_state.conversation
finished = conversation.flow.state.status == ConversationStatus.FINISHED
configured = bool(settings.groq_api_key.get_secret_value())

with st.sidebar:
    st.subheader("Lia · Banco Ágil")
    if conversation.flow.state.authenticated:
        st.success("Identidade confirmada")
    else:
        st.caption("Identidade ainda não confirmada")
    st.markdown(
        "Estou aqui para ajudar com:\n\n"
        "- **Seu limite de crédito**\n- **Pedidos de aumento**\n- **Cotações em reais**"
    )
    st.caption("Demonstração com clientes fictícios.")
    with st.expander("Dados para experimentar"):
        st.write("**Ana** · CPF: 000.000.000-01 · Nascimento: 15/01/1990")
        st.write("**Bruno** · CPF: 000.000.000-02 · Nascimento: 20/05/1985")
    if st.button("Nova conversa", key="request_new_conversation", icon=":material/add:"):
        st.session_state.pending_new_conversation = True

    if st.session_state.get("pending_new_conversation", False):
        st.warning("A conversa atual será encerrada. Os dados persistidos não serão restaurados.")
        with st.container(horizontal=True):
            if st.button("Confirmar", key="confirm_new_conversation", type="primary"):
                st.session_state.pop("conversation", None)
                st.session_state.pop("messages", None)
                st.session_state.pending_new_conversation = False
                st.rerun()
            if st.button("Cancelar", key="cancel_new_conversation"):
                st.session_state.pending_new_conversation = False
                st.rerun()

    if st.button(
        "Restaurar dados da demonstração",
        key="request_demo_reset",
        icon=":material/restart_alt:",
    ):
        st.session_state.pending_demo_reset = True

    if st.session_state.get("pending_demo_reset", False):
        st.warning("Isso restaura limites, scores e solicitações dos clientes fictícios.")
        with st.container(horizontal=True):
            if st.button("Confirmar", key="confirm_demo_reset", type="primary"):
                try:
                    reset_demo_data(Path(__file__).resolve().parent / "data", settings.data_dir)
                except (BankingError, OSError):
                    st.error(
                        "Não foi possível concluir a restauração. Alguns dados podem ter sido "
                        "restaurados; tente novamente antes de continuar."
                    )
                    st.stop()
                st.session_state.pop("conversation", None)
                st.session_state.pop("messages", None)
                st.session_state.pending_demo_reset = False
                st.rerun()
            if st.button("Cancelar", key="cancel_demo_reset"):
                st.session_state.pending_demo_reset = False
                st.rerun()
    if st.button("Encerrar atendimento", key="end_conversation", disabled=finished):
        reply = asyncio.run(conversation.send("encerrar"))
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

if not configured:
    st.info("Para ativar a conversa, configure GROQ_API_KEY no arquivo .env e recarregue a página.")

for message in st.session_state.messages:
    is_lia = message["role"] == "assistant"
    with st.chat_message(
        "Lia" if is_lia else "user", avatar=":material/support_agent:" if is_lia else None
    ):
        if is_lia:
            st.caption("Lia · Banco Ágil")
            progress = message.get("interview_progress")
            if progress is not None:
                st.caption(
                    f"Entrevista de crédito · etapa {progress['current']} de {progress['total']}"
                )
                st.progress(progress["completed"] / progress["total"])
        st.markdown(message["content"])

if finished:
    st.caption("Atendimento encerrado. Use “Nova conversa” para começar novamente.")

quick_action = None
if (
    not finished
    and configured
    and conversation.flow.state.current_agent == AgentType.TRIAGE
    and (conversation.flow.state.authenticated or len(st.session_state.messages) == 1)
):
    with st.container(horizontal=True):
        for label, text in (
            ("Consultar limite", "Quero consultar meu limite"),
            ("Pedir aumento", "Quero pedir um aumento de limite"),
            ("Ver cotação", "Quero consultar uma cotação"),
        ):
            if st.button(label, key=f"quick_{label}"):
                quick_action = text

typed_prompt = st.chat_input(
    "Conte para a Lia como ela pode ajudar…",
    key="chat",
    disabled=finished or not configured,
    max_chars=4000,
    submit_mode="disable",
)
prompt = quick_action or typed_prompt
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    was_interview = conversation.flow.state.current_agent == AgentType.INTERVIEW
    with (
        st.chat_message("Lia", avatar=":material/support_agent:"),
        st.spinner("A Lia está cuidando disso…"),
    ):
        st.caption("Lia · Banco Ágil")
        response = asyncio.run(conversation.send(prompt))
        interview = conversation.flow.state.interview
        progress = None
        if (
            conversation.flow.state.status == ConversationStatus.ACTIVE
            and interview is not None
            and (was_interview or conversation.flow.state.current_agent == AgentType.INTERVIEW)
        ):
            completed = interview.completed_fields()
            total = interview.total_fields()
            progress = {
                "completed": completed,
                "current": total if interview.completed else min(completed + 1, total),
                "total": total,
            }
            st.caption(
                f"Entrevista de crédito · etapa {progress['current']} de {progress['total']}"
            )
            st.progress(progress["completed"] / progress["total"])
        st.markdown(response)
    for message in st.session_state.messages:
        message.pop("interview_progress", None)
    assistant_message = {"role": "assistant", "content": response}
    if progress is not None:
        assistant_message["interview_progress"] = progress
    st.session_state.messages.append(assistant_message)
    st.rerun()
