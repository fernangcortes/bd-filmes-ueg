"""Entendimento do tema/roteiro (M5 — plano §7.1 estágio 1).

Entrada: tema curto OU texto de roteiro → saída: PacoteBusca com
  * sinopse            — o que entendemos do pedido (1-2 frases);
  * tags_inteligentes  — sub-temas/territórios/saberes sugeridos p/ liga-desliga;
  * subconsultas       — consultas independentes que alimentam a buscar_agrupada().

Dois motores (o usuário nunca fica na mão):
  * 🧠 IA (API online — DeepSeek/Kimi/OpenRouter, plano §7.3; decisão 07/08:
    esta máquina é lenta demais para Ollama local): usada se houver chave
    configurada na ⚙️ Cabine; qualquer falha cai para o modo básico.
  * ⚡ Modo básico (heurístico, sem IA): divisão do roteiro em blocos +
    extração de termos fortes por frequência. Transparente e previsível.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from src.llm import LLMIndisponivel, obter_cliente

MAX_TAGS = 8
MAX_SUBCONSULTAS = 6
MAX_CARACTERES_SUBCONSULTA = 220

# Stopwords pt-BR (modo básico) — o suficiente para não sujar as tags.
STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "em", "no", "na", "nos",
    "nas", "um", "uma", "uns", "umas", "para", "com", "por", "que", "se",
    "ao", "aos", "à", "às", "ou", "como", "mais", "mas", "foi", "são", "ser",
    "sua", "seu", "suas", "seus", "ele", "ela", "eles", "elas", "isso", "isto",
    "esse", "essa", "este", "esta", "entre", "sobre", "até", "após", "quando",
    "onde", "muito", "já", "também", "não", "sim", "the", "and", "of", "in",
    "cena", "int", "ext", "dia", "noite", "fade", "cut", "close",
}


@dataclass
class PacoteBusca:
    """Tudo que o wizard precisa para o usuário revisar antes de buscar."""

    entrada_original: str
    modo: str                          # tema | roteiro
    sinopse: str
    tags_inteligentes: list[str] = field(default_factory=list)
    subconsultas: list[str] = field(default_factory=list)
    provedor: str = "basico"           # ollama | basico
    aviso: str | None = None           # motivo da queda p/ modo básico, se houve


# ---------------------------------------------------------------------------
# Motor de IA local (Ollama)
# ---------------------------------------------------------------------------

_SISTEMA = (
    "Você é o estágio de entendimento de um motor de busca temático da "
    "Universidade Estadual de Goiás (UEG). Seu trabalho é ler o pedido de um "
    "produtor audiovisual e devolver APENAS um JSON válido, sem texto antes ou "
    "depois, neste formato exato:\n"
    '{"sinopse": "...", "tags": ["...", "..."], "subconsultas": ["...", "..."]}\n'
    "Regras: sinopse = 1-2 frases do que se procura; tags = 3 a 8 sub-temas, "
    "territórios, biomas, saberes ou perfis de personagens implícitos "
    "(termos curtos, em português); subconsultas = 1 a 6 consultas de busca "
    "independentes, cada uma focada em um assunto diferente, escritas como "
    "frases temáticas que ajudem a encontrar pesquisadores, teses, projetos "
    "de extensão e laboratórios da UEG."
)


def _extrair_json(texto: str) -> dict:
    """Tolerante a LLM que enrola: pega do primeiro '{' ao último '}'."""
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        raise ValueError("resposta sem JSON")
    return json.loads(texto[inicio : fim + 1])


def _via_llm(entrada: str, modo: str, instrucao_extra: str | None) -> PacoteBusca:
    cliente = obter_cliente()
    ok, motivo = cliente.disponivel()
    if not ok:
        raise LLMIndisponivel(motivo)

    rotulo = "ROTEIRO" if modo == "roteiro" else "TEMA"
    prompt = f"{rotulo} DO PRODUTOR:\n{entrada}\n"
    if instrucao_extra:
        prompt += f"\nAJUSTE PEDIDO PELO USUÁRIO (obedeça): {instrucao_extra}\n"
    prompt += "\nResponda APENAS o JSON."

    bruto = cliente.gerar(prompt, sistema=_SISTEMA)
    dados = _extrair_json(bruto)

    subconsultas = [str(s).strip() for s in dados.get("subconsultas", []) if str(s).strip()]
    if not subconsultas:
        raise ValueError("LLM não devolveu sub-consultas")

    return PacoteBusca(
        entrada_original=entrada,
        modo=modo,
        sinopse=str(dados.get("sinopse", "")).strip(),
        tags_inteligentes=[str(t).strip() for t in dados.get("tags", []) if str(t).strip()][:MAX_TAGS],
        subconsultas=subconsultas[:MAX_SUBCONSULTAS],
        provedor=cliente.rotulo,
    )


# ---------------------------------------------------------------------------
# Modo básico (sem IA) — heurística transparente
# ---------------------------------------------------------------------------

def _cortar_frase(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    pedaco = texto[:limite]
    return (pedaco.rsplit(" ", 1)[0] if " " in pedaco else pedaco).strip()


def _termos_fortes(texto: str, maximo: int) -> list[str]:
    """Palavras frequentes (≥5 letras, fora das stopwords) como candidatas a tag."""
    palavras = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]{5,}", texto.lower())
    comuns = Counter(p for p in palavras if p not in STOPWORDS).most_common(maximo * 2)
    # devolve com a capitalização original da 1ª ocorrência
    resultado, vistos = [], set()
    for termo, _ in comuns:
        if termo in vistos:
            continue
        vistos.add(termo)
        achado = re.search(rf"\b{re.escape(termo)}\b", texto, re.IGNORECASE)
        resultado.append(achado.group(0) if achado else termo)
        if len(resultado) >= maximo:
            break
    return resultado


def _blocos_roteiro(texto: str) -> list[str]:
    """Divide o roteiro em blocos temáticos (parágrafos duplos), descarta
    blocos curtos demais (falas soltas) e limita a quantidade/tamanho."""
    brutos = [b.strip() for b in re.split(r"\n\s*\n", texto) if len(b.strip()) >= 80]
    # blocos mais informativos primeiro (tamanho como proxy simples)
    brutos.sort(key=len, reverse=True)
    return [_cortar_frase(b, MAX_CARACTERES_SUBCONSULTA) for b in brutos[:MAX_SUBCONSULTAS]]


def _via_basico(entrada: str, modo: str, aviso: str | None) -> PacoteBusca:
    if modo == "roteiro":
        subconsultas = _blocos_roteiro(entrada)
        if not subconsultas:  # roteiro sem blocos longos: usa o começo
            subconsultas = [_cortar_frase(entrada, MAX_CARACTERES_SUBCONSULTA)]
        sinopse = "Roteiro dividido em blocos temáticos (modo básico, sem IA)."
    else:
        subconsultas = [_cortar_frase(entrada.strip(), MAX_CARACTERES_SUBCONSULTA)]
        sinopse = f"Busca direta pelo tema informado: {entrada.strip()[:140]}"

    return PacoteBusca(
        entrada_original=entrada,
        modo=modo,
        sinopse=sinopse,
        tags_inteligentes=_termos_fortes(entrada, MAX_TAGS),
        subconsultas=subconsultas,
        provedor="basico",
        aviso=aviso,
    )


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def analisar(
    entrada: str,
    modo: str = "tema",
    instrucao_extra: str | None = None,
    forcar_basico: bool = False,
) -> PacoteBusca:
    """Tema/roteiro → pacote de busca revisável. IA local quando possível,
    modo básico como rede de segurança (o motivo da queda vai em `aviso`)."""
    entrada = (entrada or "").strip()
    if not entrada:
        raise ValueError("entrada vazia")

    if not forcar_basico:
        try:
            return _via_llm(entrada, modo, instrucao_extra)
        except (LLMIndisponivel, ValueError, json.JSONDecodeError) as exc:
            aviso = f"IA local indisponível ({exc}). Usando o modo básico."
        except Exception as exc:  # LLM é best-effort: nunca derruba o wizard
            aviso = f"Falha inesperada na IA local ({exc.__class__.__name__}). Usando o modo básico."
    else:
        aviso = None

    pacote = _via_basico(entrada, modo, aviso)
    if instrucao_extra:
        # sem IA, o ajuste fino vira um acréscimo explícito nas sub-consultas
        pacote.subconsultas = [
            _cortar_frase(f"{s} {instrucao_extra}", MAX_CARACTERES_SUBCONSULTA)
            for s in pacote.subconsultas
        ]
        pacote.sinopse += f" Ajuste aplicado: “{instrucao_extra}”."
    return pacote
