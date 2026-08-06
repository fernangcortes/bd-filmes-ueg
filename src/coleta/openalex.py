"""Coletor F4 — OpenAlex (CC0): produção científica global da UEG.

Verificado ao vivo em ago/2026 (relatório Vol. 1, §3.7):
- works?filter=institutions.id:I3129565396 → ~9.931 works (título, resumo
  em índice invertido, autores com ORCID, tópicos, ano, DOI);
- authors?filter=last_known_institutions.id:I3129565396 → pesquisadores
  cuja última afiliação conhecida é a UEG (âncora ORCID da consolidação).

Regras implementadas:
- polite pool: parâmetro mailto= lido de config/instituicoes.yaml
  (fontes F4-OPENALEX → polite_pool_mailto) ou da variável de ambiente
  BD_FILMES_MAILTO. Sem e-mail configurado, a coleta roda no pool comum
  (mais lento/compartilhado) e avisa no log — nunca inventamos um e-mail.
- Data lake bruto obrigatório: cada página JSON vai para
  dados/lago/F4-OPENALEX/<data>/ antes de qualquer tratamento.
- Consolidação light compartilhada (src.coleta.pessoas): ORCID exato →
  Lattes → e-mail → nome normalizado; COALESCE só preenche lacunas.

Decisão de qualidade (M3): dos works da UEG, só viram `pessoa` os autores
cuja *própria autoria* declara afiliação UEG (authorships[].institutions
contém I3129565396). Co-autores de outras instituições ficam preservados
em autores_raw/metadados para auditoria, mas não entram no cadastro de
personagens — o banco é da UEG, e artigos multinstitucionais trariam
milhares de externos sem vínculo real.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Callable

import requests
import yaml
from psycopg.types.json import Jsonb

from src.banco.conexao import conectar, fonte_id_por_codigo, marcar_coleta
from src.coleta.lago import salvar_json
from src.coleta.pessoas import upsert_pessoa, vincular_documento

API = "https://api.openalex.org"
UEG_OPENALEX = "I3129565396"
FONTE = "F4-OPENALEX"
TAM_PAGINA = 200        # máximo da API
PAUSA_S = 0.2           # polite pool permite 10 req/s; ficamos bem abaixo
TENTATIVAS = 5          # retries com backoff (regra dos relatórios)
UA = {"User-Agent": "CriaLab-UEG-Harvester/1.0 (+github.com/fernangcortes/bd-filmes-ueg)"}

Progresso = Callable[[str, float | None], None]


def _log(progresso: Progresso | None, msg: str, frac: float | None = None) -> None:
    if progresso:
        progresso(msg, frac)
    else:
        print(msg, flush=True)


def _mailto() -> str | None:
    """E-mail do polite pool: config/instituicoes.yaml ou BD_FILMES_MAILTO.

    Nunca inventa um endereço: sem configuração, roda no pool comum.
    """
    env = os.getenv("BD_FILMES_MAILTO", "").strip()
    if env:
        return env
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "instituicoes.yaml"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            instituicoes = yaml.safe_load(f) or []
        for inst in instituicoes:
            for fonte in inst.get("fontes", []):
                if fonte.get("codigo") == FONTE:
                    mail = (fonte.get("polite_pool_mailto") or "").strip()
                    return mail or None
    except Exception:
        pass
    return None


def _pagina(sess: requests.Session, caminho: str, params: dict,
            progresso: Progresso | None = None) -> dict:
    """Busca uma página da API com retries, backoff e respeito a 429."""
    espera = 2
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = sess.get(f"{API}{caminho}", params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = int(r.headers.get("Retry-After", espera))
                raise requests.HTTPError(
                    f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if tentativa == TENTATIVAS:
                raise
            atraso = espera
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                atraso = int(exc.response.headers.get("Retry-After", espera))
            _log(progresso,
                 f"OpenAlex: {exc.__class__.__name__} — nova tentativa em {atraso}s "
                 f"({tentativa}/{TENTATIVAS})")
            time.sleep(atraso)
            espera *= 2
    raise RuntimeError("inalcançável")


def _resumo_invertido(indice: dict | None) -> str | None:
    """Reconstrói o resumo a partir do abstract_inverted_index da OpenAlex."""
    if not indice:
        return None
    posicoes: dict[int, str] = {}
    for palavra, pos_list in indice.items():
        for p in pos_list:
            posicoes[p] = palavra
    return " ".join(posicoes[i] for i in sorted(posicoes))


def _autoria_ueg(authorship: dict) -> bool:
    """True se ESTA autoria declara afiliação UEG (não o work como um todo)."""
    for inst in authorship.get("institutions", []):
        iid = (inst.get("id") or "").rsplit("/", 1)[-1]
        if iid == UEG_OPENALEX:
            return True
    return False


# ------------------------------------------------------------- works

def _upsert_work(cur, fonte_id: int, w: dict) -> int:
    openalex_id = (w.get("id") or "").rsplit("/", 1)[-1]  # "W2741809807"
    doi = w.get("doi")                                     # já vem como URL
    autores = [
        a.get("author", {}).get("display_name")
        for a in w.get("authorships", [])
        if a.get("author", {}).get("display_name")
    ]
    topicos = [t.get("display_name") for t in w.get("topics", []) if t.get("display_name")]
    palavras = [k.get("display_name") for k in w.get("keywords", []) if k.get("display_name")]
    oa = w.get("open_access", {}) or {}
    melhor = (w.get("best_oa_location") or {})

    metadados = {
        "openalex_id": openalex_id,
        "doi": doi,
        "tipo_openalex": w.get("type"),
        "idioma": w.get("language"),
        "citacoes": w.get("cited_by_count"),
        "acesso_aberto": oa.get("is_oa"),
        "topicos": topicos,
        "autores_openalex": [
            {"nome": a.get("author", {}).get("display_name"),
             "orcid": a.get("author", {}).get("orcid"),
             "ueg": _autoria_ueg(a)}
            for a in w.get("authorships", [])
        ],
        "fonte_publicacao": (
            ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        ),
    }

    cur.execute(
        """
        INSERT INTO documento (fonte_id, tipo, titulo, resumo, palavras_chave, ano,
                               autores_raw, url, pdf_url, identificador_externo, metadados)
        VALUES (%s, 'work', %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fonte_id, identificador_externo) DO UPDATE SET
            titulo = EXCLUDED.titulo,
            resumo = EXCLUDED.resumo,
            palavras_chave = EXCLUDED.palavras_chave,
            ano = EXCLUDED.ano,
            autores_raw = EXCLUDED.autores_raw,
            url = EXCLUDED.url,
            pdf_url = EXCLUDED.pdf_url,
            metadados = EXCLUDED.metadados,
            coletado_em = now()
        RETURNING id
        """,
        (
            fonte_id,
            w.get("title"),
            _resumo_invertido(w.get("abstract_inverted_index")),
            palavras[:15] or topicos or None,
            w.get("publication_year"),
            autores or None,
            doi or w.get("id"),
            melhor.get("pdf_url") or oa.get("oa_url"),
            openalex_id,
            Jsonb(metadados),
        ),
    )
    return cur.fetchone()[0]


def _coletar_works(conn, sess, fonte_id: int, mailto: str | None,
                   progresso: Progresso | None, limite_paginas: int | None) -> dict:
    stats = {"works": 0, "autores_ueg_vinculados": 0}
    params = {
        "filter": f"institutions.id:{UEG_OPENALEX}",
        "per-page": TAM_PAGINA,
        "cursor": "*",
    }
    if mailto:
        params["mailto"] = mailto

    pagina = 0
    total = None
    while params["cursor"]:
        j = _pagina(sess, "/works", params, progresso)
        salvar_json(FONTE, f"works_{pagina:04d}.json", j)
        if total is None:
            total = j.get("meta", {}).get("count", 0)
            _log(progresso, f"OpenAlex works da UEG: {total} registros anunciados.", 0.05)

        with conn.cursor() as cur:
            for w in j.get("results", []):
                doc_id = _upsert_work(cur, fonte_id, w)
                for a in w.get("authorships", []):
                    if not _autoria_ueg(a):
                        continue  # co-autor externo: fica só no autores_raw
                    autor = a.get("author", {})
                    pid = upsert_pessoa(cur, autor.get("display_name"),
                                        orcid=autor.get("orcid"))
                    if pid is not None:
                        vincular_documento(cur, pid, doc_id, "autor")
                        stats["autores_ueg_vinculados"] += 1
                stats["works"] += 1
        conn.commit()

        pagina += 1
        frac = min(stats["works"] / max(total or 1, 1), 0.95) * 0.7  # works = 70% do total
        _log(progresso,
             f"Works: {stats['works']}/{total} · autores UEG vinculados: "
             f"{stats['autores_ueg_vinculados']}", frac)

        params["cursor"] = j.get("meta", {}).get("next_cursor")
        if limite_paginas and pagina >= limite_paginas:
            _log(progresso, f"Limite de {limite_paginas} páginas (teste) atingido.")
            break
        if params["cursor"]:
            time.sleep(PAUSA_S)
    return stats


# ------------------------------------------------------------- authors

def _coletar_autores(conn, sess, mailto: str | None,
                     progresso: Progresso | None, limite_paginas: int | None) -> dict:
    stats = {"autores": 0, "com_orcid": 0}
    params = {
        "filter": f"last_known_institutions.id:{UEG_OPENALEX}",
        "per-page": TAM_PAGINA,
        "cursor": "*",
    }
    if mailto:
        params["mailto"] = mailto

    pagina = 0
    total = None
    while params["cursor"]:
        j = _pagina(sess, "/authors", params, progresso)
        salvar_json(FONTE, f"authors_{pagina:04d}.json", j)
        if total is None:
            total = j.get("meta", {}).get("count", 0)
            _log(progresso,
                 f"OpenAlex authors (última afiliação UEG): {total} anunciados.", 0.75)

        with conn.cursor() as cur:
            for a in j.get("results", []):
                orcid = a.get("orcid")
                pid = upsert_pessoa(cur, a.get("display_name"), orcid=orcid)
                if pid is not None:
                    stats["autores"] += 1
                    if orcid:
                        stats["com_orcid"] += 1
        conn.commit()

        pagina += 1
        frac = 0.7 + min(stats["autores"] / max(total or 1, 1), 1.0) * 0.28
        _log(progresso,
             f"Authors: {stats['autores']}/{total} · com ORCID: {stats['com_orcid']}", frac)

        params["cursor"] = j.get("meta", {}).get("next_cursor")
        if limite_paginas and pagina >= limite_paginas:
            _log(progresso, f"Limite de {limite_paginas} páginas (teste) atingido.")
            break
        if params["cursor"]:
            time.sleep(PAUSA_S)
    return stats


# ------------------------------------------------------------- fluxo

def executar(progresso: Progresso | None = None, limite_paginas: int | None = None,
             so_works: bool = False, so_autores: bool = False) -> dict:
    """Coleta OpenAlex completa (idempotente): works → documento, authors → pessoa."""
    stats: dict = {"works": 0, "autores_ueg_vinculados": 0, "autores": 0, "com_orcid": 0}
    mailto = _mailto()
    if mailto:
        _log(progresso, f"Polite pool ativo (mailto={mailto}).", 0.0)
    else:
        _log(progresso,
             "Sem e-mail configurado — rodando no pool comum da OpenAlex "
             "(mais lento). Para o polite pool, preencha polite_pool_mailto em "
             "config/instituicoes.yaml ou a variável BD_FILMES_MAILTO.", 0.0)

    conn = conectar()
    sess = requests.Session()
    sess.headers.update(UA)
    try:
        fonte_id = fonte_id_por_codigo(conn, FONTE)

        if not so_autores:
            stats.update(_coletar_works(conn, sess, fonte_id, mailto,
                                        progresso, limite_paginas))
        if not so_works:
            stats.update(_coletar_autores(conn, sess, mailto,
                                          progresso, limite_paginas))

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pessoa")
            stats["pessoas_total"] = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pessoa WHERE orcid IS NOT NULL")
            stats["pessoas_com_orcid"] = cur.fetchone()[0]

        if not limite_paginas:  # só marca coleta completa (não testes fatiados)
            marcar_coleta(conn, FONTE)
            conn.commit()
    finally:
        conn.close()
        sess.close()

    _log(progresso, "Coleta OpenAlex concluída.", 1.0)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor OpenAlex (CC0) — UEG")
    parser.add_argument("--limite-paginas", type=int, default=None,
                        help="máximo de páginas por endpoint (teste)")
    parser.add_argument("--so-works", action="store_true", help="só works")
    parser.add_argument("--so-autores", action="store_true", help="só authors")
    args = parser.parse_args()
    executar(limite_paginas=args.limite_paginas,
             so_works=args.so_works, so_autores=args.so_autores)


if __name__ == "__main__":
    main()
