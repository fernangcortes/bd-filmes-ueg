"""Consolidação light de pessoas — regras determinísticas do MVP (plano §6.5).

Ordem de casamento (somente identificadores exatos, nada de heurística):
1. ORCID exato;
2. URL Lattes idêntica;
3. e-mail institucional idêntico;
4. nome normalizado (sem acento, minúsculo, tokens ordenados).

Sem identificador, a pessoa entra como registro novo e honesto; a fusão
profunda fica para a Fase 2. Campos novos só preenchem lacunas (COALESCE) —
nunca sobrescrevem o que já existe.
"""
from __future__ import annotations

import re

from src.coleta.normalizacao import normalizar_nome

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dXx]$")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def _limpar_email(email: str | None) -> str | None:
    if not email:
        return None
    email = email.strip().lower().rstrip(".;")
    return email if EMAIL_RE.match(email) else None


def _limpar_orcid(orcid: str | None) -> str | None:
    if not orcid:
        return None
    orcid = orcid.strip().replace("https://orcid.org/", "").replace("http://orcid.org/", "")
    return orcid if ORCID_RE.match(orcid) else None


def _limpar_lattes(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return url if "lattes.cnpq.br" in url else None


def _buscar(cur, orcid, lattes_url, email, norm) -> int | None:
    """Procura pessoa existente pelos identificadores exatos, na ordem."""
    if orcid:
        cur.execute("SELECT id FROM pessoa WHERE orcid = %s LIMIT 1", (orcid,))
        row = cur.fetchone()
        if row:
            return row[0]
    if lattes_url:
        cur.execute("SELECT id FROM pessoa WHERE lattes_url = %s LIMIT 1", (lattes_url,))
        row = cur.fetchone()
        if row:
            return row[0]
    if email:
        cur.execute("SELECT id FROM pessoa WHERE lower(email) = %s LIMIT 1", (email,))
        row = cur.fetchone()
        if row:
            return row[0]
    if norm:
        cur.execute("SELECT id FROM pessoa WHERE nome_normalizado = %s LIMIT 1", (norm,))
        row = cur.fetchone()
        if row:
            return row[0]
    return None


def _completar(cur, pid: int, orcid, lattes_url, email, vinculo, unidade) -> None:
    """Preenche lacunas do registro existente (nunca sobrescreve)."""
    cur.execute(
        """
        UPDATE pessoa SET
            orcid      = COALESCE(orcid, %s),
            lattes_url = COALESCE(lattes_url, %s),
            email      = COALESCE(email, %s),
            vinculo    = COALESCE(vinculo, %s),
            unidade    = COALESCE(unidade, %s)
        WHERE id = %s
        """,
        (orcid, lattes_url, email, vinculo, unidade, pid),
    )


def upsert_pessoa(cur, nome: str | None, orcid: str | None = None,
                  lattes_url: str | None = None, email: str | None = None,
                  vinculo: str | None = None, unidade: str | None = None) -> int | None:
    """Insere ou consolida uma pessoa; devolve o id (None se nome vazio)."""
    if not nome or not nome.strip():
        return None
    nome = " ".join(nome.split())  # colapsa espaços/quebras
    orcid = _limpar_orcid(orcid)
    lattes_url = _limpar_lattes(lattes_url)
    email = _limpar_email(email)
    norm = normalizar_nome(nome)

    pid = _buscar(cur, orcid, lattes_url, email, norm)
    if pid is not None:
        _completar(cur, pid, orcid, lattes_url, email, vinculo, unidade)
        return pid

    cur.execute(
        """
        INSERT INTO pessoa (nome_canonico, nome_normalizado, orcid, lattes_url,
                            email, vinculo, unidade, confianca_fusao)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'exata')
        ON CONFLICT (orcid) WHERE orcid IS NOT NULL DO NOTHING
        RETURNING id
        """,
        (nome, norm, orcid, lattes_url, email, vinculo, unidade),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    # corrida rara de conflito em ORCID sem RETURNING: buscar de novo
    if orcid:
        cur.execute("SELECT id FROM pessoa WHERE orcid = %s", (orcid,))
        row = cur.fetchone()
        if row:
            return row[0]
    return None


def pessoa_id_por_nome_exato(cur, nome: str | None) -> int | None:
    """Só devolve id se já existir pessoa com esse nome normalizado.

    Usado para campos de texto ambíguos (ex.: coordenação de projetos de
    extensão, onde vários nomes vêm concatenados sem separador): casamos
    quando o nome já existe na base; nunca criamos registro a partir de
    texto não confiável.
    """
    if not nome or not nome.strip():
        return None
    norm = normalizar_nome(nome)
    if not norm:
        return None
    cur.execute("SELECT id FROM pessoa WHERE nome_normalizado = %s LIMIT 1", (norm,))
    row = cur.fetchone()
    return row[0] if row else None


def vincular_documento(cur, pessoa_id: int | None, documento_id: int, papel: str) -> None:
    """Liga pessoa a documento com papel (autor/orientador/coordenador/responsavel)."""
    if pessoa_id is None:
        return
    cur.execute(
        """
        INSERT INTO pessoa_documento (pessoa_id, documento_id, papel)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (pessoa_id, documento_id, papel),
    )
