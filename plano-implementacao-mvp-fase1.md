# Plano de Implementação — MVP da Fase 1: "Banco de Personagens CriaLab|UEG"

**Documento de engenharia — decisões consolidadas em 05/08/2026**
**Base:** `banco_ueg_crialab.final.md` (Vol. 1), `banco_ueg_crialab_vol2.final.md` (Vol. 2), `guia_desbloqueio_acessos_crialab.final.md`
**Restrição de fontes:** somente fontes marcadas como **acesso aberto/verificado ao vivo** (ago/2026) nos documentos de pesquisa.
**Premissas do gerente (Fernando):** qualidade > prazo; operação por usuários leigos; o agente decide a stack e consulta o gerente em decisões importantes.

***

## 1. O que o MVP é (e o que não é)

### 1.1 Definição do produto

Um aplicativo local de busca temática em que um produtor do CriaLab:

1. digita um **tema** (ex.: "Cerrado") **ou** anexa um **roteiro** (PDF/TXT/DOCX);
2. passa por um **assistente de refinamento** — tags normais, tags inteligentes (geradas por IA) e um chat para ajustar o escopo antes de pesquisar;
3. recebe resultados ranqueados de **publicações, projetos de extensão, laboratórios (prédio/sala/equipamentos) e pessoas (com contato institucional)**, cada item com link da fonte;
4. recebe um **resumo final gerado por IA** destacando os pesquisadores e *por que* cada um se encaixa em cada assunto do tema/roteiro;
5. pode ampliar a pesquisa para além das bases institucionais com uma **busca web** (notícias, artigos não científicos, documentos) via provedor de API escolhido pelo usuário;
6. exporta o resultado (Markdown/CSV).

### 1.2 Critérios de aceite do MVP

| #  | Critério                                                                                                                                                          | Como verificar                    |
| -- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| A1 | Busca por "Cerrado" retorna teses RENAC/TECCER (BDTD), projetos de extensão (CKAN) e laboratórios com prédio/sala (ueg.br), ranqueados, cada um com link da fonte | Teste manual na interface         |
| A2 | Upload de um roteiro PDF gera busca contextualizada melhor que o tema seco (tags inteligentes + resumo final citando pesquisadores e o porquê do encaixe)         | Teste com roteiro real do CriaLab |
| A3 | Uma pessoa leiga consegue instalar, iniciar, atualizar os dados e fazer uma busca sem tocar em código                                                             | Teste com usuário não-técnico     |
| A4 | Toda afirmação do resumo da IA tem citação clicável para a fonte                                                                                                  | Inspeção manual                   |
| A5 | Página LGPD + canal de opt-out funcionais antes de qualquer coleta                                                                                                | Checklist                         |
| A6 | Mesma pessoa aparecendo em fontes diferentes (orientador BDTD × coordenador CKAN × autor OpenAlex) é consolidada quando há identificador exato                    | Consulta SQL de verificação       |

### 1.3 Explicitamente fora do MVP (fica para fases seguintes)

* Portal de Periódicos OJS (25 revistas) — **decisão do gerente (Q2-C)**: atrás de WAF, entra na Fase 2 junto com a whitelist;

* RIUEG por scraping, Censos DGP, ORCID bulk, BrCris — Fase 2 (fusão e pessoas);

* Grafo Neo4j, GraphRAG, pacote de produção completo, densidade temática — Fase 3;

* Loop CriaLab (produções cadastradas), recolheita agendada automática — Fase 4;

* Expansão UFG — Fase 2+ (mas o schema já nasce multi-instituição, ver §6);

* Pedido LAI e e-mail de whitelist — **fora do plano (Q15)**, o gerente toca por conta própria se quiser.

***

## 2. Fontes de dados do MVP (todas abertas e verificadas)

| #  | Fonte                                                                | Endpoint/canal exato                                                                                                          | Volume esperado                                                                                            | Licença/base legal                                                                 | Estratégia                                                                                                                                                                  |
| -- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1 | **BDTD/UEG (DSpace 10.0)** — teses e dissertações                    | OAI-PMH: `https://bdtd.ueg.br/server/oai/request` · REST: `https://bdtd.ueg.br/server/api`                                    | \~1.700–1.900 registros                                                                                    | `openAccess`; termo de autorização para divulgação científica (Res. CsA 1087/2019) | Carga inicial via OAI (`oai_dc`, scythe); REST para metadados ricos (orientador com ORCID/Lattes, área CNPq, link PDF)                                                      |
| F2 | **CKAN Dados Abertos GO — org. UEG**                                 | API: `https://dadosabertos.go.gov.br/api/3/action/package_search?fq=organization:universidade-estadual-de-goias` + CSV direto | 15 datasets; foco em: extensão (tema↔coordenador↔câmpus), cargos (nome+Lattes+e-mail), bens móveis/imóveis | **CC-BY** (crédito à fonte)                                                        | API Action v3; snapshot dos CSVs no data lake                                                                                                                               |
| F3 | **Páginas de laboratórios ueg.br** — todas as 33 unidades / 8 câmpus | `https://www.ueg.br/{slug}/conteudo/{id}_laboratorios` → `https://www.ueg.br/{slug}/referencia/{id}`                          | Dezenas de laboratórios                                                                                    | Páginas públicas institucionais                                                    | Scraping educado: 1 req/s, janela noturna, User-Agent identificado (`CriaLab-UEG-Harvester/1.0`), respeito a robots.txt, tolerância a URLs legadas (`www.{unidade}.ueg.br`) |
| F4 | **OpenAlex** — camada de identidade e produção global                | `https://api.openalex.org/works?filter=institutions.id:I3129565396` · `authors?filter=last_known_institutions.id:I3129565396` | \~9.931 works; autores com ORCID                                                                           | CC0                                                                                | API REST com `mailto=` (polite pool); snapshot local                                                                                                                        |

**Regras invioláveis de coleta (dos documentos):** zero scraping da Plataforma Lattes (Portaria CNPq 976/2022); nada existe só na fonte — tudo passa pelo data lake bruto antes de qualquer tratamento; toda coleta registra proveniência (fonte, URL, data, licença) por registro.

***

## 3. Arquitetura do MVP

```
┌───────────────────────────────────┐
│ INTERFACE (Streamlit, pt-BR, para leigos)                            │
│  Busca simples | Assistente passo a passo | Upload de roteiro        │
│  Chat refinador | Resultados + resumo IA | Exportar | Cabine APIs    │
│  Botão "Atualizar dados" | Página LGPD/opt-out                       │
├───────────────────────────────────┤
│ ORQUESTRADOR DE BUSCA                                                │
│  Entendimento (LLM: tema/roteiro → tags inteligentes, sub-consultas)│
│  → Busca híbrida local (SQL + vetorial) → Reranqueador             │
│  → Busca web externa (opcional, provedor escolhido)                 │
│  → Síntese final com citações (LLM)                                 │
├───────────────────────────────────┤
│ ARMAZENAMENTO                                                        │
│  PostgreSQL 16 + pgvector (dados + vetores, via Docker)              │
│  Data lake bruto: pastas versionadas (XML/JSON/CSV/HTML originais)   │
├───────────────────────────────────┤
│ COLETA (scripts Python, incrementais)                                │
│  F1 BDTD OAI+REST | F2 CKAN API | F3 Labs scraping | F4 OpenAlex     │
└───────────────────────────────────┘
```

**Decisões-chave já tomadas:**

* **Linguagem: Python 3.12** — todo o ecossistema necessário (OAI-PMH, scraping, embeddings, LLM, Streamlit) vive em Python; é também a linguagem dos casos de referência dos relatórios.

* **PostgreSQL 16 + pgvector** via Docker Compose (imagem `pgvector/pgvector:pg16`) — ver explicação didática da Q10: qualidade de busca se decide no embedding + reranqueador, não no banco vetorial; pgvector mantém um serviço só para instalar e backupear. O código terá interface `VectorStore` que permite migrar para Qdrant no futuro sem reescrever a busca.

* **Embeddings: bge-m3 local via fastembed (ONNX/CPU)** — roda no i7-10700 com 32 GB de RAM; carga inicial de \~15–20 mil documentos leva algumas horas, uma única vez; atualizações são pequenas. Quando a render farm com GPUs NVIDIA chegar, o mesmo componente aponta para ela (ou para API) sem mudar código.

* **LLM local opcional via Ollama**; LLM em nuvem configurável na Cabine de APIs (§7).

* **Coleta incremental por datestamp** com botão "Atualizar dados" na interface — ver explicação didática da Q11.

***

## 4. Estrutura do repositório

Repositório **público na conta pessoal do Fernando no GitHub** (Q12); migração para organização UEG fica para decisão burocrática futura. Nome sugerido: `bd-filmes-ueg` (a confirmar na criação).

```
bd-filmes-ueg/
├── README.md                  # guia de instalação para leigos (passo a passo com prints)
├── docker-compose.yml         # PostgreSQL + pgvector
├── iniciar.bat                # 1 clique: sobe o banco + abre o app
├── instalar.bat               # 1 clique: verifica Python/Docker, cria venv, instala tudo
├── pyproject.toml
├── config/
│   ├── instituicoes.yaml      # UEG = 1ª linha (formato Vol. 2, §3.2) — expansão vira config
│   └── apis.example.yaml      # chaves e provedores (o arquivo real fica fora do git)
├── src/
│   ├── coleta/                # harvesters: bdtd_oai.py, bdtd_rest.py, ckan.py,
│   │                          #   laboratorios.py, openalex.py — todos incrementais
│   ├── lago/                  # data lake bruto (gravacao/versionamento de originais)
│   ├── banco/                 # schema.sql, models.py, vectorstore.py (interface pgvector)
│   ├── fusao/                 # consolidacao light de pessoas (§6.3)
│   ├── busca/                 # entendimento.py, hibrida.py, rerank.py, sintese.py, websearch/
│   ├── llm/                   # provedores: ollama, deepseek, kimi, qwen, openrouter (interface unica)
│   └── app/                   # Streamlit: paginas busca, assistente, resultados,
│                              #   cabine_apis, atualizar_dados, lgpd
├── dados/                     # data lake bruto + banco (fora do git, no disco externo se preciso)
└── testes/
```

***

## 5. Modelo de dados (PostgreSQL)

Princípios: **proveniência obrigatória** (todo registro aponta fonte + URL + data de coleta) e **schema multi-instituição desde o dia 1** (Vol. 2: cadastrar universidade vira uma linha de configuração, não um projeto novo).

```sql
instituicao(id, nome, ror, openalex_id, circulo, config_jsonb)          -- UEG: ROR 03ta25k06, I3129565396
fonte(id, instituicao_id, tipo, url_base, licenca, ultima_coleta)       -- F1..F4
documento(id, fonte_id, tipo, titulo, resumo, palavras_chave, ano,      -- tese/TCC/artigo/projeto/lab
          autores_raw, url, pdf_url, metadados_jsonb, embedding vector(1024))
pessoa(id, nome_canonico, orcid, lattes_url, email, vinculo, unidade,   -- consolidacao light
       confianca_fusao, optout boolean default false)
pessoa_documento(pessoa_id, documento_id, papel)                        -- autor/orientador/coordenador/responsavel
laboratorio(id, instituicao_id, unidade, nome, descricao, predio, sala,
            responsavel_nome, responsavel_email, equipamentos text[], url_fonte)
projeto_extensao(id, titulo, coordenacao, colaboradores, area_tematica,
                 campus, local_execucao, url_fonte)
busca_log(id, entrada_usuario, roteiro_anexado, tags_usadas, provedores_usados, criado_em)
optout(id, nome, identificador, motivo, criado_em, atendido_em)
```

***

## 6. Pipeline de coleta (detalhe por fonte)

### 6.1 F1 — BDTD/UEG (`coleta/bdtd_oai.py`, `bdtd_rest.py`)

1. **Descoberta automática** (regra do Vol. 2): `GET /server/api` → se HAL JSON, é DSpace 7+ → usar REST + OAI nativos.
2. **Carga inicial OAI-PMH** com `oaipmh-scythe`: `ListRecords&metadataPrefix=oai_dc`, respeitando `resumptionToken`, ignorando registros `deleted`; cada XML original vai para `dados/lago/bdtd/AAAA-MM-DD/`.
3. **Enriquecimento REST**: para cada item, `GET /server/api/core/items/{uuid}` e bundles/bitstreams → autor, **orientador (com ORCID e URL Lattes quando houver)**, programa, câmpus, palavras-chave PT/EN, área CNPq, resumo, data de defesa, link PDF.
4. **Incremental**: `from={ultima_coleta}` salvo em `fonte.ultima_coleta`.
5. **Fallback documentado**: BDTD nacional (`bdtd.ibict.br`, prefixo `UEG-2_`) se a instância local cair — implementado como config alternativa, não automática no MVP.

### 6.2 F2 — CKAN GO (`coleta/ckan.py`)

1. `package_search?fq=organization:universidade-estadual-de-goias` → lista de datasets e URLs de recurso.
2. Download dos CSVs prioritários: **Projetos/Ações de Extensão e Locais de Execução**, **Cargos e seus ocupantes**, **Bens Imóveis**, **Bens Patrimoniais Móveis**. (FAPEG: config opcional, desligada por padrão.)
3. Normalização para `projeto_extensao` e `pessoa` (coordenadores com e-mail funcional e Lattes do dataset de cargos).
4. Atribuição obrigatória: campo "Fonte: Dados Abertos Goiás (CC-BY)" exibido na interface.

### 6.3 F3 — Laboratórios (`coleta/laboratorios.py`)

1. Lista de slugs das 33 unidades em `config/instituicoes.yaml`.
2. Para cada unidade: varrer `{slug}/conteudo/*_laboratorios` → extrair links `referencia/{id}`.
3. Parser dos rótulos fixos: Unidade / Curso(s) / Descrição / Objetivos / **Localização (Prédio, Sala)** / **Contato (Nome, E-mail)** / **Equipamentos** / Imagens.
4. Subsites de PPG (ex.: RENAC `ueg.br/iacsb/renac/`) e ESEFFEGO como configs adicionais de mesmo parser.
5. Tolerância: URLs legadas `www.{unidade}.ueg.br`; falha em uma unidade não derruba as demais (log + segue).

### 6.4 F4 — OpenAlex (`coleta/openalex.py`)

1. `works?filter=institutions.id:I3129565396` com cursor de paginação, `mailto=` configurado → \~9.931 works (título, resumo invertido, autores com ORCID, tópicos, ano, DOI).
2. `authors?filter=last_known_institutions.id:I3129565396` → pesquisadores com ORCID e contagens.
3. Alimenta `documento` e `pessoa` (âncora ORCID da consolidação).

### 6.5 Consolidação light de pessoas (`fusao/`) — resposta à Q8

Somente fusões **determinísticas e seguras** (nada de heurística arriscada no MVP):

1. **ORCID exato** (OpenAlex × BDTD) → mesma pessoa;
2. **URL Lattes idêntica** (CKAN cargos × BDTD orientador) → mesma pessoa;
3. **Nome normalizado** (sem acento, minúsculo, tokens ordenados) **+ mesma unidade/câmpus** → fusão marcada `confianca_fusao='media'`, revisável.

Sem identificador: permanecem entradas separadas — honesto, e a Fase 2 faz a fusão profunda (BrCris/heurísticas). **Regra LGPD:** pessoa com `optout=true` some da interface e dos resumos, mas o dado bruto fica retido no lake para auditoria.

***

## 7. Busca aprimorada e Cabine de APIs (resposta à Q13)

### 7.1 Pipeline de busca (5 estágios)

1. **Entendimento** — entrada = tema curto **ou** roteiro anexado (extração de texto de PDF/TXT/DOCX). O LLM gera: sinopse estruturada, **tags inteligentes** (sub-temas, biomas, territórios, saberes, personagens implícitos) e sub-consultas. No modo roteiro, cada bloco/assunto vira uma sub-consulta.
2. **Assistente (wizard)** — o usuário revisa: tags normais (câmpus, tipo de material, período, área CNPq) + tags inteligentes sugeridas pela IA (liga/desliga) + **chat refinador** ("quero mais pesquisadores de campo, menos teoria" → ajusta as consultas). Só então dispara a busca.
3. **Busca híbrida local** — vetorial (pgvector, bge-m3) **+** filtros SQL (tags, tipo, unidade) sobre todas as fontes locais. Sem pressa de latência (Q7): orçamento de até \~60 s no modo profundo.
4. **Reranqueador** — `bge-reranker-v2-m3` local (CPU) reordena o top-50 de cada sub-consulta. *É aqui, não no banco vetorial, que a qualidade salta.*
5. **Síntese final (LLM)** — resumo em pt-BR destacando **pesquisadores e por que cabem em cada assunto**, com citação clicável por afirmação + seções: Personagens / Locações & equipamentos / Pesquisas / Web (quando ativa). Exportável em MD/CSV.

### 7.2 Busca web externa (`busca/websearch/`)

Camada opcional por consulta (toggle na tela), para notícias, artigos não científicos e documentos — sempre rotulada "fora das bases institucionais" e com as mesmas regras de citação.

### 7.3 Matriz de APIs por função — e como o usuário escolhe

A **Cabine de APIs** é uma tela de configuração em que cada função tem provedores rotulados: 🟢 **local/grátis**, 💰 **custo-benefício**, 💎 **topo de linha** — com estimativa de custo por busca exibida antes de executar.

| Função                          | 🟢 Local/grátis                                                                                  | 💰 Custo-benefício                                                                                                    | 💎 Topo de linha                                            |
| ------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **LLM de entendimento/síntese** | Ollama local (ex.: Qwen2.5 14B) — grátis, privado, qualidade média; render farm futura turbinará | **DeepSeek** (padrão recomendado: excelente pt-BR, centavos/busca) · Kimi (contexto longo, bom para roteiros grandes) | Claude/GPT via **OpenRouter** (melhor síntese, custo maior) |
| **Embeddings**                  | **bge-m3 local** (padrão; grátis)                                                                | OpenAI/Voyage (se o local ficar lento demais)                                                                         | —                                                           |
| **Reranqueador**                | **bge-reranker local** (padrão)                                                                  | Cohere Rerank API                                                                                                     | —                                                           |
| **Busca web**                   | **Brave Search API** (2.000/mês grátis)                                                          | **Tavily** (feita para LLM, 1.000/mês grátis) · Google Custom Search (100/dia grátis)                                 | SerpAPI (pago, completo)                                    |

Padrões de fábrica (zero configuração para começar): LLM local Ollama + embeddings locais + rerank local + web desligada. O usuário ativa APIs pagas quando quiser, colando a chave na Cabine — o app sugere "melhor custo-benefício" (DeepSeek) ou "melhor qualidade" (OpenRouter/Claude) com uma frase de explicação cada.

***

## 8. LGPD e opt-out (Q9 — obrigatório desde a semana 1)

* Página "Privacidade (LGPD)" no app: finalidade, bases legais (art. 7º, III/IV/IX), fontes usadas, contato para remoção;

* Formulário de opt-out → tabela `optout`; rotina aplica a remoção na interface e nas sínteses;

* Somente dados institucionais/funcionais (@ueg.br, lotação, Lattes público) — nunca dados sensíveis;

* ROPA mínimo documentado no repositório (`docs/ROPA.md`);

* Dados de contato exibidos como insumo interno de pré-produção (aviso na tela), nunca republicados em massa.

***

## 9. Operação para leigos (Q4)

* `instalar.bat`: verifica Python e Docker Desktop, cria ambiente, instala dependências, sobe o banco;

* `iniciar.bat`: sobe o banco e abre o app no navegador;

* Botão **"Atualizar dados"** na interface: roda os 4 coletores incrementais com barra de progresso e relatório ("BDTD: +3 teses novas; Laboratórios: 2 fichas alteradas");

* Erros viram mensagens em português claro ("A fonte X não respondeu; seus dados anteriores continuam disponíveis") — o data lake garante que nada se perde;

* README com prints + vídeo curto de demonstração.

***

## 10. Marcos de implementação (sem prazo duro — qualidade manda; estimativas indicativas)

| Marco                            | Conteúdo                                                                                                                                              | Critério de conclusão                                                                                                                                                                                                                                   | Estimativa      |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| **M0 — Fundação** ✅              | Repo público no GitHub do Fernando; Docker Compose (Postgres+pgvector); schema; `instituicoes.yaml` com UEG; página LGPD/opt-out no app; scripts .bat | ✅ App abre com página LGPD; banco sobe com 1 clique                                                                                                                                                                                                     | concluído 05/08 |
| **M1 — BDTD no ar** ✅            | Coletores OAI+REST, lake bruto, carga completa das teses                                                                                              | ✅ `documento` populado: **1.748 teses/dissertações, 2.032 pessoas (1.587 com Lattes)**; botão "Atualizar dados" ativo. Nota: OAI local com índice vazio (migração DSpace 10) → varredura via REST discover com retries; OAI reservado para incrementais | concluído 05/08 |
| **M2 — CKAN + Laboratórios** ✅   | Coletores F2 e F3 (33 unidades + 8 câmpus + institutos/PPG RENAC); tabelas `projeto_extensao` e `laboratorio`                                                                          | ✅ **685 projetos de extensão** (+686 docs espelho p/ busca), **2.096 pessoas** (+50 cargos CKAN com Lattes/e-mail, +14 responsáveis de lab), **70 laboratórios** em 11 unidades (15 com prédio/sala/e-mail completos); 91 coordenadores casados com pessoas existentes; 3 botões ativos. Notas §12.1                                                                                                 | concluído 06/08 |
| **M3 — OpenAlex + consolidação** | Coletor F4; fusão light (§6.5)                                                                                                                        | Autores com ORCID consolidados; verificação A6                                                                                                                                                                                                          | \~1 semana      |
| **M4 — Busca básica**            | Embeddings bge-m3 (carga inicial); busca híbrida no Streamlit: tema → resultados ranqueados com fonte                                                 | Critério A1                                                                                                                                                                                                                                             | \~2 semanas     |
| **M5 — Assistente inteligente**  | Wizard de tags, chat refinador, upload de roteiro + entendimento LLM                                                                                  | Critério A2 (parcial: sem web)                                                                                                                                                                                                                          | \~2 semanas     |
| **M6 — Web + síntese + Cabine**  | Camada websearch, síntese final com pesquisadores e porquês, Cabine de APIs, exportação MD/CSV                                                        | Critérios A2 e A4 completos                                                                                                                                                                                                                             | \~2 semanas     |
| **M7 — Polimento e demo**        | Rerank afinado, testes, README com prints, roteiro de demo para o Marcelo, verificação A3 com leigo                                                   | Todos os critérios A1–A6                                                                                                                                                                                                                                | \~1 semana      |

Total indicativo: **\~10–12 semanas de trabalho do agente**, sem data de corte. Ao final de cada marco, relatório curto ao gerente com demonstração e decisões pendentes.

***

## 11. Riscos do MVP e mitigações (herdados dos relatórios)

| Risco                                                   | Mitigação no MVP                                                                                                 |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Fonte UEG instável (404 intermitente, servidor legado)  | Data lake bruto (nada existe só na fonte); retries com backoff; mensagem amigável + dados anteriores preservados |
| Qualidade irregular de metadados (títulos concatenados) | Normalização na ETL; nunca confiar em campo cru; metadados originais preservados no lake                         |
| Mudança de layout das páginas de laboratório            | Parser por rótulos fixos + testes de contrato; falha isola a unidade, não o todo                                 |
| Embeddings lentos em CPU                                | Carga única noturna; fastembed/ONNX; render farm futura como acelerador plugável                                 |
| Custo de APIs de LLM                                    | Padrão 100% local; custo estimado exibido antes de cada busca paga; log de consumo                               |
| LGPD/reclamação de titular                              | Opt-out funcional desde o M0; dados funcionais apenas; ROPA documentado                                          |

***

## 12. Decisões que precisam do gerente (registro vivo)

1. **Nome do repositório GitHub** — sugiro `bd-filmes-ueg`. Confirmar antes da criação (ação pública e visível).
2. **Chaves de API** — quando quiser ativar DeepSeek/Kimi/OpenRouter/Brave/Tavily, o gerente cria as contas e cola as chaves na Cabine de APIs (nunca no git).
3. **E-mail de contato para o opt-out** — sugiro um e-mail do CriaLab; confirmar qual.
4. **Roteiro real para o teste A2** — o gerente fornece um roteiro do CriaLab quando chegarmos ao M5.

### 12.1 Decisões operacionais registradas no M2 (06/08/2026) — revisar se discordar

1. **Coordenador de extensão sem separador de nomes** — no CSV do CKAN, "Coordenação e colaboradores" traz vários nomes concatenados em caixa alta, sem delimitador. Para não criar pessoas fictícias, o coletor só *vincula* o projeto a uma pessoa quando o texto casa exatamente com uma pessoa já existente (91 casamentos nesta carga). Quem não existe na base continua visível no campo `coordenacao` do projeto, mas não vira registro de pessoa. Fase 2 pode extrair os demais com NER/heurística.
2. **Bens imóveis/móveis** — ficam como snapshot bruto versionado no data lake (85 mil linhas de bens móveis não cabem no modelo do MVP; imóveis vêm só com dados patrimoniais, sem endereço útil). Sem tabela própria por ora.
3. **Laboratórios: 4 formatos de página tratados** — (A) ficha com rótulos fixos (prédio/sala/e-mail/equipamentos: Palmeiras); (B) lista textual com coordenadores (ESEFFEGO); (B2) lista de siglas (CCSEH: 18 centros/labs, inclui LUPPA e LIM-LIFE — áudio-visual); (C) página própria por lab (Laranjeiras: 7, inclui o próprio CriaLab; PPG RENAC: 11, via config `paginas_lab`). ~20 unidades não têm página de laboratórios no CMS (conteúdo "não disponível" ou inexistente) — registrado; Fase 2 pode tentar navegador headless para as páginas em JavaScript.
4. **Janela noturna** — a carga inicial rodou de dia por ser manual e única, mantidos 1 req/s e User-Agent identificado. Recargas completas agendadas (Fase 4) seguem a janela 22h–06h do config.
5. **Documentos de sessão** — sumários e prompts de sessão ficam em `docs/sumarios-prompts-sessoes/` (fora do git, memória operacional local); o plano e o README continuam versionados na raiz.

***

*Plano gerado a partir dos três documentos de pesquisa e das 15 respostas do gerente (05/08/2026). Todas as fontes de dados do MVP são de acesso aberto e foram verificadas ao vivo entre 04 e 08/08/2026, conforme registrado nos relatórios.*
