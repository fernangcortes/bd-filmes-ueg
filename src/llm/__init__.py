"""Clientes de LLM do Banco de Personagens (M5).

Padrão do plano (§7.3): LLM local via Ollama — grátis, privado.
A Cabine de APIs (M6) adicionará provedores pagos (DeepSeek/Kimi/OpenRouter).
"""
from src.llm.cliente import ClienteLLM, LLMIndisponivel, obter_cliente

__all__ = ["ClienteLLM", "LLMIndisponivel", "obter_cliente"]
