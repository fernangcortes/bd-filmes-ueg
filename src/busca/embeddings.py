"""Geração local de embeddings — fastembed (ONNX/CPU).

Modelo padrão: intfloat/multilingual-e5-large (1024 dim, ~100 línguas, MIT).
Decisão M4 (plano §12.3): o plano original previa bge-m3, mas ele ainda não
está disponível nas releases publicadas do fastembed (suporte mergeado no
repositório, aguardando publicação no PyPI). O e5-large multilíngue tem a
mesma dimensão (1024) — nenhuma alteração de schema — e desempenho equivalente
para português. A troca futura é uma linha (BD_FILMES_MODELO_EMBEDDING) +
reindexação.

E5 exige prefixos: "passage: " para documentos, "query: " para consultas
(sem eles a qualidade cai sensivelmente — convenção oficial do modelo).

O modelo (~2,2 GB) é baixado uma única vez e fica em dados/modelos/ —
pasta persistente, fora do git (não usar cache temporário do Windows).
"""
from __future__ import annotations

import os
from pathlib import Path

# Raiz do repositório (…/bd-filmes-UEG)
RAIZ = Path(__file__).resolve().parents[2]

MODELO_PADRAO = "intfloat/multilingual-e5-large"
DIMENSAO = 1024

# E5 trunca em 512 tokens. Limitamos a ~1.300 caracteres (~350 tokens):
# título + palavras-chave + início do resumo carregam o sinal temático para
# recuperação, e o custo de CPU cai pela metade na carga inicial (plano §12.3).
MAX_CARACTERES = 1300

PREFIXO_DOCUMENTO = "passage: "
PREFIXO_CONSULTA = "query: "


def _cache_modelos() -> str:
    pasta = RAIZ / "dados" / "modelos"
    pasta.mkdir(parents=True, exist_ok=True)
    return str(pasta)


def nome_modelo() -> str:
    return os.getenv("BD_FILMES_MODELO_EMBEDDING", MODELO_PADRAO)


class GeradorEmbeddings:
    """Singleton preguiçoso: o modelo só é carregado/baixado no primeiro uso."""

    _instancia: "GeradorEmbeddings | None" = None

    def __init__(self) -> None:
        from fastembed import TextEmbedding  # import tardio (app abre rápido)

        self.modelo = TextEmbedding(
            model_name=nome_modelo(),
            cache_dir=_cache_modelos(),
        )

    @classmethod
    def obter(cls) -> "GeradorEmbeddings":
        if cls._instancia is None:
            cls._instancia = cls()
        return cls._instancia

    @staticmethod
    def preparar_texto(texto: str) -> str:
        """Corta o texto no teto útil do modelo (512 tokens ≈ 1.900 chars),
        recuando ao último espaço para não quebrar palavras (subtokens ruins)."""
        if len(texto) <= MAX_CARACTERES:
            return texto
        pedaco = texto[:MAX_CARACTERES]
        return pedaco.rsplit(" ", 1)[0] if " " in pedaco else pedaco

    def embed_documentos(self, textos: list[str], lote: int = 32) -> list[list[float]]:
        """Vetoriza documentos (prefixo 'passage:'). Retorna vetores L2-normalizados."""
        entradas = [PREFIXO_DOCUMENTO + self.preparar_texto(t) for t in textos]
        return [v.tolist() for v in self.modelo.embed(entradas, batch_size=lote)]

    def embed_consulta(self, texto: str) -> list[float]:
        """Vetoriza uma consulta (prefixo 'query:')."""
        vetor = next(iter(self.modelo.embed([PREFIXO_CONSULTA + self.preparar_texto(texto)])))
        return vetor.tolist()
