"""Cliente LLM do Banco de Personagens (M5).

Decisão do gerente (07/08/2026): **começar com modelos online (API)** — esta
máquina é lenta demais para IA local (Ollama fica como opção, não padrão).
Plano §7.3: DeepSeek (💰 padrão recomendado, pt-BR excelente) · Kimi (💰
contexto longo, roteiros grandes) · OpenRouter (💎 Claude/GPT).

Os três provedores de nuvem falam o protocolo OpenAI (chat/completions) —
um único código cobre todos. As chaves ficam em `config/apis.yaml`
(NUNCA no git — ver apis.example.yaml) e podem ser coladas na ⚙️ Cabine.

Se nada estiver configurado (ou a API falhar), o assistente cai para o modo
básico (heurístico) — o app nunca quebra por causa da IA.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config" / "apis.yaml"

TIMEOUT_RESPOSTA = 180  # roteiros longos; a resposta em si é pequena

# Endpoints no protocolo OpenAI (chat/completions)
PROVEDORES_NUVEM = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "modelo_padrao": "deepseek-chat",
        "rotulo": "DeepSeek (💰 custo-benefício)",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "modelo_padrao": "kimi-k2-0711-preview",
        "rotulo": "Kimi (💰 contexto longo)",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "modelo_padrao": "anthropic/claude-sonnet-4",
        "rotulo": "OpenRouter (💎 topo de linha)",
    },
}

OLLAMA_PADRAO = {"base_url": "http://localhost:11434", "modelo_padrao": "qwen2.5:14b"}


class LLMIndisponivel(Exception):
    """Provedor sem chave, fora do ar ou modelo ausente."""


def carregar_config() -> dict:
    """config/apis.yaml (local, fora do git). Sem arquivo = padrão de fábrica."""
    if not CONFIG.exists():
        return {}
    try:
        return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


class ClienteLLM:
    """Interface mínima de geração de texto, multi-provedor.

    Mesmos métodos para nuvem e Ollama: `disponivel()` e `gerar()`.
    """

    def __init__(self, config: dict | None = None):
        cfg_llm = (config if config is not None else carregar_config()).get("llm", {})
        self.provedor = os.getenv("BD_FILMES_LLM_PROVEDOR") or cfg_llm.get("provedor_padrao") or "deepseek"

        if self.provedor == "ollama":
            cfg = cfg_llm.get("ollama", {})
            self.base_url = (
                os.getenv("BD_FILMES_OLLAMA_HOST")
                or cfg.get("base_url")
                or OLLAMA_PADRAO["base_url"]
            ).rstrip("/")
            self.modelo = (
                os.getenv("BD_FILMES_OLLAMA_MODELO")
                or cfg.get("modelo")
                or OLLAMA_PADRAO["modelo_padrao"]
            )
            self.api_key = ""
            self.rotulo = f"Ollama local ({self.modelo})"
        else:
            info = PROVEDORES_NUVEM.get(self.provedor)
            if info is None:  # provedor desconhecido no yaml: cai para DeepSeek
                self.provedor = "deepseek"
                info = PROVEDORES_NUVEM["deepseek"]
            cfg = cfg_llm.get(self.provedor, {})
            self.base_url = cfg.get("base_url") or info["base_url"]
            self.modelo = cfg.get("modelo") or info["modelo_padrao"]
            self.api_key = os.getenv("BD_FILMES_LLM_API_KEY") or cfg.get("api_key", "")
            self.rotulo = f"{info['rotulo']} · {self.modelo}"

    # ---------------- sonda ----------------

    def disponivel(self) -> tuple[bool, str]:
        """(ok, motivo). Nuvem: chave válida via GET /models (não gasta tokens).
        Ollama: servidor no ar + modelo baixado."""
        if self.provedor == "ollama":
            return self._disponivel_ollama()
        if not self.api_key:
            return False, (
                f"Sem chave da {self.provedor}. Cole na ⚙️ Cabine de APIs "
                f"ou em config/apis.yaml (modelo: apis.example.yaml)."
            )
        try:
            r = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5,
            )
        except requests.RequestException:
            return False, f"{self.rotulo} inacessível (sem internet ou provedor fora do ar)."
        if r.status_code in (401, 403):
            return False, f"Chave da {self.provedor} recusada (HTTP {r.status_code}) — confira na Cabine."
        if r.status_code != 200:
            return False, f"{self.rotulo} respondeu HTTP {r.status_code}."
        return True, f"IA pronta: {self.rotulo}."

    def _disponivel_ollama(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
        except requests.RequestException:
            return False, (
                "Ollama fora do ar (não instalado ou desligado) — e esta máquina "
                "é lenta para IA local; prefira um provedor de nuvem na Cabine."
            )
        if r.status_code != 200:
            return False, f"Ollama respondeu HTTP {r.status_code}."
        modelos = [m.get("name", "") for m in r.json().get("models", [])]
        if not any(m == self.modelo or m.startswith(self.modelo.split(":")[0]) for m in modelos):
            return False, f"Modelo '{self.modelo}' não baixado no Ollama (ollama pull {self.modelo})."
        return True, f"IA local pronta ({self.modelo})."

    # ---------------- geração ----------------

    def gerar(self, prompt: str, sistema: str | None = None, temperatura: float = 0.2) -> str:
        """Gera texto. Lança LLMIndisponivel em qualquer falha — o chamador
        decide o fallback (nunca quebrar a experiência do usuário leigo)."""
        if self.provedor == "ollama":
            return self._gerar_ollama(prompt, sistema, temperatura)
        return self._gerar_nuvem(prompt, sistema, temperatura)

    def _gerar_nuvem(self, prompt: str, sistema: str | None, temperatura: float) -> str:
        if not self.api_key:
            raise LLMIndisponivel(f"Sem chave da {self.provedor} — configure na Cabine.")
        mensagens = ([{"role": "system", "content": sistema}] if sistema else []) + [
            {"role": "user", "content": prompt}
        ]
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.modelo, "messages": mensagens, "temperature": temperatura},
                timeout=TIMEOUT_RESPOSTA,
            )
        except requests.RequestException as exc:
            raise LLMIndisponivel(f"{self.rotulo} inacessível: {exc}") from exc
        if r.status_code != 200:
            raise LLMIndisponivel(f"{self.rotulo} HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMIndisponivel(f"Resposta inesperada da {self.provedor}: {exc}") from exc

    def _gerar_ollama(self, prompt: str, sistema: str | None, temperatura: float) -> str:
        corpo = {
            "model": self.modelo,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperatura},
        }
        if sistema:
            corpo["system"] = sistema
        try:
            r = requests.post(f"{self.base_url}/api/generate", json=corpo, timeout=TIMEOUT_RESPOSTA)
        except requests.RequestException as exc:
            raise LLMIndisponivel(f"Ollama inacessível: {exc}") from exc
        if r.status_code != 200:
            raise LLMIndisponivel(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("response", "")


_cliente: ClienteLLM | None = None


def obter_cliente(recarregar: bool = False) -> ClienteLLM:
    """Singleton leve. A Cabine chama com recarregar=True após salvar chaves."""
    global _cliente
    if _cliente is None or recarregar:
        _cliente = ClienteLLM()
    return _cliente
