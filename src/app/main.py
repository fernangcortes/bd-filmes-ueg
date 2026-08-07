"""Banco de Personagens CriaLab|UEG — página inicial."""
import streamlit as st

from db import contar, conectar

st.set_page_config(
    page_title="Banco de Personagens — CriaLab|UEG",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Banco de Personagens — CriaLab|UEG")
st.subheader("Do tema do seu filme às pessoas, locações, equipamentos e pesquisas da UEG")

st.markdown(
    """
Digite o **tema** de um programa/filme — ou anexe um **roteiro** — e o sistema
devolve, ranqueado e com a fonte de cada informação:

- 👤 **Personagens**: pesquisadoras e pesquisadores da UEG com contato institucional
- 📍 **Locações**: laboratórios com prédio, sala e câmpus
- 🔬 **Equipamentos** disponíveis
- 📚 **Pesquisas**: teses, dissertações e projetos de extensão para embasamento

Tudo construído exclusivamente sobre **fontes de dados abertas e verificadas**
da UEG e do ecossistema nacional de ciência aberta.
"""
)

st.divider()

# --- Status do sistema ---
st.markdown("### Status do sistema")
col1, col2, col3, col4 = st.columns(4)

banco_ok = conectar() is not None
col1.metric("Banco de dados", "🟢 no ar" if banco_ok else "🔴 fora")
col2.metric("Documentos", contar("documento") if banco_ok else "—")
col3.metric("Pessoas", contar("pessoa") if banco_ok else "—")
col4.metric("Laboratórios", contar("laboratorio") if banco_ok else "—")

if banco_ok:
    conn = conectar()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(embedding) FROM documento")
        _tot, _emb = cur.fetchone()
    conn.close()
    if _emb < _tot:
        st.caption(
            f"🧠 Busca inteligente: **{_emb:,} de {_tot:,}** documentos indexados "
            f"({_emb / _tot:.0%}) — continue em 🔄 Atualizar dados → Indexar embeddings.".replace(",", ".")
        )

if not banco_ok:
    st.warning(
        "O banco de dados não respondeu. Verifique se o **Docker Desktop** está "
        "aberto e feche/abra novamente o `iniciar.bat`. Seus dados anteriores "
        "permanecem guardados — nada se perde.",
        icon="⚠️",
    )
else:
    st.success(
        "Base em operação: teses e dissertações (BDTD), projetos de extensão e "
        "cargos (Dados Abertos GO, CC-BY), laboratórios (ueg.br) e produção "
        "científica global (OpenAlex, CC0) já coletados. "
        "O botão **🔄 Atualizar dados** re-roda todos os coletores com um clique."
    )

st.divider()
st.caption(
    "CriaLab|UEG — Laboratório de Pesquisas Criativas e Inovação em Audiovisual · "
    "UnU Goiânia-Laranjeiras · Dados pessoais tratados conforme a LGPD — veja a página "
    "🔒 Privacidade (LGPD) no menu lateral."
)
