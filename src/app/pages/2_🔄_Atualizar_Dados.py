"""Atualização da base — em construção (marcos M1–M3)."""
import streamlit as st

from db import conectar

st.set_page_config(page_title="Atualizar dados — Banco de Personagens", page_icon="🔄", layout="wide")

st.title("🔄 Atualizar dados")

st.info(
    "Em construção. Com um clique, esta página vai rodar os 4 coletores de dados "
    "abertos do MVP:\n\n"
    "- **BDTD/UEG** — teses e dissertações (OAI-PMH + REST, coleta incremental)\n"
    "- **Dados Abertos GO** — projetos de extensão, cargos e bens da UEG (CC-BY)\n"
    "- **Laboratórios ueg.br** — prédio, sala, equipamentos e contato (33 unidades)\n"
    "- **OpenAlex** — produção e pesquisadores UEG com ORCID (CC0)\n\n"
    "A primeira carga é completa; as seguintes trazem **só o que mudou** desde a "
    "última coleta. Um relatório ao final mostra o que entrou de novo em cada fonte."
)

st.markdown("### Fontes cadastradas")
conn = conectar()
if conn is None:
    st.warning("Banco de dados fora do ar — abra o Docker Desktop e reinicie o app.", icon="⚠️")
else:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT codigo, tipo, url_base, licenca, "
            "COALESCE(to_char(ultima_coleta, 'DD/MM/YYYY HH24:MI'), 'nunca coletado') "
            "FROM fonte ORDER BY codigo"
        )
        linhas = cur.fetchall()
    conn.close()
    st.dataframe(
        linhas,
        column_config={
            0: "Fonte",
            1: "Tipo",
            2: "Endereço",
            3: "Licença",
            4: "Última coleta",
        },
        use_container_width=True,
        hide_index=True,
    )
