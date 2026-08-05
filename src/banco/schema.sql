-- ============================================================
-- Banco de Personagens CriaLab|UEG — schema do MVP (Fase 1)
-- PostgreSQL 16 + pgvector. Aplicado automaticamente na 1ª subida
-- do container (docker-entrypoint-initdb.d).
--
-- Princípios (dos relatórios de pesquisa):
--  * proveniência obrigatória: todo registro aponta fonte + URL + data;
--  * multi-instituição desde o dia 1 (expansão vira configuração);
--  * LGPD: somente dados funcionais/institucionais; opt-out respeitado.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- Instituições da rede (UEG é a primeira; expansão = nova linha)
CREATE TABLE IF NOT EXISTS instituicao (
    id           SERIAL PRIMARY KEY,
    nome         TEXT NOT NULL,
    sigla        TEXT,
    ror          TEXT,
    openalex_id  TEXT UNIQUE,
    wikidata     TEXT,
    circulo      SMALLINT NOT NULL DEFAULT 1,
    config       JSONB NOT NULL DEFAULT '{}'::jsonb,
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fontes de dados por instituição (F1..F4 no MVP)
CREATE TABLE IF NOT EXISTS fonte (
    id             SERIAL PRIMARY KEY,
    instituicao_id INT NOT NULL REFERENCES instituicao(id),
    codigo         TEXT NOT NULL,          -- ex.: F1-BDTD-OAI
    tipo           TEXT NOT NULL,          -- oai_pmh | rest | ckan | scraping | api
    url_base       TEXT NOT NULL,
    licenca        TEXT,
    ultima_coleta  TIMESTAMPTZ,            -- base da coleta incremental
    ativa          BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (instituicao_id, codigo)
);

-- Documentos: teses, dissertações, TCCs, artigos, works, projetos, fichas
CREATE TABLE IF NOT EXISTS documento (
    id                   BIGSERIAL PRIMARY KEY,
    fonte_id             INT NOT NULL REFERENCES fonte(id),
    tipo                 TEXT NOT NULL,    -- tese | dissertacao | tcc | artigo | work | projeto_extensao | ficha_lab
    titulo               TEXT,
    resumo               TEXT,
    palavras_chave       TEXT[],
    ano                  SMALLINT,
    autores_raw          TEXT[],           -- como veio na fonte (auditoria)
    url                  TEXT,
    pdf_url              TEXT,
    identificador_externo TEXT,            -- handle / DOI / OpenAlex ID / id CKAN
    metadados            JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding            vector(1024),     -- bge-m3
    coletado_em          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fonte_id, identificador_externo)
);

-- Pessoas (consolidação light: ORCID exato | URL Lattes idêntica | nome+unidade)
CREATE TABLE IF NOT EXISTS pessoa (
    id               BIGSERIAL PRIMARY KEY,
    nome_canonico    TEXT NOT NULL,
    nome_normalizado TEXT,               -- sem acento, minúsculo, tokens ordenados
    orcid            TEXT,
    lattes_url       TEXT,
    email            TEXT,               -- somente e-mail funcional/institucional
    vinculo          TEXT,
    unidade          TEXT,
    confianca_fusao  TEXT NOT NULL DEFAULT 'exata',  -- exata | media (revisável)
    optout           BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS pessoa_orcid_uk      ON pessoa (orcid)      WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS pessoa_nome_norm_idx        ON pessoa (nome_normalizado);

-- Papéis pessoa↔documento
CREATE TABLE IF NOT EXISTS pessoa_documento (
    pessoa_id    BIGINT NOT NULL REFERENCES pessoa(id)    ON DELETE CASCADE,
    documento_id BIGINT NOT NULL REFERENCES documento(id) ON DELETE CASCADE,
    papel        TEXT NOT NULL,          -- autor | orientador | coordenador | responsavel
    PRIMARY KEY (pessoa_id, documento_id, papel)
);

-- Laboratórios (locações): prédio/sala/equipamentos/contato
CREATE TABLE IF NOT EXISTS laboratorio (
    id                BIGSERIAL PRIMARY KEY,
    instituicao_id    INT NOT NULL REFERENCES instituicao(id),
    unidade           TEXT,
    nome              TEXT NOT NULL,
    descricao         TEXT,
    predio            TEXT,
    sala              TEXT,
    responsavel_nome  TEXT,
    responsavel_email TEXT,
    equipamentos      TEXT[],
    url_fonte         TEXT,
    embedding         vector(1024),
    coletado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instituicao_id, nome, unidade)
);

-- Projetos/ações de extensão (CKAN, CC-BY)
CREATE TABLE IF NOT EXISTS projeto_extensao (
    id              BIGSERIAL PRIMARY KEY,
    instituicao_id  INT NOT NULL REFERENCES instituicao(id),
    titulo          TEXT NOT NULL,
    coordenacao     TEXT,
    colaboradores   TEXT,
    area_tematica   TEXT,
    campus          TEXT,
    local_execucao  TEXT,
    url_fonte       TEXT,
    embedding       vector(1024),
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instituicao_id, titulo, campus)
);

-- Log de buscas (auditoria e melhoria do sistema)
CREATE TABLE IF NOT EXISTS busca_log (
    id                BIGSERIAL PRIMARY KEY,
    entrada_usuario   TEXT,
    roteiro_anexado   BOOLEAN NOT NULL DEFAULT FALSE,
    tags_usadas       JSONB,
    provedores_usados JSONB,
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Canal de opt-out (LGPD)
CREATE TABLE IF NOT EXISTS optout (
    id            BIGSERIAL PRIMARY KEY,
    nome          TEXT NOT NULL,
    identificador TEXT,        -- e-mail / ORCID / Lattes informado pelo titular
    motivo        TEXT,
    criado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    atendido_em   TIMESTAMPTZ
);

-- ============================================================
-- Sementes: UEG + fontes do MVP (todas abertas/verificadas ago/2026)
-- ============================================================

INSERT INTO instituicao (nome, sigla, ror, openalex_id, wikidata, circulo)
VALUES ('Universidade Estadual de Goiás', 'UEG', 'https://ror.org/03ta25k06',
        'I3129565396', 'Q10387810', 1)
ON CONFLICT (openalex_id) DO NOTHING;

INSERT INTO fonte (instituicao_id, codigo, tipo, url_base, licenca)
SELECT i.id, f.codigo, f.tipo, f.url_base, f.licenca
FROM instituicao i
JOIN (VALUES
    ('F1-BDTD-OAI',  'oai_pmh',  'https://bdtd.ueg.br/server/oai/request',
     'Acesso aberto — Res. CsA 1087/2019'),
    ('F1-BDTD-REST', 'rest',     'https://bdtd.ueg.br/server/api',
     'Acesso aberto — Res. CsA 1087/2019'),
    ('F2-CKAN',      'ckan',     'https://dadosabertos.go.gov.br/api/3/action/',
     'CC-BY — creditar: Dados Abertos Goiás'),
    ('F3-LABS',      'scraping', 'https://www.ueg.br',
     'Páginas públicas institucionais'),
    ('F4-OPENALEX',  'api',      'https://api.openalex.org',
     'CC0')
) AS f(codigo, tipo, url_base, licenca) ON TRUE
WHERE i.openalex_id = 'I3129565396'
ON CONFLICT (instituicao_id, codigo) DO NOTHING;
