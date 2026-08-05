"""Privacidade (LGPD) — informação ao titular + canal de opt-out.

Funcional desde o M0, antes de qualquer coleta (decisão do gerente, Q9).
"""
import streamlit as st

from db import conectar

st.set_page_config(page_title="Privacidade (LGPD) — Banco de Personagens", page_icon="🔒", layout="wide")

st.title("🔒 Privacidade e proteção de dados (LGPD)")

st.markdown(
    """
### O que este sistema faz

O **Banco de Personagens** é um sistema do **CriaLab|UEG** (Laboratório de Pesquisas
Criativas e Inovação em Audiovisual, UnU Goiânia-Laranjeiras) que conecta temas de
produção audiovisual a pesquisadores, laboratórios, equipamentos e pesquisas da UEG,
apoiando a produção de filmes e programas que divulgam a ciência da universidade.

### Quais dados são tratados

Apenas **dados profissionais e institucionais já públicos**, coletados de fontes
abertas: nome, vínculo institucional (unidade/curso/programa), e-mail funcional
`@ueg.br`, link público do Currículo Lattes e ORCID, e produções acadêmicas.
**Nunca** são tratados dados sensíveis (CPF, endereço residencial, filiação,
raça, saúde etc.).

### Fontes e bases legais

- BDTD/UEG, Dados Abertos do Estado de Goiás (CC-BY), páginas institucionais da UEG
  e OpenAlex — todas de acesso aberto e verificadas;
- Bases legais (Lei 13.709/2018): **art. 7º, III** (execução de políticas públicas de
  ensino, pesquisa e extensão), **art. 7º, IV** (estudos por órgão de pesquisa) e
  **art. 7º, §4º** (dados tornados manifestamente públicos pelo titular).

### Seus direitos

Você pode solicitar a **remoção (opt-out)** dos seus dados deste sistema a qualquer
momento pelo formulário abaixo. A remoção esconde seus dados da interface e dos
resumos gerados; os registros brutos de origem permanecem retidos apenas para
auditoria, conforme o registro de operações (ROPA) do projeto.

Os dados de contato exibidos são **insumo interno de pré-produção** do CriaLab —
não são republicados em massa nem cedidos a terceiros.
"""
)

st.divider()
st.markdown("### Formulário de remoção (opt-out)")

with st.form("optout_form", clear_on_submit=True):
    nome = st.text_input("Nome completo *")
    identificador = st.text_input(
        "E-mail, ORCID ou link do Currículo Lattes (ajuda a localizar seu cadastro)"
    )
    motivo = st.text_area("Motivo (opcional)")
    enviado = st.form_submit_button("Solicitar remoção")

if enviado:
    if not nome.strip():
        st.error("Informe o nome completo.")
    else:
        conn = conectar()
        if conn is None:
            st.error(
                "Não foi possível registrar agora (banco de dados fora do ar). "
                "Tente novamente em instantes — abra o Docker Desktop e recarregue "
                "a página."
            )
        else:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO optout (nome, identificador, motivo) VALUES (%s, %s, %s)",
                        (nome.strip(), identificador.strip() or None, motivo.strip() or None),
                    )
                conn.commit()
                st.success(
                    "Solicitação registrada. Seus dados serão removidos da interface "
                    "e dos resumos do sistema."
                )
            finally:
                conn.close()

st.caption(
    "Dúvidas sobre o tratamento de dados: procure a coordenação do CriaLab|UEG "
    "(UnU Goiânia-Laranjeiras). Este sistema se apoia na página LGPD institucional "
    "da UEG (ueg.br/transparencia)."
)
