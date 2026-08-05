"""Conexão com o banco — Banco de Personagens CriaLab|UEG.

Tolerante a falha: se o banco estiver fora do ar, retorna None e a
interface mostra uma mensagem amigável em vez de quebrar.
"""
import os

import psycopg

DB_URL = os.getenv(
    "BD_FILMES_DB",
    "postgresql://crialab:crialab_local_dev@localhost:5432/crialab",
)


def conectar():
    """Retorna uma conexão psycopg ou None se o banco estiver indisponível."""
    try:
        return psycopg.connect(DB_URL, connect_timeout=3)
    except Exception:
        return None


def contar(tabela: str) -> int | None:
    """Conta registros de uma tabela; None se o banco estiver indisponível."""
    conn = conectar()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {tabela}")  # tabela é fixa no código
            return cur.fetchone()[0]
    finally:
        conn.close()
