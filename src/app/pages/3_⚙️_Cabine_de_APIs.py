"""Cabine de APIs — configuração mínima funcional (antecipada para o M5).

O gerente cola as chaves aqui; elas vão para config/apis.yaml — arquivo LOCAL,
fora do git (ver apis.example.yaml). Nada de chave no código nem no GitHub.

Versão completa (M6) terá estimativa de custo por busca, reranqueador e
busca web; esta cobre o que o M5 precisa: o LLM de entendimento.
"""
import sys
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do repo

from src.llm.cliente import PROVEDORES_NUVEM, ClienteLLM, carregar_config, obter_cliente  # noqa: E402

st.set_page_config(page_title="Cabine de APIs — Banco de Personagens", page_icon="⚙️", layout="wide")

st.title("⚙️ Cabine de APIs")
st.markdown(
    "Cole aqui as chaves dos serviços pagos. Elas ficam **só neste computador** "
    "(arquivo `config/apis.yaml`, que nunca vai para o GitHub). Sem chave, o "
    "sistema continua funcionando no modo básico, sem IA."
)

config = carregar_config()
cfg_llm = config.get("llm", {})

ROTULOS_PROVEDOR = {
    "deepseek": "💰 DeepSeek — recomendado: pt-BR excelente, centavos por busca",
    "kimi": "💰 Kimi — contexto longo, bom para roteiros grandes",
    "openrouter": "💎 OpenRouter — acesso a Claude/GPT, melhor qualidade",
    "ollama": "🟢 Ollama local — grátis, mas lento demais nesta máquina",
}

st.markdown("### 🧠 IA de entendimento (leitura de tema/roteiro)")

opcoes = list(ROTULOS_PROVEDOR)
atual = cfg_llm.get("provedor_padrao", "deepseek")
provedor = st.radio(
    "Provedor padrão",
    options=opcoes,
    format_func=lambda p: ROTULOS_PROVEDOR[p],
    index=opcoes.index(atual) if atual in opcoes else 0,
)

st.caption(
    "Custo estimado (DeepSeek): **menos de R$ 0,10 por análise de roteiro** — "
    "estimativa aproximada; o valor real aparece no painel do provedor. "
    "Cada clique em “Analisar pedido” no 🧭 Assistente faz 1 chamada de IA."
)

chaves = {}
for nome, info in PROVEDORES_NUVEM.items():
    valor_atual = cfg_llm.get(nome, {}).get("api_key", "")
    chaves[nome] = st.text_input(
        f"Chave — {info['rotulo']}",
        value=valor_atual,
        type="password",
        placeholder="cole a chave aqui (começa com sk-…)",
        key=f"key_{nome}",
    )

col_salvar, col_testar = st.columns(2)

if col_salvar.button("💾 Salvar configuração", type="primary", use_container_width=True):
    novo = dict(config)
    llm = dict(cfg_llm)
    llm["provedor_padrao"] = provedor
    for nome in PROVEDORES_NUVEM:
        entrada = dict(llm.get(nome, {}))
        entrada["api_key"] = chaves[nome]
        entrada.setdefault("modelo", PROVEDORES_NUVEM[nome]["modelo_padrao"])
        llm[nome] = entrada
    llm.setdefault("ollama", {"base_url": "http://localhost:11434", "modelo": "qwen2.5:14b"})
    novo["llm"] = llm
    caminho = Path(__file__).resolve().parents[3] / "config" / "apis.yaml"
    caminho.write_text(
        "# Cabine de APIs — gerado pela interface. NÃO versionar (está no .gitignore).\n"
        + yaml.safe_dump(novo, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    obter_cliente(recarregar=True)
    st.success("Configuração salva neste computador. O 🧭 Assistente já pode usar a IA.")

if col_testar.button("🔌 Testar conexão", use_container_width=True):
    cliente = ClienteLLM(config={"llm": {**cfg_llm, "provedor_padrao": provedor,
                                         **{n: {**cfg_llm.get(n, {}), "api_key": chaves[n]}
                                            for n in PROVEDORES_NUVEM}}})
    ok, motivo = cliente.disponivel()
    (st.success if ok else st.error)(motivo)

st.divider()
st.markdown(
    "Como conseguir uma chave (2 minutos):\n"
    "1. **DeepSeek** (recomendado): crie conta em [platform.deepseek.com](https://platform.deepseek.com), "
    "carregue alguns dólares de crédito e gere uma chave em *API keys*;\n"
    "2. **Kimi**: [platform.moonshot.cn](https://platform.moonshot.cn) · "
    "**OpenRouter**: [openrouter.ai](https://openrouter.ai) (um cadastro dá acesso a vários modelos);\n"
    "3. Cole a chave acima, escolha o provedor padrão e salve."
)
