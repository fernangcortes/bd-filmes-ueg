# Prompt para a próxima sessão (copie tudo abaixo)

---

Estamos construindo o **Banco de Personagens CriaLab|UEG** — motor de busca temático (tema/roteiro → personagens, locações, equipamentos e pesquisas da UEG) sobre fontes 100% abertas. Eu sou o gerente (Fernando); você é o especialista que implementa.

**Leia primeiro, nesta ordem:**
1. `C:\Users\FGC\Desktop\programas\bd-filmes-UEG\resumo-sessao-2026-08-05.md` — estado completo do projeto, decisões e pendências;
2. `C:\Users\FGC\Desktop\programas\bd-filmes-UEG\plano-implementacao-mvp-fase1.md` — plano detalhado do MVP (seções §6.2 e §6.3 são o M2);
3. Os 3 relatórios em `C:\Users\FGC\Desktop\programas\bd-filmes-UEG\docs-pesquisa-implementacao\` quando precisar de detalhe de fonte (endpoints, licenças, riscos).

**Estado:** M0 (fundação) e M1 (coleta BDTD: 1.748 teses, 2.032 pessoas) concluídos e publicados em https://github.com/fernangcortes/bd-filmes-ueg. Banco Postgres+pgvector roda via Docker; app Streamlit em `src/app/`; coletores em `src/coleta/` com data lake em `dados/lago/`.

**Tarefa desta sessão — M2:** implementar os coletores **CKAN Dados Abertos GO** (API `https://dadosabertos.go.gov.br/api/3/action/package_search?fq=organization:universidade-estadual-de-goias`, 15 datasets CC-BY — prioridade: "Projetos/Ações de Extensão e Locais de Execução", "Cargos e seus ocupantes UEG", "Bens Imóveis", "Bens Patrimoniais Móveis") e **laboratórios ueg.br** (todas as 33 unidades/8 câmpus: `{slug}/conteudo/{id}_laboratorios` → `referencia/{id}`, rótulos fixos Prédio/Sala/Contato/Equipamentos; 1 req/s, User-Agent identificado, tolerância a URLs legadas). Popular as tabelas `projeto_extensao`, `laboratorio` e alimentar `pessoa` (coordenadores/responsáveis) com a consolidação light já existente. Depois ligar os botões na página "🔄 Atualizar dados", verificar o banco, commit + push.

**Regras permanentes:** qualidade > prazo; operação por leigos (1 clique); proveniência e data lake brutos obrigatórios; zero scraping do Lattes; LGPD (dados funcionais apenas, opt-out respeitado); me consulte em decisões importantes e explique conceitos complicados didaticamente; ao final, atualize o plano e o README, commite e me mostre os números verificados no banco.

---
