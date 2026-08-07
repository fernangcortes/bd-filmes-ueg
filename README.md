# 🎬 Banco de Personagens — CriaLab|UEG

Motor de busca temático que conecta o **tema de um filme/programa** (ou um **roteiro**)
às **pessoas, locações, equipamentos e pesquisas da UEG** — construído exclusivamente
sobre **fontes de dados abertas e verificadas**.

Projeto do **CriaLab|UEG** (Laboratório de Pesquisas Criativas e Inovação em
Audiovisual, UnU Goiânia-Laranjeiras).

## O que ele faz (MVP — Fase 1)

1. Você digita um tema (ex.: "Cerrado") ou anexa um roteiro (PDF/TXT/DOCX);
2. Um assistente passo a passo refina a pesquisa (tags normais + tags inteligentes + chat);
3. O sistema devolve, ranqueado e com a fonte de cada item:
   - 👤 **personagens** (pesquisadores com contato institucional),
   - 📍 **locações** (laboratórios com prédio/sala/câmpus),
   - 🔬 **equipamentos**,
   - 📚 **pesquisas** (teses, dissertações, projetos de extensão);
4. Uma IA resume destacando os pesquisadores e **por que cabem em cada assunto**;
5. Opcional: amplia com busca web (notícias, artigos, documentos).

### Fontes de dados do MVP (todas abertas/verificadas)

| Fonte | O que traz | Licença |
|---|---|---|
| BDTD/UEG (DSpace 10, OAI-PMH + REST) | ~1.800 teses e dissertações, orientadores com ORCID/Lattes | Acesso aberto |
| Dados Abertos GO (CKAN) | Projetos de extensão, cargos, bens da UEG | CC-BY |
| Laboratórios ueg.br (33 unidades) | Prédio, sala, equipamentos, e-mail do responsável | Páginas públicas |
| OpenAlex | ~10 mil works da UEG (DOI, resumo, tópicos) e pesquisadores com ORCID | CC0 |

## Como instalar (Windows — sem programação)

**Pré-requisitos (uma vez só):**
1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado e aberto
2. [Python 3.12+](https://www.python.org/downloads/) — marque **"Add python.exe to PATH"** na instalação

**Instalação:** dê dois cliques em **`instalar.bat`** e aguarde.

**Uso diário:** dê dois cliques em **`iniciar.bat`** — o sistema abre no navegador.

**Busca inteligente (primeira vez):** depois de instalar, rode a indexação dos
embeddings **uma única vez** — pelo botão "Indexar embeddings" na página
🔄 Atualizar dados **ou** dois cliques em **`indexar.bat`** (janela preta que
pode ficar rodando sozinha; leva ~1,5–2 h, pode fechar e continuar depois —
ela sempre segue de onde parou). Sem isso, a página 🔎 Busca não encontra nada.

Para encerrar, feche a janela preta do terminal. Seus dados ficam guardados.

## Estrutura

```
├── instalar.bat / iniciar.bat   # operação por 1 clique
├── indexar.bat                  # carga inicial dos embeddings (busca inteligente)
├── docker-compose.yml           # banco PostgreSQL + pgvector
├── config/
│   ├── instituicoes.yaml        # cadastro de instituições (expansão = nova linha)
│   └── apis.example.yaml        # modelo de chaves (copie para apis.yaml)
├── src/
│   ├── app/                     # interface Streamlit (busca, assistente, LGPD, APIs)
│   ├── banco/schema.sql         # modelo de dados · vectorstore.py (interface pgvector)
│   ├── coleta/                  # bdtd.py · ckan.py · laboratorios.py · openalex.py · pessoas.py (M1–M3)
│   ├── busca/                   # embeddings.py · indexar.py · hibrida.py (M4)
│   └── fusao/ llm/              # (marcos seguintes)
└── docs/ROPA.md                 # registro LGPD de tratamento
```

## Roadmap

- **M0 — Fundação** ✅ (repo, banco, schema, página LGPD/opt-out)
- **M1 — Coleta BDTD/UEG** ✅ (1.748 teses/dissertações, 2.032 pessoas, 1.587 com Lattes — botão "Atualizar dados" ativo)
- **M2 — CKAN + Laboratórios** ✅ (685 projetos de extensão, 2.096 pessoas, 70 laboratórios em 11 unidades — 3 botões ativos)
- **M3 — OpenAlex + consolidação** ✅ (9.941 works, 4.825 pesquisadores UEG, 8.618 pessoas na base — 3.074 com ORCID; critério A6 verificado: 923 pessoas em 2 fontes, 63 em 3; 4 botões ativos)
- **M4 — Busca básica** ✅ (embeddings locais `multilingual-e5-large` via fastembed/CPU — mesma dimensão 1024 do bge-m3 previsto, ver §12.3 do plano; **13.200/13.200 vetores indexados**; busca híbrida RRF vetorial+lexical em **5 seções ranqueadas** (teses · dissertações · artigos · extensão · laboratórios) na página 🔎 Busca — critério A1 verificado com índice 100%; tsvector em coluna gerada com índice GIN (busca quente ~0,5 s); indexação retomável por botão no app ou `indexar.bat`. Decisões §12.3 e §12.4)
- M5 — Assistente inteligente + roteiro
- M6 — Web + síntese + Cabine de APIs
- M7 — Polimento e demo

O plano detalhado está em [`plano-implementacao-mvp-fase1.md`](plano-implementacao-mvp-fase1.md).
Fases 2–4 (fusão profunda, grafo, loop CriaLab) nos relatórios de pesquisa.

## Privacidade

Somente dados profissionais já públicos, com bases legais no art. 7º da LGPD,
canal de opt-out na própria interface e registro ROPA em `docs/ROPA.md`.

## Licença

[MIT](LICENSE) — código aberto. Dados das fontes sob suas licenças originais
(CC-BY Dados Abertos GO, CC0 OpenAlex, acesso aberto BDTD/UEG).
