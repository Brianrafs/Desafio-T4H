"""Banco Ágil: atendimento conversacional com domínio determinístico."""

import os

# Desabilitar telemetria antes de importar CrewAI ou seus instrumentadores.
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["CREWAI_TELEMETRY_ENABLED"] = "false"
