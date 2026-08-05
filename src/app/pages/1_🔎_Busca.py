"""Busca por tema / roteiro — em construção (marcos M4–M6)."""
import streamlit as st

st.set_page_config(page_title="Busca — Banco de Personagens", page_icon="🔎", layout="wide")

st.title("🔎 Busca por tema")
st.info(
    "Em construção. Aqui você vai poder:\n\n"
    "1. **Digitar um tema** (ex.: \"Cerrado\") **ou anexar um roteiro** (PDF/TXT/DOCX);\n"
    "2. Refinar a pesquisa num **assistente passo a passo** — tags normais, "
    "tags inteligentes sugeridas pela IA e um chat de ajuste;\n"
    "3. Receber **personagens, locações, equipamentos e pesquisas** ranqueados, "
    "com a fonte de cada item;\n"
    "4. Ler um **resumo final da IA** destacando os pesquisadores e por que cada um "
    "se encaixa em cada assunto;\n"
    "5. Ampliar com **busca web** (notícias, artigos, documentos) quando quiser, "
    "pelo provedor escolhido na ⚙️ Cabine de APIs."
)
