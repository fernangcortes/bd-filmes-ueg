# Resumo da sessão — 05/08/2026

**Projeto:** Banco de Personagens CriaLab|UEG (motor de busca temático: tema/roteiro → personagens, locações, equipamentos e pesquisas da UEG)
**Gerente:** Fernando Gomes Côrtes · **Repo:** https://github.com/fernangcortes/bd-filmes-ueg (público, MIT)
**Workspace:** `C:\Users\FGC\Desktop\programas\bd-filmes-UEG`

---

## 1. O que aconteceu nesta sessão

1. **Análise dos 3 documentos de pesquisa** (`docs-pesquisa-implementacao/`): Vol. 1 (ecossistema de bases UEG + arquitetura 6 camadas + roadmap 4 fases), Vol. 2 (expansão UFG/panorama), Guia de Desbloqueio (acessos institucionais).
2. **Rodada de 15 perguntas** ao gerente → decisões consolidadas → **plano detalhado do MVP da Fase 1** escrito em `plano-implementacao-mvp-fase1.md`.
3. **M0 — Fundação** ✅ concluído e publicado.
4. **M1 — Coleta BDTD/UEG** ✅ concluído e publicado (commit `25b6415`).

## 2. Decisões-chave do gerente (as 15 respostas)

- Fontes do MVP: **BDTD/UEG + CKAN GO + laboratórios (33 unidades) + OpenAlex**; **OJS fora do MVP** (WAF → Fase 2);
- Roda na **máquina local** (i7-10700, 32 GB RAM, sem GPU; render farm NVIDIA futura será acelerador plugável);
- Latência de busca pode passar de 10 s se melhorar a qualidade;
- **Alguma consolidação de pessoas** já no MVP (light, determinística);
- LGPD/opt-out **dentro** do MVP desde o início;
- pgvector (decisão do agente, explicada: qualidade vem de embedding+rerank, não do banco vetorial; migração p/ Qdrant possível via interface);
- Coleta **incremental** com botão manual (sem agendador até a Fase 4);
- Código **público no GitHub pessoal**; migração p/ UEG depois (burocracia);
- Busca rica: tema **ou roteiro** → assistente com tags normais+inteligentes+chat → busca híbrida → web externa opcional → resumo IA com pesquisadores e porquês; **Cabine de APIs** (🟢 local / 💰 custo-benefício / 💎 topo de linha);
- **Sem prazo duro** — qualidade manda; LAI e whitelist **fora** do plano (gerente toca por conta própria se quiser).

## 3. Estado atual verificado

**Banco (Docker `bd-filmes-ueg-db`, Postgres 16 + pgvector, sobe com `iniciar.bat`):**
- 9 tabelas + seeds: UEG (ROR 03ta25k06 / OpenAlex I3129565396) e 5 fontes (F1–F4);
- **1.748 teses/dissertações** BDTD (1.717 dissert. + 31 teses);
- **2.032 pessoas** (1.748 autores + 1.748 orientadores ligados); **1.587 com Lattes (78%)**, 28 com ORCID.

**Data lake:** `dados/lago/F1-BDTD-REST/2026-08-05/` (72 páginas JSON brutas; gitignored).

**App Streamlit:** home com status; 🔒 Privacidade LGPD com opt-out **funcional**; 🔄 Atualizar dados com botão BDTD ativo (barra de progresso); Busca e Cabine de APIs como placeholders.

## 4. Descobertas operacionais importantes

- **OAI-PMH local da BDTD está com índice vazio** (migração DSpace 10 em andamento, ago/2026) → coleta primária via **REST discover** (`/server/api/discover/search/objects?projection=full`, páginas de 25, retries com backoff, fatiamento `--ini/--fim`); OAI reservado p/ incrementais futuras;
- Espelho nacional (bdtd.ibict.br) está **atrás de anti-bot** — fallback indisponível no momento;
- Servidor UEG é frágil: páginas grandes estouram timeout (usar páginas pequenas sempre);
- Docker nesta máquina **não está no PATH** do Git Bash: usar `C:\Program Files\Docker\Docker\resources\bin\docker.exe` ou o plugin `resources\cli-plugins\docker-compose.exe` (os `.bat` já tratam isso);
- `.venv` local tem: streamlit, psycopg[binary], oaipmh-scythe, requests, pyyaml, lxml (faltam fastembed, pypdf, python-docx etc. — `pip install -e .` completa);
- `git push` funciona direto (credenciais Windows configuradas); commits locais usam `-c user.name=fernangcortes -c user.email=fernangcortes@users.noreply.github.com`;
- `docs-pesquisa-implementacao/` fica **fora do GitHub** (dados operacionais sensíveis) — está no `.gitignore`.

## 5. Pendências registradas (decisões do gerente, plano §12)

1. Chaves de API quando ativar (DeepSeek/Kimi/OpenRouter/Brave/Tavily) — colar na Cabine de APIs, nunca no git;
2. E-mail de contato para opt-out — definir qual o do CriaLab;
3. Roteiro real do CriaLab para o teste de aceite A2 (marco M5).

## 6. Próximo passo: M2

Coletores **CKAN Dados Abertos GO** (package_search org. UEG → CSVs de extensão/cargos/bens, CC-BY) e **laboratórios ueg.br** (33 unidades, parser de rótulos fixos, 1 req/s, janela noturna, UA identificado). Popular `projeto_extensao` e `laboratorio`; alimentar `pessoa` com coordenadores/responsáveis. Detalhes: `plano-implementacao-mvp-fase1.md` §6.2–6.3.
