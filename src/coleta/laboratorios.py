"""Coletor F3 — Laboratórios das unidades da UEG (ueg.br, scraping educado).

Verificado ao vivo em 06/08/2026:
- cada unidade/câmpus tem um subsite https://www.ueg.br/{slug}/;
- a página-lista aparece como {slug}/conteudo/{id}_laboratorios ou
  {slug}/intermediario/{id}_laboratorios (nem sempre linkada na home);
- a ficha é {slug}/referencia/{id}, com corpo em div.blog-text e rótulos
  fixos em <strong>: Unidade / Curso(s) / Descrição / Objetivos /
  Localização (Campus-Unidade, Prédio, Sala) / Contato (Nome, E-mail) /
  Equipamentos / Imagens.

Regras (plano §6.3 e relatórios): 1 req/s, User-Agent identificado,
tolerância a URLs legadas (www.{unidade}.ueg.br), falha em uma unidade
não derruba as demais, todo HTML bruto vai para o data lake antes do parser.
A janela noturna (22h–06h) é a política para recargas completas agendadas;
a carga inicial e atualizações manuais pelo botão rodam a qualquer hora,
sempre a 1 req/s.
"""
from __future__ import annotations

import argparse
import re
import time
import unicodedata
from pathlib import Path
from typing import Callable

import requests
import yaml
from bs4 import BeautifulSoup
from psycopg.types.json import Jsonb

from src.banco.conexao import conectar, fonte_id_por_codigo, marcar_coleta
from src.coleta.lago import salvar_texto
from src.coleta.pessoas import upsert_pessoa, vincular_documento

FONTE = "F3-LABS"
BASE = "https://www.ueg.br"
PAUSA_S = 1.0            # 1 req/s — regra inviolável da fonte
MAX_NAV = 20             # páginas de menu varridas por subsite (teto)
TENTATIVAS = 3

CONFIG = Path(__file__).resolve().parents[2] / "config" / "instituicoes.yaml"

Progresso = Callable[[str, float | None], None]


def _log(progresso: Progresso | None, msg: str, frac: float | None = None) -> None:
    if progresso:
        progresso(msg, frac)
    else:
        print(msg, flush=True)


def _carregar_unidades() -> tuple[str, list[dict]]:
    """Lê slugs e User-Agent do config (regra: expansão vira configuração)."""
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    ueg = next(i for i in cfg if i["sigla"] == "UEG")
    f3 = next(f_ for f_ in ueg["fontes"] if f_["codigo"] == FONTE)
    return f3.get("user_agent") or "CriaLab-UEG-Harvester/1.0", f3.get("unidades") or []


def _get(sess: requests.Session, url: str, progresso=None) -> str | None:
    """GET com retries/backoff; tolera URL legada www.{unidade}.ueg.br."""
    espera = 5
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = sess.get(url, timeout=45)
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if tentativa == TENTATIVAS:
                # tolerância a subdomínio legado: www.{unidade}.ueg.br
                m = re.match(r"https://www\.ueg\.br/([a-z0-9_-]+)/(.*)", url)
                if m:
                    legado = f"http://www.{m.group(1)}.ueg.br/{m.group(2)}"
                    try:
                        r = sess.get(legado, timeout=45)
                        if r.status_code == 200:
                            return r.text
                    except requests.RequestException:
                        pass
                _log(progresso, f"  ⚠️ falha de rede em {url}")
                return None
            time.sleep(espera)
            espera *= 2
    return None


# ----------------------------------------------------------- parser

ROTULOS = ["Unidade:", "Curso(s):", "Descrição", "Objetivos", "Localização",
           "Campus/Unidade:", "Prédio:", "Sala:", "Contato", "Nome:",
           "E-mail", "Equipamentos", "Imagens"]


def _texto_ficha(html: str) -> tuple[str, list[str]] | None:
    """Devolve (título, linhas do corpo) ou None se não for ficha de lab."""
    soup = BeautifulSoup(html, "html.parser")
    corpo = soup.find("div", class_="blog-text")
    if corpo is None:
        return None
    h = soup.find(["h1", "h2"])
    titulo = h.get_text(" ", strip=True) if h else ""
    linhas = [l.strip() for l in corpo.get_text("\n", strip=True).splitlines()]
    linhas = [l for l in linhas if l and l != "Voltar a Laboratórios"]
    # contrato mínimo: tem que parecer ficha de laboratório
    if not any(l in ROTULOS for l in linhas):
        return None
    if not any(l in ("Prédio:", "Sala:", "Equipamentos", "Localização") for l in linhas):
        return None
    return titulo, linhas


def _valor_apos(linhas: list[str], rotulo: str) -> str | None:
    """Texto logo após um rótulo (pula rótulos vazios intermediários)."""
    try:
        i = linhas.index(rotulo)
    except ValueError:
        return None
    for l in linhas[i + 1:]:
        if l in ROTULOS:
            return None
        return l.lstrip(":").strip() or None
    return None


def _secao(linhas: list[str], inicio: str, fims: list[str]) -> list[str]:
    """Linhas entre um rótulo de início e o próximo rótulo de fim."""
    try:
        i = linhas.index(inicio)
    except ValueError:
        return []
    out = []
    for l in linhas[i + 1:]:
        if l in fims:
            break
        out.append(l)
    return out


def _parse_ficha(html: str) -> dict | None:
    """Extrai os campos da ficha pelos rótulos fixos."""
    achado = _texto_ficha(html)
    if achado is None:
        return None
    titulo, linhas = achado
    descricao = " ".join(_secao(linhas, "Descrição", ["Objetivos", "Localização",
                                                      "Contato", "Equipamentos",
                                                      "Imagens", "Unidade:", "Curso(s):"]))
    objetivos = " ".join(_secao(linhas, "Objetivos", ["Localização", "Contato",
                                                      "Equipamentos", "Imagens"]))
    equipamentos = [l.lstrip("-• ").strip() for l in _secao(linhas, "Equipamentos", ["Imagens"])]
    equipamentos = [e for e in equipamentos if e and not e.lower().startswith("imagens")]
    email = _valor_apos(linhas, "E-mail")
    if email is None:
        # padrão observado: 'E-mail' seguido de ': nome@ueg.br' na mesma linha seguinte
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", "\n".join(linhas))
        email = m.group(0) if m else None
    return {
        "nome": titulo,
        "unidade": _valor_apos(linhas, "Unidade:"),
        "cursos": _valor_apos(linhas, "Curso(s):"),
        "descricao": descricao or None,
        "objetivos": objetivos or None,
        "campus_unidade": _valor_apos(linhas, "Campus/Unidade:"),
        "predio": _valor_apos(linhas, "Prédio:"),
        "sala": _valor_apos(linhas, "Sala:"),
        "responsavel_nome": _valor_apos(linhas, "Nome:"),
        "responsavel_email": email,
        "equipamentos": equipamentos or None,
    }


# ----------------------------------------------------------- descoberta

NOME_LAB_RE = re.compile(r"^(Labor[aá]t[oó]rio|N[uú]cleo|Centro|Grupo)", re.I)

# títulos genéricos de seção que NÃO são laboratórios (falso positivo do formato B)
NOMES_GENERICOS = {
    "laboratórios", "laboratorio", "laboratorios", "centros", "centro",
    "núcleos", "nucleos", "núcleo", "nucleo", "grupo", "grupos",
}

# entrada com sigla: "LUPPA – Laboratório Universitário de …" (formato B2, ex.: CCSEH)
ITEM_SIGLA_RE = re.compile(
    r"^[\w&./()-]{2,20}\s*[–—-]\s*(Labor[aá]t[oó]rio|Centro|N[uú]cleo)\b", re.I)
# entrada sem sigla mas nomeada pelo tipo: "Centro de Idiomas"
TIPO_NOME_RE = re.compile(r"^(Labor[aá]t[oó]rio|Centro|N[uú]cleo)\s+\S", re.I)


def _nome_generico(texto: str) -> bool:
    t = texto.lower().rstrip(".:")
    return t in NOMES_GENERICOS or t.startswith("núcleos docentes")


def _parse_lista_textual(html: str) -> list[dict]:
    """Formato B: página-lista em texto corrido (ex.: ESEFFEGO).

    Nome do laboratório em h2–h5 (ou parágrafo todo em <strong>) seguido de
    parágrafos de descrição, geralmente começando por "Coordenado(a) por…".
    Sem prédio/sala/equipamentos — o que a fonte não tem, não inventamos.
    A frase de coordenação vai crua para metadados (não vira pessoa: texto
    livre não é identificador confiável).
    """
    soup = BeautifulSoup(html, "html.parser")
    corpo = soup.find("div", class_="blog-text")
    if corpo is None:
        return []
    entradas: list[dict] = []
    atual: dict | None = None
    for el in corpo.find_all(["h2", "h3", "h4", "h5", "p", "li"]):
        # NFC: o CMS mistura acentos compostos/decompostos entre blocos
        texto = unicodedata.normalize("NFC", " ".join(el.get_text(" ", strip=True).split()))
        if not texto or texto == "Voltar a Laboratórios":
            continue
        strong = el.find("strong")
        eh_nome = (
            not _nome_generico(texto)
            and len(texto.split()) >= 2
            and (
                (NOME_LAB_RE.match(texto)
                 and (el.name.startswith("h")
                      or (strong is not None and strong.get_text(" ", strip=True) == texto)))
                or ITEM_SIGLA_RE.match(texto)
                or TIPO_NOME_RE.match(texto)
            )
        )
        if eh_nome:
            if atual:
                entradas.append(atual)
            atual = {"nome": texto, "partes": []}
        elif atual is not None:
            atual["partes"].append(texto)
    if atual:
        entradas.append(atual)

    out = []
    for e in entradas:
        desc = " ".join(e["partes"])
        m = re.search(r"(Coordenad[oa][^.]*\.)", desc)
        out.append({
            "nome": e["nome"],
            "descricao": desc or None,
            "coordenacao_raw": m.group(1) if m else None,
        })
    return out


def _links_labs(soup: BeautifulSoup) -> list[str]:
    """Links de páginas-lista de laboratórios/estrutura em uma página."""
    urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        texto = a.get_text(" ", strip=True).lower()
        if re.search(r"laboratorio", href) or re.search(r"laboratório|laboratorios|estrutura", texto) \
                or re.search(r"estrutura", href):
            if re.search(r"/(conteudo|intermediario)/\d+", a["href"]):
                if a["href"].startswith("/"):
                    a["href"] = BASE + a["href"]
                urls.add(a["href"])
    return sorted(urls)


def _descobrir_listas(sess: requests.Session, slug: str, progresso) -> tuple[list[str], int]:
    """Acha páginas-lista de laboratórios do subsite (home → menus, se preciso)."""
    home = _get(sess, f"{BASE}/{slug}/", progresso)
    reqs = 1
    if home is None:
        return [], reqs
    salvar_texto(FONTE, f"{slug}/home.html", home)
    soup = BeautifulSoup(home, "html.parser")
    listas = _links_labs(soup)
    if listas:
        return listas, reqs

    # fallback: varrer páginas de menu do subsite procurando o link
    nav = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.match(rf"https://www\.ueg\.br/{slug}/(conteudo|intermediario)/\d+", href):
            nav.append(href)
    for url in sorted(set(nav))[:MAX_NAV]:
        time.sleep(PAUSA_S)
        html = _get(sess, url, progresso)
        reqs += 1
        if html is None:
            continue
        listas = _links_labs(BeautifulSoup(html, "html.parser"))
        if listas:
            return listas, reqs
    return [], reqs


# links administrativos genéricos que aparecem em toda página (não são fichas)
ADMIN_LINKS = {
    "acesso à informação", "lista telefônica", "acessibilidade",
    "regimento geral", "fale conosco", "mapa do site", "ouvidoria",
}


def _fichas_da_lista(html: str, slug: str) -> dict[str, str]:
    """Links referencia/{id} de uma página-lista → {url: nome}."""
    soup = BeautifulSoup(html, "html.parser")
    fichas: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(rf"(?:https?://(?:www\.)?(?:{slug}\.)?ueg\.br)?/{slug}/referencia/(\d+)", href)
        if not m:
            continue
        texto = a.get_text(" ", strip=True)
        if texto.lower() in ADMIN_LINKS:
            continue
        url = f"{BASE}/{slug}/referencia/{m.group(1)}"
        fichas[url] = texto
    return fichas


def _links_conteudo_lab(html: str, slug: str, url_lista: str) -> dict[str, str]:
    """Formato C: corpo da lista com links p/ páginas de cada lab (ex.: Laranjeiras)."""
    soup = BeautifulSoup(html, "html.parser")
    corpo = soup.find("div", class_="blog-text")
    if corpo is None:
        return {}
    alvo = re.compile(rf"(?:https?://(?:www\.)?ueg\.br)?/{slug}/(conteudo|intermediario)/(\d+)_([\w-]+)")
    out: dict[str, str] = {}
    for a in corpo.find_all("a", href=True):
        m = alvo.search(a["href"])
        if not m:
            continue
        url = f"{BASE}/{slug}/{m.group(1)}/{m.group(2)}_{m.group(3)}"
        if url == url_lista:
            continue
        out[url] = a.get_text(" ", strip=True)
    return out


def _parse_pagina_generica(html: str, nome_link: str) -> dict | None:
    """Página de laboratório fora do padrão de rótulos: tenta o parser de
    fichas primeiro; senão, guarda título + texto do corpo como descrição."""
    ficha = _parse_ficha(html)
    if ficha is not None:
        return ficha
    soup = BeautifulSoup(html, "html.parser")
    corpo = soup.find("div", class_="blog-text")
    if corpo is None:
        return None
    txt = unicodedata.normalize("NFC", " ".join(corpo.get_text(" ", strip=True).split()))
    if len(txt) < 40 or "não está disponível" in txt:
        return None
    h = soup.find(["h1", "h2"])
    nome = (h.get_text(" ", strip=True) if h else "") or nome_link
    return {
        "nome": nome, "unidade": None, "cursos": None,
        "descricao": txt[:2000], "objetivos": None, "campus_unidade": None,
        "predio": None, "sala": None, "responsavel_nome": None,
        "responsavel_email": None, "equipamentos": None,
    }


# ----------------------------------------------------------- banco

def _instituicao_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM instituicao WHERE sigla = 'UEG'")
        return cur.fetchone()[0]


def _upsert_laboratorio(cur, inst_id: int, slug: str, ficha: dict, url: str) -> None:
    cur.execute(
        """
        INSERT INTO laboratorio (instituicao_id, unidade, nome, descricao, predio,
                                 sala, responsavel_nome, responsavel_email,
                                 equipamentos, url_fonte, metadados)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (instituicao_id, nome, unidade) DO UPDATE SET
            descricao = EXCLUDED.descricao,
            predio = EXCLUDED.predio,
            sala = EXCLUDED.sala,
            responsavel_nome = EXCLUDED.responsavel_nome,
            responsavel_email = EXCLUDED.responsavel_email,
            equipamentos = EXCLUDED.equipamentos,
            url_fonte = EXCLUDED.url_fonte,
            metadados = EXCLUDED.metadados,
            coletado_em = now()
        """,
        (
            inst_id, ficha["unidade"] or slug, ficha["nome"], ficha["descricao"],
            ficha["predio"], ficha["sala"], ficha["responsavel_nome"],
            ficha["responsavel_email"], ficha["equipamentos"], url,
            Jsonb({"cursos": ficha["cursos"], "objetivos": ficha["objetivos"],
                   "campus_unidade": ficha["campus_unidade"],
                   "coordenacao_raw": ficha.get("coordenacao_raw")}),
        ),
    )


def _upsert_documento(cur, fonte_id: int, ficha: dict, url: str,
                      identificador: str | None = None) -> int:
    resumo = ". ".join(p for p in [ficha["descricao"], ficha["objetivos"]] if p)
    cur.execute(
        """
        INSERT INTO documento (fonte_id, tipo, titulo, resumo, palavras_chave,
                               autores_raw, url, identificador_externo, metadados)
        VALUES (%s, 'ficha_lab', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fonte_id, identificador_externo) DO UPDATE SET
            titulo = EXCLUDED.titulo, resumo = EXCLUDED.resumo,
            palavras_chave = EXCLUDED.palavras_chave,
            autores_raw = EXCLUDED.autores_raw, metadados = EXCLUDED.metadados,
            coletado_em = now()
        RETURNING id
        """,
        (
            fonte_id, ficha["nome"], resumo or None, ficha["equipamentos"],
            [ficha["responsavel_nome"]] if ficha["responsavel_nome"] else None,
            url, identificador or url,
            Jsonb({"unidade": ficha["unidade"], "predio": ficha["predio"],
                   "sala": ficha["sala"], "cursos": ficha["cursos"],
                   "campus_unidade": ficha["campus_unidade"]}),
        ),
    )
    return cur.fetchone()[0]


# ----------------------------------------------------------- fluxo

def executar(progresso: Progresso | None = None, apenas: list[str] | None = None) -> dict:
    """Coleta de laboratórios em todos os subsites (idempotente, 1 req/s)."""
    ua, unidades = _carregar_unidades()
    if apenas:
        unidades = [u for u in unidades if u["slug"] in apenas]
    stats = {"unidades": 0, "unidades_sem_pagina": 0, "fichas": 0,
             "responsaveis": 0, "erros_unidade": 0}

    conn = conectar()
    sess = requests.Session()
    sess.headers.update({"User-Agent": ua})

    try:
        fonte_id = fonte_id_por_codigo(conn, FONTE)
        inst_id = _instituicao_id(conn)
        total = len(unidades)
        _log(progresso, f"{total} subsites a varrer (1 req/s, janela educada)…", 0.0)

        for pos, un in enumerate(unidades):
            slug = un["slug"]
            nome_un = un.get("nome", slug)
            try:
                # subsites de PPG podem declarar páginas de lab direto no config
                paginas_cfg = un.get("paginas_lab") or []
                if paginas_cfg:
                    listas = []
                    links_diretos = {u: u.rsplit("_", 1)[-1].replace("-", " ") for u in paginas_cfg}
                else:
                    listas, _ = _descobrir_listas(sess, slug, progresso)
                    links_diretos = {}
                if not listas and not links_diretos:
                    stats["unidades_sem_pagina"] += 1
                    _log(progresso, f"[{pos + 1}/{total}] {nome_un}: sem página de laboratórios localizada.")
                    continue

                fichas: dict[str, str] = {}
                entradas_texto: list[tuple[dict, str]] = []  # (entrada, url_lista)
                links_conteudo: dict[str, str] = links_diretos  # formato C
                for url_lista in listas:
                    time.sleep(PAUSA_S)
                    html = _get(sess, url_lista, progresso)
                    if html is None:
                        continue
                    salvar_texto(FONTE, f"{slug}/lista_{url_lista.rsplit('/', 1)[-1]}.html", html)
                    fichas.update(_fichas_da_lista(html, slug))
                    if not fichas:
                        # formato B: lista textual sem fichas (ex.: ESEFFEGO)
                        entradas = _parse_lista_textual(html)
                        if entradas:
                            entradas_texto.extend((e, url_lista) for e in entradas)
                        else:
                            # formato C: página por laboratório (ex.: Laranjeiras)
                            links_conteudo.update(_links_conteudo_lab(html, slug, url_lista))

                novas = 0
                for url, _texto_link in fichas.items():
                    time.sleep(PAUSA_S)
                    html = _get(sess, url, progresso)
                    if html is None:
                        continue
                    ficha = _parse_ficha(html)
                    if ficha is None:
                        continue  # link administrativo (reserva, formulário etc.)
                    fid = url.rsplit("/", 1)[-1]
                    salvar_texto(FONTE, f"{slug}/ficha_{fid}.html", html)
                    with conn.cursor() as cur:
                        _upsert_laboratorio(cur, inst_id, slug, ficha, url)
                        doc_id = _upsert_documento(cur, fonte_id, ficha, url)
                        pid = upsert_pessoa(
                            cur, ficha["responsavel_nome"],
                            email=ficha["responsavel_email"],
                            unidade=ficha["unidade"] or nome_un,
                            vinculo="responsável de laboratório",
                        )
                        if pid is not None:
                            vincular_documento(cur, pid, doc_id, "responsavel")
                            stats["responsaveis"] += 1
                    conn.commit()
                    novas += 1

                for entrada, url_lista in entradas_texto:
                    ficha = {
                        "nome": entrada["nome"], "unidade": nome_un,
                        "cursos": None, "descricao": entrada["descricao"],
                        "objetivos": None, "campus_unidade": None,
                        "predio": None, "sala": None,
                        "responsavel_nome": None, "responsavel_email": None,
                        "equipamentos": None,
                        "coordenacao_raw": entrada["coordenacao_raw"],
                    }
                    with conn.cursor() as cur:
                        _upsert_laboratorio(cur, inst_id, slug, ficha, url_lista)
                        ident = f"{url_lista}#{entrada['nome'][:60]}"
                        _upsert_documento(cur, fonte_id, ficha, url_lista, identificador=ident)
                    conn.commit()
                    novas += 1

                for url, nome_link in links_conteudo.items():
                    time.sleep(PAUSA_S)
                    html = _get(sess, url, progresso)
                    if html is None:
                        continue
                    ficha = _parse_pagina_generica(html, nome_link)
                    if ficha is None:
                        continue
                    fid = url.rsplit("/", 1)[-1]
                    salvar_texto(FONTE, f"{slug}/pagina_{fid}.html", html)
                    ficha["unidade"] = ficha["unidade"] or nome_un
                    with conn.cursor() as cur:
                        _upsert_laboratorio(cur, inst_id, slug, ficha, url)
                        doc_id = _upsert_documento(cur, fonte_id, ficha, url)
                        pid = upsert_pessoa(
                            cur, ficha["responsavel_nome"],
                            email=ficha["responsavel_email"],
                            unidade=ficha["unidade"],
                            vinculo="responsável de laboratório",
                        )
                        if pid is not None:
                            vincular_documento(cur, pid, doc_id, "responsavel")
                            stats["responsaveis"] += 1
                    conn.commit()
                    novas += 1

                stats["fichas"] += novas
                stats["unidades"] += 1
                _log(progresso, f"[{pos + 1}/{total}] {nome_un}: {novas} fichas de laboratório.",
                     (pos + 1) / total)
            except Exception as exc:
                conn.rollback()
                stats["erros_unidade"] += 1
                _log(progresso, f"⚠️ {nome_un}: falha isolada ({exc.__class__.__name__}) — seguindo para a próxima.")

        marcar_coleta(conn, FONTE)
        conn.commit()
    finally:
        conn.close()
        sess.close()

    _log(progresso, "Coleta de laboratórios concluída.", 1.0)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor de laboratórios ueg.br")
    parser.add_argument("--slug", action="append", default=None,
                        help="restringe a coleta a um ou mais slugs (teste)")
    args = parser.parse_args()
    executar(apenas=args.slug)


if __name__ == "__main__":
    main()
