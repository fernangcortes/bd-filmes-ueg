"""Cabine de APIs — em construção (marco M6)."""
import streamlit as st

st.set_page_config(page_title="Cabine de APIs — Banco de Personagens", page_icon="⚙️", layout="wide")

st.title("⚙️ Cabine de APIs")

st.info(
    "Em construção. Aqui você escolhe, para cada função do sistema, o provedor "
    "com o melhor equilíbrio para o seu caso — com ajuda das etiquetas:\n\n"
    "- 🟢 **local/grátis** — roda no seu computador, sem custo e com privacidade total\n"
    "- 💰 **custo-benefício** — qualidade alta por centavos por busca\n"
    "- 💎 **topo de linha** — a melhor qualidade disponível, custo maior\n\n"
    "| Função | 🟢 Local/grátis | 💰 Custo-benefício | 💎 Topo de linha |\n"
    "|---|---|---|---|\n"
    "| IA (leitura de roteiro e resumo) | Ollama | DeepSeek · Kimi | OpenRouter (Claude/GPT) |\n"
    "| Embeddings (vetores de busca) | bge-m3 local | OpenAI · Voyage | — |\n"
    "| Reranqueador | bge-reranker local | Cohere | — |\n"
    "| Busca web | Brave (2.000/mês grátis) | Tavily · Google | SerpAPI |\n\n"
    "O sistema já vem configurado **100% local e gratuito** — nenhuma chave é "
    "necessária para começar. Antes de cada busca paga, o custo estimado é exibido."
)
