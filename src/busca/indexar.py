"""Indexação de embeddings — carga inicial e incremental (M4).

Percorre as três coleções vetoriais (documento, laboratorio, projeto_extensao)
gravando vetores onde `embedding IS NULL` — portanto é **idempotente e
retomável**: se for interrompida (ou o tempo limite da rodada estourar),
basta rodar de novo; ela continua de onde parou.

Ordem das coleções:
  1. laboratorio (entidade)         → vetor copiado p/ espelho em documento
  2. projeto_extensao (entidade)    → vetor copiado p/ espelho em documento
  3. documento (tese/dissertacao/work)
  4. espelhos que sobraram sem par  → texto montado dos próprios campos

Uso em lote (linha de comando, com limite de tempo por rodada):
  .venv/Scripts/python -m src.busca.indexar --max-segundos 260

Uso no app (botão, até o fim):
  from src.busca.indexar import executar
  stats = executar(progresso=lambda msg, frac: print(msg, frac))
"""
from __future__ import annotations

import argparse
import time
from typing import Callable

from src.banco.vectorstore import PgVectorStore
from src.busca.embeddings import MAX_CARACTERES, GeradorEmbeddings

Progresso = Callable[[str, float | None], None]

LOTE = 64


# ---------------------------------------------------------------------------
# Montagem dos textos de indexação (título primeiro; resumo ocupa o restante
# do orçamento de caracteres do modelo)
# ---------------------------------------------------------------------------

def _montar(cabeca: list[str], corpo: str | None) -> str:
    base = "\n".join(p for p in cabeca if p)
    sobra = MAX_CARACTERES - len(base) - 1
    if corpo and sobra > 0:
        base = (base + "\n" + corpo[:sobra]).strip()
    return base


def texto_documento(titulo, resumo, palavras_chave, metadados) -> str:
    cabeca = [titulo or ""]
    if palavras_chave:
        cabeca.append("Palavras-chave: " + ", ".join(palavras_chave[:12]))
    meta = metadados or {}
    programa = meta.get("dc.publisher.program")
    if programa:
        cabeca.append(f"Programa: {programa}")
    topicos = meta.get("topicos")
    if isinstance(topicos, list) and topicos:
        cabeca.append("Tópicos: " + ", ".join(str(t) for t in topicos[:8]))
    return _montar(cabeca, resumo)


def texto_laboratorio(nome, descricao, unidade, predio, sala, equipamentos, metadados) -> str:
    cabeca = [nome or ""]
    if unidade:
        cabeca.append(f"Laboratório da {unidade} (UEG).")
    if equipamentos:
        cabeca.append("Equipamentos: " + ", ".join(equipamentos[:15]))
    meta = metadados or {}
    cursos = meta.get("cursos")
    if isinstance(cursos, list) and cursos:
        cabeca.append("Cursos atendidos: " + ", ".join(str(c) for c in cursos[:8]))
    elif isinstance(cursos, str) and cursos:
        cabeca.append(f"Cursos atendidos: {cursos}")
    local = " ".join(p for p in (f"Prédio {predio}" if predio else "", f"Sala {sala}" if sala else ""))
    if local.strip():
        cabeca.append(f"Localização: {local.strip()}.")
    return _montar(cabeca, descricao)


def texto_projeto(titulo, coordenacao, area_tematica, campus, local_execucao, metadados) -> str:
    cabeca = [titulo or ""]
    meta = metadados or {}
    modalidade = meta.get("modalidade")
    cabeca.append(f"{(modalidade or 'Projeto/ação').title()} de extensão universitária (UEG).")
    if area_tematica:
        cabeca.append(f"Área temática: {area_tematica}")
    if campus:
        cabeca.append(f"Câmpus: {campus}")
    if coordenacao:
        cabeca.append(f"Coordenação: {coordenacao}")
    if local_execucao:
        cabeca.append(f"Local de execução: {local_execucao}")
    return _montar(cabeca, None)


CONSULTAS_PENDENTES = {
    "documento": (
        "SELECT id, titulo, resumo, palavras_chave, metadados FROM documento "
        "WHERE embedding IS NULL AND tipo IN ('tese', 'dissertacao', 'work') "
        "ORDER BY length(coalesce(resumo, '')) DESC, id LIMIT %s",
        lambda linha: texto_documento(linha[1], linha[2], linha[3], linha[4]),
    ),
    "laboratorio": (
        "SELECT id, nome, descricao, unidade, predio, sala, equipamentos, metadados "
        "FROM laboratorio WHERE embedding IS NULL ORDER BY id LIMIT %s",
        lambda linha: texto_laboratorio(*linha[1:]),
    ),
    "projeto_extensao": (
        "SELECT id, titulo, coordenacao, area_tematica, campus, local_execucao, metadados "
        "FROM projeto_extensao WHERE embedding IS NULL ORDER BY id LIMIT %s",
        lambda linha: texto_projeto(linha[1], linha[2], linha[3], linha[4], linha[5], linha[6]),
    ),
    "espelhos": (
        "SELECT id, titulo, resumo, palavras_chave, metadados FROM documento "
        "WHERE embedding IS NULL AND tipo IN ('ficha_lab', 'projeto_extensao') "
        "ORDER BY id LIMIT %s",
        lambda linha: texto_documento(linha[1], linha[2], linha[3], linha[4]),
    ),
}

TABELA_DA_COLECAO = {
    "documento": "documento",
    "laboratorio": "laboratorio",
    "projeto_extensao": "projeto_extensao",
    "espelhos": "documento",
}

ORDEM = ["laboratorio", "projeto_extensao", "documento", "espelhos"]

ROTULOS = {
    "laboratorio": "laboratórios",
    "projeto_extensao": "projetos de extensão",
    "documento": "teses, dissertações e artigos",
    "espelhos": "fichas restantes",
}


# ---------------------------------------------------------------------------
# Rotina principal
# ---------------------------------------------------------------------------

def executar(
    progresso: Progresso | None = None,
    max_segundos: float | None = None,
) -> dict:
    """Indexa o que falta. Retorna estatísticas; `concluido=False` indica que
    a rodada parou pelo limite de tempo e deve ser chamada de novo."""

    def avisar(msg: str, frac: float | None = None) -> None:
        if progresso:
            progresso(msg, frac)

    inicio = time.monotonic()
    loja = PgVectorStore()
    gerador = None  # lazy: só carrega o modelo se houver algo pendente
    processados = 0

    try:
        totais = loja.progresso_indexacao()
        pendente_total = sum(t - c for t, c in totais.values())
        total_geral = sum(t for t, _ in totais.values())
        if pendente_total == 0:
            avisar("Tudo já estava indexado — nada a fazer.", 1.0)
            loja.garantir_indices()
            return _stats(loja, processados, inicio, concluido=True)

        avisar(
            f"Carregando o modelo de embeddings (na 1ª vez baixa ~2,2 GB da internet)…",
            0.0,
        )
        gerador = GeradorEmbeddings.obter()
        avisar(f"Modelo pronto. {pendente_total:,} de {total_geral:,} registros a indexar.".replace(",", "."), 0.0)

        for colecao in ORDEM:
            consulta, montar = CONSULTAS_PENDENTES[colecao]
            tabela = TABELA_DA_COLECAO[colecao]
            rotulo = ROTULOS[colecao]

            while True:
                if max_segundos and (time.monotonic() - inicio) > max_segundos:
                    avisar("Tempo desta rodada esgotado — continue na próxima.", None)
                    return _stats(loja, processados, inicio, concluido=False)

                with loja.conn.cursor() as cur:
                    cur.execute(consulta, (LOTE * 2,))  # margem p/ texto vazio
                    linhas = cur.fetchall()
                if not linhas:
                    break

                # textos vazios recebem vetor do próprio título (montar nunca
                # devolve vazio porque cabeça sempre tem o título/nome)
                textos = [montar(l) for l in linhas[:LOTE]]
                vetores = gerador.embed_documentos(textos)
                pares = [(l[0], v) for l, v in zip(linhas, vetores)]
                loja.salvar_embeddings(tabela, pares)
                processados += len(pares)

                feitos = processados
                frac = min(feitos / max(pendente_total, 1), 1.0)
                avisar(f"Indexando {rotulo}: +{len(pares)} (total nesta rodada: {feitos:,})".replace(",", "."), frac)

            # ao fim de cada entidade, replica vetores para os espelhos
            if colecao in ("laboratorio", "projeto_extensao"):
                espelhos = loja.copiar_embeddings_para_espelhos()
                if espelhos:
                    avisar(f"{espelhos} documentos espelho herdaram o vetor da entidade.", None)

        loja.garantir_indices()
        return _stats(loja, processados, inicio, concluido=True)
    finally:
        loja.close()


def _stats(loja: PgVectorStore, processados: int, inicio: float, concluido: bool) -> dict:
    totais = loja.progresso_indexacao()
    decorrido = time.monotonic() - inicio
    return {
        "concluido": concluido,
        "processados_nesta_rodada": processados,
        "segundos": round(decorrido, 1),
        "velocidade": round(processados / decorrido, 1) if decorrido > 0 else 0,
        "progresso": {t: {"total": t_, "com_embedding": c_} for t, (t_, c_) in totais.items()},
        "pendentes": sum(t_ - c_ for t_, c_ in totais.values()),
    }


def zerar_embeddings() -> None:
    """Apaga todos os vetores (para reindexação do zero com outro modelo/config)."""
    loja = PgVectorStore()
    try:
        with loja.conn.cursor() as cur:
            for tabela in ("documento", "laboratorio", "projeto_extensao"):
                cur.execute(f"UPDATE {tabela} SET embedding = NULL")
    finally:
        loja.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexação de embeddings (retomável)")
    parser.add_argument("--max-segundos", type=float, default=None,
                        help="para a rodada após N segundos (padrão: até concluir)")
    parser.add_argument("--forcar", action="store_true",
                        help="zera todos os embeddings e reindexa do zero")
    args = parser.parse_args()

    if args.forcar:
        zerar_embeddings()
        print("Embeddings zerados — reindexação do zero.")

    def progresso(msg: str, frac: float | None) -> None:
        pct = f" [{frac * 100:5.1f}%]" if frac is not None else ""
        print(f"{time.strftime('%H:%M:%S')} {msg}{pct}", flush=True)

    stats = executar(progresso=progresso, max_segundos=args.max_segundos)
    print("RESUMO:", stats, flush=True)


if __name__ == "__main__":
    main()
