"""Interface de armazenamento vetorial (plano §3).

A busca e a indexação conversam com esta interface, nunca diretamente com
o pgvector — assim uma migração futura para outro banco vetorial (ex.: Qdrant,
quando a render farm chegar) vira uma nova implementação desta classe,
sem reescrever a busca.

Implementação atual: PgVectorStore (PostgreSQL 16 + pgvector, via Docker).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import psycopg

DB_URL_PADRAO = "postgresql://crialab:crialab_local_dev@localhost:5432/crialab"

# Tabelas que guardam vetores (todas vector(1024))
TABELAS_VETORIAIS = ("documento", "laboratorio", "projeto_extensao")


@dataclass
class FiltrosBusca:
    """Filtros SQL da busca híbrida (todos opcionais)."""

    tipos: list[str] | None = None       # tese, dissertacao, work, projeto_extensao, ficha_lab
    unidade: str | None = None           # câmpus/unidade (casamento parcial)
    ano_min: int | None = None
    ano_max: int | None = None


@dataclass
class ResultadoBusca:
    """Um item ranqueado devolvido pela busca híbrida."""

    tabela: str                          # documento | laboratorio | projeto_extensao
    id: int
    tipo: str                            # tese | dissertacao | work | projeto_extensao | ficha_lab
    titulo: str
    trecho: str                          # resumo cortado para exibição
    ano: int | None
    url: str | None
    unidade: str | None                  # câmpus/unidade para exibição
    similaridade: float                  # cosseno [0..1] da parte vetorial
    score: float                         # score final híbrido (RRF vetorial+lexical)
    metadados: dict = field(default_factory=dict)


class VectorStore(ABC):
    """Contrato mínimo do armazenamento vetorial."""

    @abstractmethod
    def progresso_indexacao(self) -> dict[str, tuple[int, int]]:
        """{tabela: (total_de_registros, com_embedding)} — para barras de progresso."""

    @abstractmethod
    def salvar_embeddings(self, tabela: str, pares: list[tuple[int, list[float]]]) -> int:
        """Grava vetores (id, vetor) na tabela. Retorna quantos foram gravados."""

    @abstractmethod
    def copiar_embeddings_para_espelhos(self) -> int:
        """Replica o vetor da tabela-entidade para o documento espelho
        (laboratorio→ficha_lab, projeto_extensao→projeto_extensao em documento),
        evitando computar o mesmo texto duas vezes. Retorna quantos espelhos
        foram preenchidos nesta chamada."""

    @abstractmethod
    def buscar(
        self,
        vetor_consulta: list[float],
        texto_consulta: str,
        filtros: FiltrosBusca,
        limite: int = 30,
        candidatos: int = 200,
    ) -> list[ResultadoBusca]:
        """Busca híbrida: similaridade vetorial + casamento lexical (tsvector),
        combinados por Reciprocal Rank Fusion, com filtros SQL."""

    @abstractmethod
    def garantir_indices(self) -> None:
        """Cria índices vetoriais (HNSW) se ainda não existirem. Idempotente."""

    @abstractmethod
    def close(self) -> None: ...


def _para_vetor_sql(vetor: list[float]) -> str:
    """Serializa um vetor Python para o literal texto do pgvector."""
    return "[" + ",".join(f"{x:.6f}" for x in vetor) + "]"


class PgVectorStore(VectorStore):
    """PostgreSQL 16 + pgvector — implementação padrão do MVP."""

    def __init__(self, db_url: str = DB_URL_PADRAO):
        self.conn = psycopg.connect(db_url, connect_timeout=5, autocommit=True)

    # ---------------- indexação ----------------

    def progresso_indexacao(self) -> dict[str, tuple[int, int]]:
        saida: dict[str, tuple[int, int]] = {}
        with self.conn.cursor() as cur:
            for tabela in TABELAS_VETORIAIS:
                cur.execute(
                    f"SELECT count(*), count(embedding) FROM {tabela}"  # tabela fixa no código
                )
                total, com = cur.fetchone()
                saida[tabela] = (total, com)
        return saida

    def salvar_embeddings(self, tabela: str, pares: list[tuple[int, list[float]]]) -> int:
        if tabela not in TABELAS_VETORIAIS:
            raise ValueError(f"Tabela vetorial desconhecida: {tabela}")
        if not pares:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(
                f"UPDATE {tabela} SET embedding = %s::vector WHERE id = %s",
                [(_para_vetor_sql(v), rid) for rid, v in pares],
            )
        return len(pares)

    def copiar_embeddings_para_espelhos(self) -> int:
        feitos = 0
        with self.conn.cursor() as cur:
            # laboratório → documento espelho (casa por nome + unidade)
            cur.execute(
                """
                UPDATE documento d
                SET embedding = l.embedding
                FROM laboratorio l
                WHERE d.tipo = 'ficha_lab'
                  AND d.embedding IS NULL
                  AND l.embedding IS NOT NULL
                  AND d.titulo = l.nome
                  AND coalesce(d.metadados->>'unidade', '') = coalesce(l.unidade, '')
                """
            )
            feitos += cur.rowcount
            # projeto de extensão → documento espelho (casa por título + câmpus)
            cur.execute(
                """
                UPDATE documento d
                SET embedding = p.embedding
                FROM projeto_extensao p
                WHERE d.tipo = 'projeto_extensao'
                  AND d.embedding IS NULL
                  AND p.embedding IS NOT NULL
                  AND d.titulo = p.titulo
                  AND coalesce(d.metadados->>'campus', '') = coalesce(p.campus, '')
                """
            )
            feitos += cur.rowcount
        return feitos

    # ---------------- busca híbrida ----------------

    def buscar(
        self,
        vetor_consulta: list[float],
        texto_consulta: str,
        filtros: FiltrosBusca,
        limite: int = 30,
        candidatos: int = 200,
    ) -> list[ResultadoBusca]:
        """RRF (k=60) entre o ranking vetorial (cosseno) e o lexical
        (tsvector em português sobre título+resumo+palavras-chave).

        A superfície de busca é a tabela `documento`, que espelha todos os
        tipos — teses, dissertações, works, projetos de extensão e fichas de
        laboratório — num ranking único, sem duplicatas.
        """
        sql = """
        WITH filtrado AS (
            -- tsv é coluna gerada (STORED) com índice GIN: o tsvector é
            -- calculado uma vez na gravação, não a cada busca (ver schema.sql)
            SELECT d.id, d.tipo, d.titulo, d.resumo, d.ano, d.url, d.metadados,
                   d.embedding, d.tsv AS sv
            FROM documento d
            WHERE d.embedding IS NOT NULL
              AND (%(tipos)s::text[] IS NULL OR d.tipo = ANY(%(tipos)s))
              AND (%(ano_min)s::int IS NULL OR d.ano >= %(ano_min)s)
              AND (%(ano_max)s::int IS NULL OR d.ano <= %(ano_max)s)
              AND (%(unidade)s::text IS NULL OR coalesce(
                     d.metadados->>'campus',
                     d.metadados->>'unidade',
                     d.metadados->>'dc.publisher.department', ''
                   ) ILIKE '%%' || %(unidade)s || '%%')
        ),
        vetorial AS (
            SELECT id,
                   row_number() OVER (ORDER BY embedding <=> %(vetor)s::vector) AS pos,
                   1 - (embedding <=> %(vetor)s::vector) AS sim
            FROM filtrado
            ORDER BY embedding <=> %(vetor)s::vector
            LIMIT %(candidatos)s
        ),
        lexical AS (
            SELECT id,
                   row_number() OVER (
                       ORDER BY ts_rank_cd(sv, websearch_to_tsquery('portuguese', %(texto)s)) DESC
                   ) AS pos
            FROM filtrado
            WHERE sv @@ websearch_to_tsquery('portuguese', %(texto)s)
            LIMIT %(candidatos)s
        ),
        fusao AS (
            SELECT coalesce(v.id, l.id) AS id,
                   coalesce(1.0 / (60 + v.pos), 0.0)
                   + coalesce(1.0 / (60 + l.pos), 0.0) AS score,
                   v.sim
            FROM vetorial v
            FULL OUTER JOIN lexical l ON l.id = v.id
        )
        SELECT f.id, f.tipo, f.titulo,
               left(coalesce(f.resumo, ''), 420) AS trecho,
               f.ano, f.url, f.metadados,
               coalesce(fu.sim, 0.0) AS similaridade,
               fu.score
        FROM fusao fu
        JOIN filtrado f ON f.id = fu.id
        ORDER BY fu.score DESC, fu.sim DESC NULLS LAST
        LIMIT %(limite)s
        """
        params = {
            "vetor": _para_vetor_sql(vetor_consulta),
            "texto": texto_consulta,
            "tipos": filtros.tipos,
            "unidade": filtros.unidade,
            "ano_min": filtros.ano_min,
            "ano_max": filtros.ano_max,
            "candidatos": candidatos,
            "limite": limite,
        }
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            linhas = cur.fetchall()

        resultados: list[ResultadoBusca] = []
        for rid, tipo, titulo, trecho, ano, url, meta, sim, score in linhas:
            meta = meta or {}
            unidade = (
                meta.get("campus")
                or meta.get("unidade")
                or meta.get("dc.publisher.department")
            )
            resultados.append(
                ResultadoBusca(
                    tabela="documento",
                    id=rid,
                    tipo=tipo,
                    titulo=(titulo or "").strip() or "(sem título na fonte — ver link)",
                    trecho=trecho or "",
                    ano=ano,
                    url=url,
                    unidade=unidade,
                    similaridade=float(sim),
                    score=float(score),
                    metadados=meta,
                )
            )
        return resultados

    # ---------------- índices ----------------

    def garantir_indices(self) -> None:
        with self.conn.cursor() as cur:
            for tabela in TABELAS_VETORIAIS:
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {tabela}_embedding_hnsw
                    ON {tabela} USING hnsw (embedding vector_cosine_ops)
                    """
                )

    def close(self) -> None:
        self.conn.close()
