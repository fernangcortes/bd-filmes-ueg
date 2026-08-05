"""Data lake bruto — cópia local imutável de tudo que é coletado.

Regra de ouro dos relatórios: nenhum dado existe apenas "na fonte".
Cada resposta bruta (JSON/XML) é gravada antes de qualquer tratamento,
em pastas por fonte e data: dados/lago/<FONTE>/<AAAA-MM-DD>/...
"""
import json
from datetime import datetime
from pathlib import Path

RAIZ_LAGO = Path(__file__).resolve().parents[2] / "dados" / "lago"


def _pasta(fonte_codigo: str) -> Path:
    hoje = datetime.now().strftime("%Y-%m-%d")
    pasta = RAIZ_LAGO / fonte_codigo / hoje
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def salvar_json(fonte_codigo: str, nome_arquivo: str, conteudo) -> Path:
    """Grava JSON bruto no lake e devolve o caminho."""
    destino = _pasta(fonte_codigo) / nome_arquivo
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=1)
    return destino


def salvar_texto(fonte_codigo: str, nome_arquivo: str, conteudo: str) -> Path:
    """Grava texto bruto (XML/HTML) no lake e devolve o caminho."""
    destino = _pasta(fonte_codigo) / nome_arquivo
    with open(destino, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return destino
