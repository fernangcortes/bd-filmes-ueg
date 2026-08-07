"""Extração de texto de roteiros anexados (M5) — PDF, TXT e DOCX.

O usuário leigo anexa o arquivo do roteiro; esta função devolve o texto puro
para o estágio de entendimento. Nada é gravado em disco: o texto vive só na
sessão (LGPD: roteiros podem ter conteúdo sensível/inédito).

Dependências já presentes no projeto: pypdf (PDF) e python-docx (DOCX).
"""
from __future__ import annotations

import io

# Teto de segurança: roteiros muito longos são cortados para o entendimento
# (o LLM local e a heurística não precisam de mais que isso para achar temas).
MAX_CARACTERES_ROTEIRO = 30_000

EXTENSOES_ACEITAS = (".pdf", ".txt", ".docx")


class RoteiroInvalido(Exception):
    """Formato não suportado ou arquivo sem texto legível."""


def _de_pdf(conteudo: bytes) -> str:
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(conteudo))
    partes = [(pagina.extract_text() or "") for pagina in leitor.pages]
    return "\n".join(partes)


def _de_docx(conteudo: bytes) -> str:
    import docx

    documento = docx.Document(io.BytesIO(conteudo))
    return "\n".join(p.text for p in documento.paragraphs)


def _de_txt(conteudo: bytes) -> str:
    for codificacao in ("utf-8", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise RoteiroInvalido("Não consegui ler o TXT (codificação desconhecida).")


def extrair_texto(nome_arquivo: str, conteudo: bytes) -> str:
    """Texto puro do roteiro, cortado no teto de segurança (sem quebrar
    palavra — mesma regra do M4). Lança RoteiroInvalido se não houver texto."""
    nome = (nome_arquivo or "").lower()
    if nome.endswith(".pdf"):
        texto = _de_pdf(conteudo)
    elif nome.endswith(".docx"):
        texto = _de_docx(conteudo)
    elif nome.endswith(".txt"):
        texto = _de_txt(conteudo)
    else:
        raise RoteiroInvalido(
            "Formato não suportado. Anexe PDF, TXT ou DOCX."
        )

    texto = "\n".join(linha.strip() for linha in texto.splitlines())
    if len(texto.strip()) < 20:
        raise RoteiroInvalido(
            "Não encontrei texto legível no arquivo (PDF de imagem/escaneado "
            "não é lido — exporte o roteiro como texto)."
        )
    if len(texto) > MAX_CARACTERES_ROTEIRO:
        pedaco = texto[:MAX_CARACTERES_ROTEIRO]
        texto = pedaco.rsplit(" ", 1)[0] if " " in pedaco else pedaco
    return texto.strip()
