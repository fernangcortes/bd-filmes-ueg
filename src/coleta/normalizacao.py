"""Normalização de nomes para a consolidação light de pessoas (M1)."""
import unicodedata


def normalizar_nome(nome: str) -> str:
    """Minúsculo, sem acentos, tokens ordenados — chave de fusão por nome.

    Ex.: "Morais, Kenia Aparecida de" e "KENIA APARECIDA DE MORAIS"
    viram a mesma chave.
    """
    if not nome:
        return ""
    nome = nome.replace(",", " ")
    sem_acento = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    tokens = sem_acento.lower().split()
    return " ".join(sorted(tokens))
