"""Coletor F2 — CKAN Dados Abertos GO (organização UEG, licença CC-BY).

Verificado ao vivo em 06/08/2026: API Action v3 responde 15 datasets da UEG.
Prioridade do MVP (plano §6.2):
- "Projetos/Ações de Extensão e Locais de Execução" → tabela projeto_extensao
  (+ documento tipo 'projeto_extensao' para a busca do M4);
- "Cargos e seus ocupantes UEG" → pessoa (nome, Lattes, e-mail funcional);
- "Bens Imóveis" e "Bens Patrimoniais Móveis" → snapshot bruto no data lake
  (mapeamento físico de locações/equipamentos patrimoniados; sem tabela
  própria no MVP).

Decisão de qualidade: o campo "Coordenação e colaboradores" do CSV de
extensão traz nomes concatenados SEM separador confiável. Para não criar
pessoas fictícias, o coordenador só é vinculado quando o texto casa
exatamente com uma pessoa já existente na base (consolidação light).

Regras: tudo passa pelo data lake bruto; atribuição CC-BY exibida no app.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import time
from typing import Callable

import requests
from psycopg.types.json import Jsonb

from src.banco.conexao import conectar, fonte_id_por_codigo, marcar_coleta
from src.coleta.lago import salvar_json, salvar_texto
from src.coleta.pessoas import (
    pessoa_id_por_nome_exato,
    upsert_pessoa,
    vincular_documento,
)

API = "https://dadosabertos.go.gov.br/api/3/action"
ORG = "universidade-estadual-de-goias"
FONTE = "F2-CKAN"
UA = {"User-Agent": "CriaLab-UEG-Harvester/1.0 (+github.com/fernangcortes/bd-filmes-ueg)"}
PAUSA_S = 0.5

DATASET_EXTENSAO = "projetos-acoes-de-extensao-e-locais-de-execucao"
DATASET_CARGOS = "cargos-e-seus-ocupantes"
DATASET_IMOVEIS = "bens-imoveis-da-universidade-estadual-de-goias"
DATASET_MOVEIS = "bens-patrimoniais-moveis"
SNAPSHOT_APENAS = {DATASET_IMOVEIS, DATASET_MOVEIS}  # só data lake (plano §6.2)

ATRIBUICAO = "Fonte: Dados Abertos Goiás (CC-BY)"

Progresso = Callable[[str, float | None], None]


def _log(progresso: Progresso | None, msg: str, frac: float | None = None) -> None:
    if progresso:
        progresso(msg, frac)
    else:
        print(msg, flush=True)


def _get_json(sess: requests.Session, url: str, **params) -> dict:
    r = sess.get(url, params=params, timeout=60)
    r.raise_for_status()
    dados = r.json()
    if not dados.get("success"):
        raise RuntimeError(f"CKAN respondeu success=false para {url}")
    return dados["result"]


def _baixar_csv(sess: requests.Session, url: str) -> str:
    r = sess.get(url, timeout=180)
    r.raise_for_status()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return r.content.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.content.decode("latin-1", errors="replace")


def _linhas_csv(texto: str) -> list[dict]:
    """Detecta delimitador (; ou ,) e devolve lista de dicts."""
    primeira = texto.splitlines()[0] if texto.splitlines() else ""
    delim = ";" if primeira.count(";") > primeira.count(",") else ","
    reader = csv.DictReader(io.StringIO(texto), delimiter=delim)
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _recurso_csv_mais_recente(dataset: dict) -> dict | None:
    """Escolhe o recurso CSV mais recente de um dataset CKAN."""
    candidatos = [
        r for r in dataset.get("resources", [])
        if (r.get("format") or "").upper() == "CSV" and r.get("url")
    ]
    if not candidatos:
        return None
    return sorted(candidatos, key=lambda r: r.get("last_modified") or r.get("created") or "")[-1]


def _instituicao_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM instituicao WHERE sigla = 'UEG'")
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("Instituição UEG não cadastrada — o schema foi aplicado?")
    return row[0]


# ----------------------------------------------------------- extensão

def _carregar_extensao(conn, cur, fonte_id: int, inst_id: int,
                       linhas: list[dict], url_csv: str, progresso) -> dict:
    stats = {"projetos": 0, "coordenadores_vinculados": 0}
    for i, row in enumerate(linhas):
        titulo = row.get("Título", "").strip()
        if not titulo:
            continue
        campus = row.get("Setor/Câmpus/UnU", "").strip()
        coordenacao = " ".join(row.get("Coordenação e colaboradores", "").split())
        area_tematica = row.get("Área Temática", "").strip()
        modalidade = row.get("Modalidade", "").strip()
        programa = row.get("Programa de Extensão", "").strip()
        area_conhecimento = row.get("Área Conhecimento", "").strip()
        linha_ext = row.get("Linha de Extensão", "").strip()
        exercicio = row.get("Exercício", "").strip()
        codigo_acao = row.get("Código Ação", "").strip()

        cur.execute(
            """
            INSERT INTO projeto_extensao (instituicao_id, titulo, coordenacao,
                                          area_tematica, campus, local_execucao,
                                          url_fonte, metadados)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instituicao_id, titulo, campus) DO UPDATE SET
                coordenacao = EXCLUDED.coordenacao,
                area_tematica = EXCLUDED.area_tematica,
                url_fonte = EXCLUDED.url_fonte,
                metadados = EXCLUDED.metadados,
                coletado_em = now()
            """,
            (
                inst_id, titulo, coordenacao or None, area_tematica or None,
                campus or None, None, url_csv,
                Jsonb({
                    "modalidade": modalidade, "programa": programa,
                    "area_conhecimento": area_conhecimento,
                    "linha_extensao": linha_ext, "exercicio": exercicio,
                    "codigo_acao": codigo_acao, "atribuicao": ATRIBUICAO,
                }),
            ),
        )

        # documento espelho para a busca (M4 embedda documento)
        ext_id = f"extensao:{codigo_acao}" if codigo_acao else \
            "extensao:" + hashlib.sha1(f"{titulo}|{campus}".encode()).hexdigest()[:16]
        resumo = ". ".join(p for p in [
            f"{modalidade} de extensão" if modalidade else "Ação de extensão",
            f"programa {programa}" if programa else "",
            f"área temática {area_tematica}" if area_tematica else "",
            f"linha {linha_ext}" if linha_ext else "",
            f"coordenação: {coordenacao.title()}" if coordenacao else "",
        ] if p)
        cur.execute(
            """
            INSERT INTO documento (fonte_id, tipo, titulo, resumo, ano,
                                   autores_raw, url, identificador_externo, metadados)
            VALUES (%s, 'projeto_extensao', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fonte_id, identificador_externo) DO UPDATE SET
                titulo = EXCLUDED.titulo, resumo = EXCLUDED.resumo,
                autores_raw = EXCLUDED.autores_raw, metadados = EXCLUDED.metadados,
                coletado_em = now()
            RETURNING id
            """,
            (
                fonte_id, titulo, resumo or None,
                int(exercicio[-4:]) if exercicio[-4:].isdigit() else None,
                [coordenacao.title()] if coordenacao else None,
                url_csv, ext_id,
                Jsonb({"campus": campus, "modalidade": modalidade,
                       "area_tematica": area_tematica, "atribuicao": ATRIBUICAO}),
            ),
        )
        doc_id = cur.fetchone()[0]

        # vínculo de coordenador: somente se o nome casa exato com pessoa existente
        pid = pessoa_id_por_nome_exato(cur, coordenacao)
        if pid is not None:
            vincular_documento(cur, pid, doc_id, "coordenador")
            stats["coordenadores_vinculados"] += 1

        stats["projetos"] += 1
        if (i + 1) % 100 == 0:
            conn.commit()
            _log(progresso, f"Extensão: {i + 1}/{len(linhas)} projetos…")
    conn.commit()
    return stats


# ----------------------------------------------------------- cargos

def _carregar_cargos(conn, cur, linhas: list[dict]) -> dict:
    stats = {"ocupantes": 0}
    for row in linhas:
        pid = upsert_pessoa(
            cur,
            row.get("Nome"),
            lattes_url=row.get("Currículo Lattes"),
            email=row.get("E-mail"),
            vinculo=row.get("Cargo") or None,
        )
        if pid is not None:
            stats["ocupantes"] += 1
    conn.commit()
    return stats


# ----------------------------------------------------------- fluxo

def executar(progresso: Progresso | None = None) -> dict:
    """Coleta CKAN completa (idempotente): lake bruto + carga normalizada."""
    stats = {"datasets": 0, "projetos": 0, "ocupantes": 0,
             "coordenadores_vinculados": 0, "snapshots": 0}
    conn = conectar()
    sess = requests.Session()
    sess.headers.update(UA)

    try:
        fonte_id = fonte_id_por_codigo(conn, FONTE)
        inst_id = _instituicao_id(conn)

        _log(progresso, "Consultando a API do CKAN (organização UEG)…", 0.0)
        resultado = _get_json(sess, f"{API}/package_search",
                              fq=f"organization:{ORG}", rows=100)
        salvar_json(FONTE, "package_search.json", resultado)
        datasets = {d["name"]: d for d in resultado["results"]}
        stats["datasets"] = len(datasets)
        _log(progresso, f"{len(datasets)} datasets encontrados; baixando CSVs prioritários…", 0.05)

        alvos = [DATASET_EXTENSAO, DATASET_CARGOS, DATASET_IMOVEIS, DATASET_MOVEIS]
        for pos, nome in enumerate(alvos):
            dataset = datasets.get(nome)
            if dataset is None:
                _log(progresso, f"⚠️ Dataset '{nome}' não encontrado na API — pulando.")
                continue
            recurso = _recurso_csv_mais_recente(dataset)
            if recurso is None:
                _log(progresso, f"⚠️ Dataset '{nome}' sem recurso CSV — pulando.")
                continue
            url_csv = recurso["url"]
            _log(progresso, f"Baixando {dataset['title']}…")
            texto = _baixar_csv(sess, url_csv)
            salvar_texto(FONTE, f"{nome}.csv", texto)
            time.sleep(PAUSA_S)

            if nome in SNAPSHOT_APENAS:
                stats["snapshots"] += 1
                _log(progresso, f"Snapshot bruto guardado no data lake ({nome}).")
                continue

            linhas = _linhas_csv(texto)
            with conn.cursor() as cur:
                if nome == DATASET_EXTENSAO:
                    r = _carregar_extensao(conn, cur, fonte_id, inst_id,
                                           linhas, url_csv, progresso)
                    stats.update(r)
                elif nome == DATASET_CARGOS:
                    stats.update(_carregar_cargos(conn, cur, linhas))
            frac = 0.1 + 0.9 * (pos + 1) / len(alvos)
            _log(progresso, f"{dataset['title']}: {len(linhas)} linhas processadas.", frac)

        marcar_coleta(conn, FONTE)
        conn.commit()
    finally:
        conn.close()
        sess.close()

    _log(progresso, "Coleta CKAN concluída.", 1.0)
    return stats


def main() -> None:
    argparse.ArgumentParser(description="Coletor CKAN Dados Abertos GO").parse_args()
    executar()


if __name__ == "__main__":
    main()
