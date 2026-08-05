"""Coletor BDTD/UEG — DSpace 10 (teses e dissertações).

Canais (verificados ao vivo em 05/08/2026):
- REST discover: /server/api/discover/search/objects (projection=full)
  → varredura completa com metadados DRIVER ricos (orientador + Lattes,
  programa, câmpus, área CNPq). É o canal primário hoje.
- OAI-PMH: /server/oai/request — índice vazio em ago/2026 (migração
  DSpace 10 em andamento); usado para coletas incrementais quando a
  instância repovoar o índice.
- Espelho estável (config de fallback): BDTD nacional (bdtd.ibict.br,
  prefixo UEG-2_), com os mesmos metadados DRIVER.

Regras: tudo passa pelo data lake bruto; nada existe só na fonte.
"""
from __future__ import annotations

import argparse
import re
import time
from typing import Callable

import requests
from psycopg.types.json import Jsonb

from src.banco.conexao import conectar, fonte_id_por_codigo, marcar_coleta
from src.coleta.lago import salvar_json
from src.coleta.normalizacao import normalizar_nome

API = "https://bdtd.ueg.br/server/api"
OAI = "https://bdtd.ueg.br/server/oai/request"
FONTE = "F1-BDTD-REST"
PAUSA_S = 0.4          # polidez entre requisições
TAM_PAGINA = 25        # páginas grandes estouram timeout no servidor frágil
TENTATIVAS = 4         # retries com backoff (regra dos relatórios)

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dXx]$")

TIPO_MAP = {
    "dissertação": "dissertacao",
    "tese": "tese",
    "trabalho de conclusão de curso": "tcc",
    "monografia": "tcc",
}

Progresso = Callable[[str, float | None], None]


def _log(progresso: Progresso | None, msg: str, frac: float | None = None) -> None:
    if progresso:
        progresso(msg, frac)
    else:
        print(msg, flush=True)


def status_oai() -> str:
    """Sonda o OAI-PMH local: 'ok' se o índice tem registros, senão motivo."""
    try:
        r = requests.get(
            OAI, params={"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"},
            timeout=20,
        )
        if "noRecordsMatch" in r.text:
            return "índice vazio (migração DSpace 10 em andamento)"
        if r.status_code == 200 and "<identifier>" in r.text:
            return "ok"
        return f"HTTP {r.status_code}"
    except Exception as exc:  # rede/fonte instável não derruba a coleta REST
        return f"indisponível ({exc.__class__.__name__})"


def _pagina(sess: requests.Session, pagina: int, progresso: Progresso | None = None) -> dict:
    """Busca uma página do discover com retries e backoff exponencial."""
    espera = 5
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = sess.get(
                f"{API}/discover/search/objects",
                params={"size": TAM_PAGINA, "page": pagina, "projection": "full"},
                timeout=120,
            )
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if tentativa == TENTATIVAS:
                raise
            _log(progresso, f"Página {pagina}: {exc.__class__.__name__} — nova tentativa em {espera}s ({tentativa}/{TENTATIVAS})")
            time.sleep(espera)
            espera *= 2
    raise RuntimeError("inalcançável")


def _valor(md: dict, chave: str) -> str | None:
    entradas = md.get(chave) or []
    return entradas[0].get("value") if entradas else None


def _valores(md: dict, chave: str) -> list[str]:
    return [e["value"] for e in md.get(chave) or [] if e.get("value")]


def _ano(data: str | None) -> int | None:
    if data:
        m = re.match(r"(\d{4})", data)
        if m:
            return int(m.group(1))
    return None


def _tipo(dc_type: str | None) -> str:
    if not dc_type:
        return "outro"
    return TIPO_MAP.get(dc_type.strip().lower(), "outro")


def _doc_url(uuid: str) -> str:
    return f"https://bdtd.ueg.br/items/{uuid}"


# ---------------------------------------------------------------- banco

def _upsert_documento(cur, fonte_id: int, item: dict) -> int:
    md = item.get("metadata", {})
    handle = item.get("handle")
    uuid = item.get("uuid")
    autores = _valores(md, "dc.creator")
    resumo = _valor(md, "dc.description.resumo") or _valor(md, "dc.description.abstract")
    metadados = {k: _valores(md, k) for k in md}
    metadados["_uuid"] = uuid
    metadados["_handle"] = handle

    cur.execute(
        """
        INSERT INTO documento (fonte_id, tipo, titulo, resumo, palavras_chave, ano,
                               autores_raw, url, identificador_externo, metadados)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fonte_id, identificador_externo) DO UPDATE SET
            tipo = EXCLUDED.tipo,
            titulo = EXCLUDED.titulo,
            resumo = EXCLUDED.resumo,
            palavras_chave = EXCLUDED.palavras_chave,
            ano = EXCLUDED.ano,
            autores_raw = EXCLUDED.autores_raw,
            url = EXCLUDED.url,
            metadados = EXCLUDED.metadados,
            coletado_em = now()
        RETURNING id
        """,
        (
            fonte_id,
            _tipo(_valor(md, "dc.type")),
            _valor(md, "dc.title"),
            resumo,
            _valores(md, "dc.subject") or None,
            _ano(_valor(md, "dc.date.issued")),
            autores or None,
            _doc_url(uuid) if uuid else _valor(md, "dc.identifier.uri"),
            handle,
            Jsonb(metadados),
        ),
    )
    return cur.fetchone()[0]


def _pessoa_id(cur, nome: str, orcid: str | None, lattes_url: str | None,
               unidade: str | None) -> int | None:
    """Consolidação light: ORCID exato > nome normalizado."""
    if not nome:
        return None
    nome = nome.strip()
    norm = normalizar_nome(nome)
    if orcid and ORCID_RE.match(orcid):
        cur.execute(
            """
            INSERT INTO pessoa (nome_canonico, nome_normalizado, orcid, lattes_url,
                                unidade, confianca_fusao)
            VALUES (%s, %s, %s, %s, %s, 'exata')
            ON CONFLICT (orcid) WHERE orcid IS NOT NULL DO UPDATE SET
                nome_canonico = COALESCE(pessoa.nome_canonico, EXCLUDED.nome_canonico),
                lattes_url    = COALESCE(pessoa.lattes_url, EXCLUDED.lattes_url),
                unidade       = COALESCE(pessoa.unidade, EXCLUDED.unidade)
            RETURNING id
            """,
            (nome, norm, orcid, lattes_url, unidade),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        # conflito tratado sem RETURNING (raro): buscar pelo orcid
        cur.execute("SELECT id FROM pessoa WHERE orcid = %s", (orcid,))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("SELECT id FROM pessoa WHERE nome_normalizado = %s LIMIT 1", (norm,))
    row = cur.fetchone()
    if row:
        pid = row[0]
        if lattes_url:
            cur.execute(
                "UPDATE pessoa SET lattes_url = COALESCE(lattes_url, %s) WHERE id = %s",
                (lattes_url, pid),
            )
        return pid
    cur.execute(
        """
        INSERT INTO pessoa (nome_canonico, nome_normalizado, orcid, lattes_url,
                            unidade, confianca_fusao)
        VALUES (%s, %s, %s, %s, %s, 'exata')
        RETURNING id
        """,
        (nome, norm, orcid if orcid and ORCID_RE.match(orcid) else None,
         lattes_url, unidade),
    )
    return cur.fetchone()[0]


def _papel(cur, pessoa_id: int | None, documento_id: int, papel: str) -> None:
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


def _zip_pessoas(nomes: list[str], ids: list[str], lattes: list[str]):
    """Alinha listas paralelas dc.creator × dc.creator.ID × dc.creator.Lattes."""
    for i, nome in enumerate(nomes):
        yield nome, ids[i] if i < len(ids) else None, lattes[i] if i < len(lattes) else None


# ---------------------------------------------------------------- fluxo

def executar(progresso: Progresso | None = None, ini: int = 0, fim: int | None = None) -> dict:
    """Varredura REST discover + carga no banco (idempotente; fatiável por páginas)."""
    stats = {"paginas": 0, "documentos": 0, "erros_item": 0, "oai": status_oai()}
    _log(progresso, f"OAI-PMH local: {stats['oai']} (usado só para incrementais futuras)")

    conn = conectar()
    sess = requests.Session()
    sess.headers.update({"User-Agent": "CriaLab-UEG-Harvester/1.0 (+github.com/fernangcortes/bd-filmes-ueg)"})

    try:
        fonte_id = fonte_id_por_codigo(conn, FONTE)

        primeira = _pagina(sess, 0, progresso)
        sr = primeira["_embedded"]["searchResult"]
        total_paginas = sr["page"]["totalPages"]
        total_itens = sr["page"]["totalElements"]
        fim = total_paginas if fim is None else min(fim, total_paginas)
        _log(progresso, f"BDTD/UEG: {total_itens} itens em {total_paginas} páginas — processando {ini}–{fim}", 0.0)

        for n_pag in range(ini, fim):
            j = primeira if n_pag == 0 else _pagina(sess, n_pag, progresso)
            salvar_json(FONTE, f"pagina_{n_pag:04d}.json", j)
            objetos = j["_embedded"]["searchResult"]["_embedded"]["objects"]

            with conn.cursor() as cur:
                for o in objetos:
                    item = o.get("_embedded", {}).get("indexableObject", {})
                    if item.get("type") != "item" or not item.get("handle"):
                        continue
                    md = item.get("metadata", {})
                    doc_id = _upsert_documento(cur, fonte_id, item)
                    unidade = _valor(md, "dc.publisher.department") or _valor(md, "dc.publisher.program")

                    for nome, orcid, lattes in _zip_pessoas(
                        _valores(md, "dc.creator"),
                        _valores(md, "dc.creator.ID"),
                        _valores(md, "dc.creator.Lattes"),
                    ):
                        _papel(cur, _pessoa_id(cur, nome, orcid, lattes, unidade), doc_id, "autor")

                    for nome, orcid, lattes in _zip_pessoas(
                        _valores(md, "dc.contributor.advisor1"),
                        _valores(md, "dc.contributor.advisor1ID"),
                        _valores(md, "dc.contributor.advisor1Lattes"),
                    ):
                        _papel(cur, _pessoa_id(cur, nome, orcid, lattes, unidade), doc_id, "orientador")

                    stats["documentos"] += 1
            conn.commit()

            stats["paginas"] += 1
            frac = (n_pag + 1 - ini) / max(fim - ini, 1)
            _log(progresso, f"Página {n_pag + 1}/{total_paginas} — {stats['documentos']} documentos", frac)
            time.sleep(PAUSA_S)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pessoa")
            stats["pessoas_total"] = cur.fetchone()[0]
        if fim >= total_paginas:  # só marca quando a varredura chega ao fim
            marcar_coleta(conn, FONTE)
            conn.commit()
    finally:
        conn.close()
        sess.close()

    _log(progresso, "Coleta BDTD concluída.", 1.0)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor BDTD/UEG (DSpace 10)")
    parser.add_argument("--ini", type=int, default=0, help="página inicial (fatias)")
    parser.add_argument("--fim", type=int, default=None, help="página final exclusiva")
    args = parser.parse_args()
    executar(ini=args.ini, fim=args.fim)


if __name__ == "__main__":
    main()
