"""Busca por tema — motor híbrido do M4 (vetorial e5-large + lexical + filtros SQL).

Tema → embedding local → candidatos vetoriais (pgvector) + candidatos lexicais
(tsvector em português) → fusão RRF → filtros (tipo, unidade/câmpus, ano) →
resultados ranqueados, cada um com o link da fonte original.

Pessoas com optout=true (LGPD) nunca aparecem nos resultados.
"""
import sys
from pathlib import Path

import streamlit as st

from db import conectar

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do repo

st.set_page_config(page_title="Busca — Banco de Personagens", page_icon="🔎", layout="wide")

st.title("🔎 Busca por tema")
st.markdown(
    "Digite o **tema** do seu programa/filme. O sistema procura no acervo da UEG "
    "(teses, dissertações, artigos, projetos de extensão e laboratórios) por "
    "**significado**, não só por palavra exata — e devolve tudo ranqueado, "
    "com o link da fonte de cada item."
)

ROTULOS_TIPO = {
    "tese": "Tese",
    "dissertacao": "Dissertação",
    "work": "Artigo/trabalho (OpenAlex)",
    "projeto_extensao": "Projeto de extensão",
    "ficha_lab": "Laboratório/locação",
}
ROTULOS_FONTE = {
    "tese": "BDTD/UEG",
    "dissertacao": "BDTD/UEG",
    "work": "OpenAlex (CC0)",
    "projeto_extensao": "Dados Abertos Goiás (CC-BY)",
    "ficha_lab": "ueg.br",
}

# ---------------- pré-checagem: índice pronto? ----------------
conn = conectar()
if conn is None:
    st.warning("Banco de dados fora do ar — abra o Docker Desktop e reinicie o app.", icon="⚠️")
    st.stop()

with conn.cursor() as cur:
    cur.execute("SELECT count(*), count(embedding) FROM documento")
    total_docs, com_embedding = cur.fetchone()
    cur.execute(
        "SELECT DISTINCT coalesce(metadados->>'campus', metadados->>'unidade', "
        "metadados->>'dc.publisher.department') FROM documento "
        "WHERE coalesce(metadados->>'campus', metadados->>'unidade', "
        "metadados->>'dc.publisher.department') IS NOT NULL ORDER BY 1"
    )
    unidades = [r[0] for r in cur.fetchall()]
conn.close()

if com_embedding == 0:
    st.warning(
        "A busca ainda não foi indexada. Vá até **🔄 Atualizar dados** e rode "
        "**“Indexar embeddings”** uma vez (a primeira carga é a mais demorada; "
        "pode parar e continuar quando quiser).",
        icon="⚠️",
    )
    st.stop()

if com_embedding < total_docs:
    st.caption(
        f"ℹ️ Índice em montagem: **{com_embedding:,} de {total_docs:,}** documentos "
        f"indexados ({com_embedding / total_docs:.0%}). Os resultados já funcionam, "
        "mas a cobertura ainda é parcial.".replace(",", ".")
    )

# ---------------- entrada e filtros ----------------
consulta = st.text_input(
    "Tema da pesquisa",
    placeholder='Ex.: "Cerrado", "águas de Goiás", "saberes tradicionais"…',
)

with st.expander("Filtros (opcional)", expanded=False):
    col1, col2 = st.columns(2)
    tipos = col1.multiselect(
        "Tipo de material",
        options=list(ROTULOS_TIPO),
        format_func=lambda t: ROTULOS_TIPO[t],
        default=list(ROTULOS_TIPO),
    )
    unidade = col2.selectbox("Unidade/câmpus", options=["Todas"] + unidades)
    col3, col4, col5 = st.columns([1, 1, 1])
    anos = col3.slider("Período (ano)", 1960, 2030, (1960, 2030))
    limite = col4.slider("Resultados por seção", 5, 30, 10)
    col5.write("")
    col5.write("")

disparar = st.button("🔍 Pesquisar", type="primary", use_container_width=True)

if disparar and not consulta.strip():
    st.warning("Digite um tema para pesquisar.", icon="✏️")
    st.stop()

if disparar:
    from src.banco.vectorstore import FiltrosBusca
    from src.busca.hibrida import buscar_agrupada

    filtros = FiltrosBusca(
        tipos=tipos or None,
        unidade=None if unidade == "Todas" else unidade,
        ano_min=None if anos[0] <= 1960 else anos[0],
        ano_max=None if anos[1] >= 2030 else anos[1],
    )

    with st.spinner("Pesquisando no acervo da UEG…"):
        try:
            resposta = buscar_agrupada(consulta.strip(), filtros=filtros, limite_por_grupo=limite)
        except Exception as exc:
            st.error(
                f"Não consegui concluir a busca ({exc.__class__.__name__}). "
                "Se o modelo ainda está sendo baixado/carregado, tente de novo em instantes."
            )
            st.stop()

    total_itens = sum(len(lista) for lista in resposta.grupos.values())
    st.markdown(
        f"**{total_itens} resultados** para *\"{resposta.consulta}\"* "
        f"em {resposta.segundos:.1f} s"
    )
    if total_itens == 0:
        st.info(
            "Nada encontrado com esses filtros. Tente ampliar o período, "
            "trocar a unidade ou usar outras palavras no tema."
        )
        st.stop()

    titulos_grupo = {
        "pesquisas": "📚 Pesquisas (teses, dissertações e artigos)",
        "extensao": "🏗️ Projetos de extensão",
        "laboratorios": "🔬 Laboratórios e locações",
    }
    for chave, titulo_grupo in titulos_grupo.items():
        itens = resposta.grupos.get(chave, [])
        if not itens:
            continue
        st.markdown(f"### {titulo_grupo}")
        for r in itens:
            with st.container(border=True):
                topo = st.columns([5, 1])
                topo[0].markdown(f"**{r.titulo}**")
                topo[1].markdown(f"`{r.similaridade:.2f}` ⭐")
                badges = [f"`{ROTULOS_TIPO.get(r.tipo, r.tipo)}`"]
                if r.ano:
                    badges.append(f"`{r.ano}`")
                if r.unidade:
                    badges.append(f"`{r.unidade}`")
                st.caption(" ".join(badges) + f"  ·  Fonte: {ROTULOS_FONTE.get(r.tipo, '')}")
                if r.trecho:
                    st.write(r.trecho + ("…" if len(r.trecho) >= 420 else ""))
                pessoas = resposta.pessoas_por_documento.get(r.id, [])
                if pessoas:
                    partes = []
                    for p in pessoas:
                        contato = f" ({p.papel}" + (f" · {p.email}" if p.email else "") + ")"
                        partes.append(f"**{p.nome}**{contato}")
                    st.markdown("👤 " + " · ".join(partes))
                if r.url:
                    st.link_button("🔗 Abrir na fonte", r.url)

    st.caption(
        "Relevância ⭐ = similaridade de significado (0–1) entre o tema e o documento. "
        "O ranking combina significado (vetorial) + palavras do texto (lexical). "
        "Buscas são registradas em log de auditoria para melhoria do sistema."
    )
