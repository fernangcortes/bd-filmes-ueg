"""Conexão com o banco para os módulos de coleta/fusão."""
import os

import psycopg

DB_URL = os.getenv(
    "BD_FILMES_DB",
    "postgresql://crialab:crialab_local_dev@localhost:5432/crialab",
)


def conectar() -> psycopg.Connection:
    """Abre conexão com o banco (levanta exceção se indisponível)."""
    return psycopg.connect(DB_URL, connect_timeout=5)


def fonte_id_por_codigo(conn, codigo: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM fonte WHERE codigo = %s", (codigo,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Fonte '{codigo}' não cadastrada — o schema foi aplicado?")
    return row[0]


def marcar_coleta(conn, codigo: str) -> None:
    """Registra o momento da coleta bem-sucedida (base do incremental)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE fonte SET ultima_coleta = now() WHERE codigo = %s", (codigo,)
        )
