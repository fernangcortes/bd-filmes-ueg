"""Atualização da base — coletores de dados abertos com 1 clique.

M1: BDTD/UEG (REST discover, varredura completa idempotente).
Próximos marcos: CKAN, laboratórios, OpenAlex.
"""
import sys
from pathlib import Path

import streamlit as st

from db import conectar

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do repo

st.set_page_config(page_title="Atualizar dados — Banco de Personagens", page_icon="🔄", layout="wide")

st.title("🔄 Atualizar dados")

st.markdown(
    "Com um clique, o sistema coleta as fontes de dados abertas do MVP. "
    "As cópias brutas ficam guardadas localmente (data lake) — se uma fonte falhar, "
    "seus dados anteriores continuam intactos."
)

# ---------------- Fontes cadastradas ----------------
st.markdown("### Fontes cadastradas")
conn = conectar()
if conn is None:
    st.warning("Banco de dados fora do ar — abra o Docker Desktop e reinicie o app.", icon="⚠️")
    st.stop()

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
    column_config={0: "Fonte", 1: "Tipo", 2: "Endereço", 3: "Licença", 4: "Última coleta"},
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ---------------- Coletor BDTD/UEG ----------------
st.markdown("### 📚 BDTD/UEG — teses e dissertações")
st.caption(
    "Varredura completa via REST discover (DSpace 10), com metadados ricos: "
    "autor, orientador (com Lattes), programa, câmpus e área CNPq. "
    "No servidor atual, a carga completa leva ~10–15 minutos; as próximas "
    "atualizações serão incrementais quando o OAI-PMH local sair da migração."
)

if st.button("▶️ Atualizar BDTD/UEG agora", type="primary"):
    from src.coleta.bdtd import executar

    barra = st.progress(0.0)
    area = st.status("Coletando BDTD/UEG…", expanded=True)

    def progresso(msg: str, frac: float | None) -> None:
        area.write(msg)
        if frac is not None:
            barra.progress(min(max(frac, 0.0), 1.0))

    try:
        stats = executar(progresso=progresso)
    except Exception as exc:
        area.update(label="Falha na coleta", state="error")
        st.error(
            f"A fonte não respondeu como esperado ({exc.__class__.__name__}). "
            "Seus dados anteriores continuam intactos — tente novamente mais tarde."
        )
    else:
        area.update(label="Coleta concluída ✅", state="complete", expanded=False)
        st.success(
            f"**{stats['documentos']} documentos** processados nesta rodada · "
            f"**{stats['pessoas_total']} pessoas** na base · "
            f"OAI-PMH local: {stats['oai']}"
        )

st.divider()
st.info(
    "Próximos coletores (marcos M2 e M3): **Dados Abertos GO** (projetos de extensão, "
    "cargos, bens), **laboratórios ueg.br** (prédio/sala/equipamento) e **OpenAlex** "
    "(produção + ORCID)."
)
