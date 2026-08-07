"""Atualização da base — coletores de dados abertos com 1 clique.

M1: BDTD/UEG (REST discover, varredura completa idempotente).
M2: CKAN Dados Abertos GO (extensão/cargos/bens, CC-BY) + laboratórios ueg.br.
M3: OpenAlex (works + authors, CC0) — âncora ORCID da consolidação.
M4: indexação de embeddings locais (busca por significado) — retomável.
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

# ---------------- Coletor CKAN Dados Abertos GO ----------------
st.markdown("### 🏛️ Dados Abertos GO — extensão, cargos e bens")
st.caption(
    "API CKAN do portal Dados Abertos de Goiás (licença CC-BY): projetos/ações de "
    "extensão (tema ↔ coordenador ↔ câmpus), ocupantes de cargos de direção "
    "(nome, Lattes, e-mail funcional) e snapshots brutos de bens imóveis e móveis. "
    "Leva cerca de 1 minuto."
)

if st.button("▶️ Atualizar Dados Abertos GO agora", type="primary"):
    from src.coleta.ckan import executar

    barra = st.progress(0.0)
    area = st.status("Coletando Dados Abertos GO…", expanded=True)

    def progresso_ckan(msg: str, frac: float | None) -> None:
        area.write(msg)
        if frac is not None:
            barra.progress(min(max(frac, 0.0), 1.0))

    try:
        stats = executar(progresso=progresso_ckan)
    except Exception as exc:
        area.update(label="Falha na coleta", state="error")
        st.error(
            f"A fonte não respondeu como esperado ({exc.__class__.__name__}). "
            "Seus dados anteriores continuam intactos — tente novamente mais tarde."
        )
    else:
        area.update(label="Coleta concluída ✅", state="complete", expanded=False)
        st.success(
            f"**{stats['projetos']} projetos/ações de extensão** · "
            f"**{stats['ocupantes']} ocupantes de cargos** na base · "
            f"**{stats['coordenadores_vinculados']} coordenadores** já vinculados a pessoas · "
            f"{stats['snapshots']} snapshots de bens no data lake"
        )
        st.caption("Fonte: Dados Abertos Goiás (CC-BY) — crédito obrigatório exibido nos resultados.")

st.divider()

# ---------------- Coletor Laboratórios ueg.br ----------------
st.markdown("### 🔬 Laboratórios ueg.br — locações e equipamentos")
st.caption(
    "Varredura educada (1 requisição/segundo, identificada) pelos subsites das "
    "33 unidades e 8 câmpus da UEG: fichas de laboratório com prédio, sala, "
    "equipamentos e contato do responsável. A primeira carga leva ~15–30 minutos; "
    "as seguintes são mais rápidas (só atualiza o que mudou)."
)

if st.button("▶️ Atualizar laboratórios agora", type="primary"):
    from src.coleta.laboratorios import executar

    barra = st.progress(0.0)
    area = st.status("Coletando laboratórios ueg.br…", expanded=True)

    def progresso_labs(msg: str, frac: float | None) -> None:
        area.write(msg)
        if frac is not None:
            barra.progress(min(max(frac, 0.0), 1.0))

    try:
        stats = executar(progresso=progresso_labs)
    except Exception as exc:
        area.update(label="Falha na coleta", state="error")
        st.error(
            f"O portal ueg.br não respondeu como esperado ({exc.__class__.__name__}). "
            "Seus dados anteriores continuam intactos — tente novamente mais tarde."
        )
    else:
        area.update(label="Coleta concluída ✅", state="complete", expanded=False)
        st.success(
            f"**{stats['fichas']} fichas de laboratório** em "
            f"**{stats['unidades']} unidades** · "
            f"**{stats['responsaveis']} responsáveis** vinculados · "
            f"{stats['unidades_sem_pagina']} unidades sem página de laboratórios"
        )

st.divider()

# ---------------- Coletor OpenAlex ----------------
st.markdown("### 🌐 OpenAlex — produção científica global da UEG")
st.caption(
    "API aberta (CC0): ~10 mil artigos/trabalhos da UEG com DOI, resumo e tópicos, "
    "e os pesquisadores com última afiliação UEG — cada um com ORCID, a chave que "
    "consolida a mesma pessoa entre BDTD, Dados Abertos e OpenAlex. "
    "Leva cerca de 5 minutos."
)

if st.button("▶️ Atualizar OpenAlex agora", type="primary"):
    from src.coleta.openalex import executar

    barra = st.progress(0.0)
    area = st.status("Coletando OpenAlex…", expanded=True)

    def progresso_oa(msg: str, frac: float | None) -> None:
        area.write(msg)
        if frac is not None:
            barra.progress(min(max(frac, 0.0), 1.0))

    try:
        stats = executar(progresso=progresso_oa)
    except Exception as exc:
        area.update(label="Falha na coleta", state="error")
        st.error(
            f"A API da OpenAlex não respondeu como esperado ({exc.__class__.__name__}). "
            "Seus dados anteriores continuam intactos — tente novamente mais tarde."
        )
    else:
        area.update(label="Coleta concluída ✅", state="complete", expanded=False)
        st.success(
            f"**{stats['works']} works** processados · "
            f"**{stats['autores_ueg_vinculados']} autoria(s) UEG** vinculadas · "
            f"**{stats['autores']} pesquisadores** com afiliação UEG "
            f"({stats['com_orcid']} com ORCID) · "
            f"base agora com **{stats['pessoas_total']} pessoas** "
            f"({stats['pessoas_com_orcid']} com ORCID)"
        )
        st.caption("Fonte: OpenAlex (CC0).")

st.divider()

# ---------------- Indexação de embeddings (M4) ----------------
st.markdown("### 🧠 Indexar embeddings — preparar a busca inteligente")
st.caption(
    "Transforma cada documento num vetor de significado (modelo multilíngue local, "
    "roda no próprio computador, sem enviar nada para a internet). É o que faz a "
    "busca da página 🔎 encontrar por **tema**, e não só por palavra exata. "
    "A primeira carga é a mais demorada (~1–2 h para os ~13 mil registros); "
    "pode parar a qualquer momento e continuar depois — ela sempre segue de onde parou."
)

from src.banco.vectorstore import PgVectorStore

loja_prog = PgVectorStore()
try:
    progresso_idx = loja_prog.progresso_indexacao()
finally:
    loja_prog.close()

ROTULOS_TABELA = {
    "documento": "Documentos (teses, artigos, projetos, fichas)",
    "laboratorio": "Laboratórios",
    "projeto_extensao": "Projetos de extensão",
}
total_geral = sum(t for t, _ in progresso_idx.values())
feitos_geral = sum(c for _, c in progresso_idx.values())
linhas_idx = [
    (ROTULOS_TABELA[t], c, t_, f"{c / t_:.0%}" if t_ else "—")
    for t, (t_, c) in progresso_idx.items()
]
st.dataframe(
    linhas_idx,
    column_config={0: "Coleção", 1: "Indexados", 2: "Total", 3: "%"},
    use_container_width=True,
    hide_index=True,
)
st.progress(feitos_geral / max(total_geral, 1), text=f"{feitos_geral:,} de {total_geral:,} registros indexados".replace(",", "."))

reindexar = st.checkbox(
    "Reindexar tudo do zero (apaga os vetores existentes — só use se orientado)",
    value=False,
)

if st.button("▶️ Indexar embeddings agora", type="primary"):
    from src.busca.indexar import executar, zerar_embeddings

    if reindexar:
        with st.spinner("Apagando vetores antigos…"):
            zerar_embeddings()

    barra = st.progress(0.0)
    area = st.status("Indexando embeddings…", expanded=True)

    def progresso_emb(msg: str, frac: float | None) -> None:
        area.write(msg)
        if frac is not None:
            barra.progress(min(max(frac, 0.0), 1.0))

    try:
        stats = executar(progresso=progresso_emb)
    except Exception as exc:
        area.update(label="Falha na indexação", state="error")
        st.error(
            f"Não consegui concluir a indexação ({exc.__class__.__name__}). "
            "O que já foi indexado permanece salvo — tente novamente."
        )
    else:
        if stats["concluido"]:
            area.update(label="Indexação concluída ✅", state="complete", expanded=False)
            st.success(
                f"**{stats['processados_nesta_rodada']} registros** indexados nesta rodada · "
                f"**{stats['pendentes']} pendentes** · "
                f"velocidade média: {stats['velocidade']} registros/s · "
                "a página 🔎 Busca está pronta!"
            )
        else:
            area.update(label="Rodada concluída (parcial)", state="complete", expanded=False)
            st.info(
                f"**{stats['processados_nesta_rodada']} registros** indexados nesta rodada · "
                f"restam **{stats['pendentes']}**. Clique no botão de novo para continuar "
                "— a indexação segue de onde parou."
            )
        st.rerun()

st.divider()
st.info(
    "Marco M4 concluído: as 4 fontes coletam com 1 clique e a busca híbrida "
    "(significado + palavras) está ativa na página 🔎 Busca. Próximo passo (M5): "
    "assistente de refinamento com tags inteligentes e upload de roteiro."
)
