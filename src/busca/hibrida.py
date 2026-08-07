"""Busca híbrida (M4) — fachada usada pela página 🔎 Busca.

Pipeline (plano §7.1, estágio 3): tema → vetor (e5-large local) →
candidatos vetoriais + candidatos lexicais (tsvector) → fusão RRF →
filtros SQL (tipo, unidade/câmpus, ano) → resultados ranqueados com fonte.

LGPD: pessoas com optout=true nunca aparecem nos resultados.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import psycopg

from src.banco.conexao import DB_URL
from src.banco.vectorstore import FiltrosBusca, PgVectorStore, ResultadoBusca
from src.busca.embeddings import GeradorEmbeddings


@dataclass
class PessoaVinculada:
    nome: str
    papel: str          # autor | orientador | coordenador | responsavel
    email: str | None
    unidade: str | None


@dataclass
class RespostaBusca:
    consulta: str
    resultados: list[ResultadoBusca]
    pessoas_por_documento: dict[int, list[PessoaVinculada]] = field(default_factory=dict)
    segundos: float = 0.0


@dataclass
class RespostaAgrupada:
    """Resultados separados por seção (critério A1: cada categoria aparece
    com seu próprio ranking, sem ser abafada pelas teses)."""

    consulta: str
    grupos: dict[str, list[ResultadoBusca]]            # chave: teses | dissertacoes | artigos | extensao | laboratorios
    pessoas_por_documento: dict[int, list[PessoaVinculada]] = field(default_factory=dict)
    segundos: float = 0.0


GRUPOS = {
    # Pesquisas em sub-grupos próprios: com 9,9 mil artigos contra 31 teses,
    # um ranking único de "pesquisas" enterrava as teses RENAC/TECCER (A1).
    "teses": ["tese"],
    "dissertacoes": ["dissertacao"],
    "artigos": ["work"],
    "extensao": ["projeto_extensao"],
    "laboratorios": ["ficha_lab"],
}


def pessoas_dos_documentos(ids: list[int], limite_por_doc: int = 5) -> dict[int, list[PessoaVinculada]]:
    """Pessoas vinculadas a cada documento, orientadores primeiro.

    Regra LGPD: `optout = true` exclui a pessoa de qualquer resultado.
    """
    if not ids:
        return {}
    sql = """
    SELECT pd.documento_id, pd.papel, p.nome_canonico, p.email, p.unidade
    FROM pessoa_documento pd
    JOIN pessoa p ON p.id = pd.pessoa_id
    WHERE pd.documento_id = ANY(%s)
      AND p.optout = FALSE
    ORDER BY pd.documento_id,
             CASE pd.papel
                 WHEN 'orientador' THEN 0
                 WHEN 'coordenador' THEN 1
                 WHEN 'responsavel' THEN 2
                 ELSE 3
             END,
             p.nome_canonico
    """
    saida: dict[int, list[PessoaVinculada]] = {}
    conn = psycopg.connect(DB_URL, connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (ids,))
            for doc_id, papel, nome, email, unidade in cur.fetchall():
                lista = saida.setdefault(doc_id, [])
                if len(lista) < limite_por_doc:
                    lista.append(PessoaVinculada(nome=nome, papel=papel, email=email, unidade=unidade))
    finally:
        conn.close()
    return saida


def registrar_log(entrada: str, filtros: FiltrosBusca, roteiro_anexado: bool = False) -> None:
    """Auditoria mínima da busca (tabela busca_log do schema)."""
    try:
        conn = psycopg.connect(DB_URL, connect_timeout=3)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO busca_log (entrada_usuario, roteiro_anexado, tags_usadas) VALUES (%s, %s, %s::jsonb)",
                (
                    entrada,
                    roteiro_anexado,
                    __import__("json").dumps(
                        {
                            "tipos": filtros.tipos,
                            "unidade": filtros.unidade,
                            "ano_min": filtros.ano_min,
                            "ano_max": filtros.ano_max,
                            "pipeline": "m4-vetorial+lexical-rrf",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass  # log nunca derruba a busca


def buscar(
    consulta: str,
    filtros: FiltrosBusca | None = None,
    limite: int = 30,
) -> RespostaBusca:
    """Executa a busca híbrida completa e devolve resultados + pessoas."""
    import time

    filtros = filtros or FiltrosBusca()
    inicio = time.monotonic()

    vetor = GeradorEmbeddings.obter().embed_consulta(consulta)
    loja = PgVectorStore()
    try:
        resultados = loja.buscar(vetor, consulta, filtros, limite=limite)
    finally:
        loja.close()

    ids = [r.id for r in resultados if r.tabela == "documento"]
    pessoas = pessoas_dos_documentos(ids)
    registrar_log(consulta, filtros)

    return RespostaBusca(
        consulta=consulta,
        resultados=resultados,
        pessoas_por_documento=pessoas,
        segundos=time.monotonic() - inicio,
    )


def buscar_agrupada(
    consulta: str,
    filtros: FiltrosBusca | None = None,
    limite_por_grupo: int = 10,
    roteiro_anexado: bool = False,
) -> RespostaAgrupada:
    """Uma consulta vetorial, cinco buscas ranqueadas — uma por seção
    (teses / dissertações / artigos / extensão / laboratórios). Garante que
    cada categoria apareça com seu próprio ranking, sem ser abafada pelos
    9,9 mil artigos do OpenAlex (critério A1).

    Grupos cujo tipo foi desmarcado nos filtros saem vazios.
    """
    import time

    filtros = filtros or FiltrosBusca()
    inicio = time.monotonic()

    vetor = GeradorEmbeddings.obter().embed_consulta(consulta)
    grupos: dict[str, list[ResultadoBusca]] = {}
    loja = PgVectorStore()
    try:
        for nome, tipos_grupo in GRUPOS.items():
            if filtros.tipos is not None and not set(tipos_grupo) & set(filtros.tipos):
                grupos[nome] = []
                continue
            f = FiltrosBusca(
                tipos=tipos_grupo,
                unidade=filtros.unidade,
                ano_min=filtros.ano_min,
                ano_max=filtros.ano_max,
            )
            grupos[nome] = loja.buscar(vetor, consulta, f, limite=limite_por_grupo)
    finally:
        loja.close()

    ids = [r.id for lista in grupos.values() for r in lista]
    pessoas = pessoas_dos_documentos(ids)
    registrar_log(consulta, filtros, roteiro_anexado=roteiro_anexado)

    return RespostaAgrupada(
        consulta=consulta,
        grupos=grupos,
        pessoas_por_documento=pessoas,
        segundos=time.monotonic() - inicio,
    )
