"""Benchmark pontual do multilingual-e5-large (fastembed/ONNX/CPU).

Baixa o modelo (~2,2 GB) na 1ª execução. E5 exige prefixos:
"passage: " para documentos e "query: " para consultas.
"""
import time

from fastembed import TextEmbedding

MODELO = "intfloat/multilingual-e5-large"

t0 = time.time()
modelo = TextEmbedding(model_name=MODELO)
print(f"modelo carregado/baixado em {time.time()-t0:.1f}s")

textos = [
    "passage: Cerrado: biodiversidade, recursos hídricos e comunidades tradicionais "
    "do norte de Goiás. Este trabalho analisa as práticas agroextrativistas e a "
    "conservação do bioma em parceria com comunidades locais.",
] * 16

t0 = time.time()
vetores = list(modelo.embed(textos, batch_size=16))
dt = time.time() - t0
print(f"16 textos curtos em {dt:.2f}s -> {16/dt:.1f} docs/s, dim={len(vetores[0])}")

longo = (
    "passage: Esta dissertação investiga as dinâmicas socioambientais do Cerrado "
    "goiano, com ênfase nas comunidades tradicionais e nos recursos hídricos da "
    "bacia do rio Tocantins. " * 20
)  # ~3,7 mil caracteres
t0 = time.time()
vetores = list(modelo.embed([longo] * 8, batch_size=8))
dt = time.time() - t0
print(f"8 textos longos (~3,7 mil chars) em {dt:.2f}s -> {8/dt:.1f} docs/s")

q = list(modelo.embed(["query: Cerrado"]))[0]
d = list(modelo.embed(["passage: Estudo sobre a fauna do Cerrado goiano."]))[0]
import numpy as np
sim = float(np.dot(q, d) / (np.linalg.norm(q) * np.linalg.norm(d)))
print(f"similaridade query/passage 'Cerrado': {sim:.3f}")
