"""Assistente inteligente (M5 — plano §7.1 estágios 1–2).

Fluxo em 3 passos para o usuário leigo:
  1. Conte o que procura: tema curto OU roteiro anexado (PDF/TXT/DOCX);
  2. Revise o que o sistema entendeu: sinopse, tags inteligentes (liga/desliga),
     sub-consultas e filtros — com chat refinador ("quero mais X, menos Y");
  3. Dispare a busca: cada sub-consulta roda o motor híbrido do M4
     (buscar_agrupada) e os resultados vêm agrupados por assunto.

Motor de entendimento: IA local (Ollama — §7.3) quando disponível; caso
contrário, modo básico (heurístico) — o assistente nunca fica fora do ar.
Roteiros anexados vivem apenas na sessão (nada é gravado em disco — LGPD).
"""
import sys
from pathlib import Path

import streamlit as st

from db import conectar

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # raiz do repo

from src.busca.entendimento import PacoteBusca, analisar          # noqa: E402
from src.busca.roteiro import EXTENSOES_ACEITAS, RoteiroInvalido, extrair_texto  # noqa: E402

st.set_page_config(page_title="Assistente — Banco de Personagens", page_icon="🧭", layout="wide")

st.title("🧭 Assistente de busca")
st.markdown(
    "Descreva o programa/filme com suas palavras **ou anexe o roteiro**. "
    "Eu quebro o pedido em assuntos, você revisa e só então eu pesquiso no "
    "acervo da UEG — cada assunto com seus personagens, pesquisas e locações."
)

ROTULOS_TIPO = {
    "tese": "Tese",
    "dissertacao": "Dissertação",
    "work": "Artigo/trabalho (OpenAlex)",
    "projeto_extensao": "Projeto de extensão",
    "ficha_lab": "Laboratório/locação",
}

# ---------------- pré-checagem (mesma da busca simples) ----------------
conn = conectar()
if conn is None:
    st.warning("Banco de dados fora do ar — abra o Docker Desktop e reinicie o app.", icon="⚠️")
    st.stop()

with conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM documento WHERE embedding IS NOT NULL")
    if cur.fetchone()[0] == 0:
        st.warning(
            "A busca ainda não foi indexada. Vá até **🔄 Atualizar dados** e rode "
            "**“Indexar embeddings”** uma vez.",
            icon="⚠️",
        )
        st.stop()
    cur.execute(
        "SELECT DISTINCT coalesce(metadados->>'campus', metadados->>'unidade', "
        "metadados->>'dc.publisher.department') FROM documento "
        "WHERE coalesce(metadados->>'campus', metadados->>'unidade', "
        "metadados->>'dc.publisher.department') IS NOT NULL ORDER BY 1"
    )
    unidades = [r[0] for r in cur.fetchall()]
conn.close()

# ---------------- passo 1: entrada ----------------
st.markdown("### 1️⃣ Conte o que você procura")
modo = st.radio(
    "Como quer começar?",
    options=["tema", "roteiro"],
    format_func=lambda m: "💬 Por tema (uma frase)" if m == "tema" else "📄 Anexando um roteiro (PDF/TXT/DOCX)",
    horizontal=True,
)

entrada_texto = ""
if modo == "tema":
    entrada_texto = st.text_input(
        "Tema",
        placeholder='Ex.: "documentário sobre o Cerrado e saberes tradicionais de Goiás"…',
    )
else:
    arquivo = st.file_uploader(
        "Roteiro (fica só nesta sessão — nada é salvo no computador)",
        type=[e.lstrip(".") for e in EXTENSOES_ACEITAS],
    )
    if arquivo is not None:
        try:
            entrada_texto = extrair_texto(arquivo.name, arquivo.getvalue())
            st.caption(f"📄 **{arquivo.name}** lido: {len(entrada_texto):,} caracteres de texto.".replace(",", "."))
        except RoteiroInvalido as exc:
            st.error(str(exc))

if st.button("🧭 Analisar pedido", type="primary", use_container_width=True):
    if not entrada_texto.strip():
        st.warning("Digite um tema ou anexe um roteiro primeiro.", icon="✏️")
        st.stop()
    with st.spinner("Analisando o pedido…"):
        st.session_state["pacote"] = analisar(entrada_texto.strip(), modo=modo)
        st.session_state.pop("resultados", None)

pacote: PacoteBusca | None = st.session_state.get("pacote")
if pacote is None:
    st.stop()

# ---------------- passo 2: revisão ----------------
st.markdown("### 2️⃣ Revise o que eu entendi")

if pacote.provedor != "basico":
    st.success(f"🧠 Entendimento feito por **IA** — {pacote.provedor}.", icon="🧠")
else:
    st.info(
        "⚡ **Modo básico** (sem IA). " + (pacote.aviso or "")
        + " O assistente funciona assim mesmo; com uma chave configurada na "
          "⚙️ **Cabine de APIs**, as tags e sub-consultas ficam mais espertas.",
        icon="⚡",
    )

st.markdown(f"**O que entendi:** {pacote.sinopse}")

col_tags, col_filtros = st.columns(2)
with col_tags:
    st.markdown("**Tags inteligentes** (desmarque o que não servir)")
    tags_ativas = st.multiselect(
        "Tags sugeridas",
        options=pacote.tags_inteligentes,
        default=pacote.tags_inteligentes,
        label_visibility="collapsed",
    )
    st.markdown("**Sub-consultas** (cada uma vira uma busca independente)")
    subs_ativas = st.multiselect(
        "Sub-consultas",
        options=pacote.subconsultas,
        default=pacote.subconsultas,
        label_visibility="collapsed",
    )

with col_filtros:
    st.markdown("**Filtros normais**")
    tipos = st.multiselect(
        "Tipo de material",
        options=list(ROTULOS_TIPO),
        format_func=lambda t: ROTULOS_TIPO[t],
        default=list(ROTULOS_TIPO),
    )
    unidade = st.selectbox("Unidade/câmpus", options=["Todas"] + unidades)
    anos = st.slider("Período (ano)", 1960, 2030, (1960, 2030))
    limite = st.slider("Resultados por seção (por assunto)", 3, 10, 3)

st.markdown("**Não ficou bom? Peça um ajuste**")
col_chat, col_btn = st.columns([4, 1])
ajuste = col_chat.text_input(
    "Chat refinador",
    placeholder='Ex.: "quero mais pesquisadores de campo, menos teoria"…',
    label_visibility="collapsed",
)
if col_btn.button("↻ Refinar", use_container_width=True) and ajuste.strip():
    with st.spinner("Reanalisando com seu ajuste…"):
        st.session_state["pacote"] = analisar(
            pacote.entrada_original, modo=pacote.modo, instrucao_extra=ajuste.strip()
        )
        st.session_state.pop("resultados", None)
    st.rerun()

if not subs_ativas:
    st.warning("Deixe pelo menos uma sub-consulta marcada para buscar.", icon="✏️")
    st.stop()

if st.button("🔍 Buscar agora", type="primary", use_container_width=True):
    from src.banco.vectorstore import FiltrosBusca
    from src.busca.hibrida import buscar_agrupada

    filtros = FiltrosBusca(
        tipos=tipos or None,
        unidade=None if unidade == "Todas" else unidade,
        ano_min=None if anos[0] <= 1960 else anos[0],
        ano_max=None if anos[1] >= 2030 else anos[1],
    )
    reforco = " ".join(tags_ativas[:4])  # tags ligadas reforçam o lexical
    resultados = []
    with st.spinner(f"Pesquisando {len(subs_ativas)} assunto(s) no acervo da UEG…"):
        for sub in subs_ativas:
            consulta = f"{sub} {reforco}".strip()
            resp = buscar_agrupada(
                consulta,
                filtros=filtros,
                limite_por_grupo=limite,
                roteiro_anexado=(pacote.modo == "roteiro"),
            )
            resultados.append((sub, resp))
    st.session_state["resultados"] = resultados

# ---------------- passo 3: resultados ----------------
resultados = st.session_state.get("resultados")
if not resultados:
    st.stop()

st.markdown("### 3️⃣ Resultados por assunto")

titulos_grupo = {
    "teses": "🎓 Teses",
    "dissertacoes": "📚 Dissertações",
    "artigos": "📄 Artigos",
    "extensao": "🏗️ Extensão",
    "laboratorios": "🔬 Laboratórios",
}
for sub, resp in resultados:
    total = sum(len(lista) for lista in resp.grupos.values())
    with st.expander(f"**{sub[:90]}** — {total} resultados em {resp.segundos:.1f} s", expanded=True):
        if total == 0:
            st.caption("Nada encontrado para este assunto com os filtros atuais.")
            continue
        for chave, rotulo in titulos_grupo.items():
            itens = resp.grupos.get(chave, [])
            if not itens:
                continue
            st.markdown(f"**{rotulo}**")
            for r in itens:
                pessoas = resp.pessoas_por_documento.get(r.id, [])
                quem = ""
                if pessoas:
                    quem = " · 👤 " + ", ".join(
                        f"{p.nome} ({p.papel})" for p in pessoas[:2]
                    )
                linha = f"- `{r.similaridade:.2f}` ⭐ **{r.titulo}**"
                if r.ano:
                    linha += f" ({r.ano})"
                linha += quem
                if r.url:
                    linha += f" · [fonte]({r.url})"
                st.markdown(linha)

st.caption(
    "Cada assunto roda o motor híbrido do M4 (vetorial + lexical, fusão RRF). "
    "Tags ligadas reforçam a busca por palavra. Buscas são registradas em log "
    "de auditoria; pessoas com opt-out (LGPD) nunca aparecem."
)
