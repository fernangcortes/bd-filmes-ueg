"""Teste pontual: fastembed com parallel=N (vários processos) vs sequencial."""
import time

from fastembed import TextEmbedding

texto = "passage: " + (
    "Esta dissertação investiga as dinâmicas socioambientais do Cerrado goiano, "
    "com ênfase nas comunidades tradicionais e nos recursos hídricos da região. "
    * 8
)  # ~1.200 caracteres, tamanho típico após o corte
lotes = [texto] * 256

if __name__ == "__main__":
    m = TextEmbedding(
        model_name="intfloat/multilingual-e5-large",
        cache_dir="dados/modelos",
    )
    t0 = time.time()
    list(m.embed(lotes[:64], batch_size=32))
    print(f"sequencial 64 docs: {time.time()-t0:.1f}s")

    t0 = time.time()
    list(m.embed(lotes, batch_size=32, parallel=4))
    dt = time.time() - t0
    print(f"parallel=4, 256 docs: {dt:.1f}s -> {256/dt:.1f} docs/s")
