#!/usr/bin/env python3
"""
StartupDrops — Coletor de notícias
-----------------------------------
Lê os RSS das fontes, deduplica contra o arquivo existente, resume o que é novo
(IA da Anthropic com fallback para regras) e ACUMULA em data/news.json.

Uso:
    pip install feedparser requests anthropic
    python collector.py                 # roda a coleta
    python collector.py --no-ai         # força só a lógica de regras
    python collector.py --max-age 45    # mantém no arquivo notícias dos últimos 45 dias

Variáveis de ambiente:
    ANTHROPIC_API_KEY   -> se presente, ativa o resumo por IA (senão cai na regra)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import requests

# ── FONTES ────────────────────────────────────────────────────────────────────
# Mesmas fontes do portal. Ajuste as URLs conforme necessário.
SOURCES = [
    # Brasil
    {"name": "Startupi",              "region": "Brasil",         "country": "BR", "feed": "https://startupi.com.br/feed/"},
    {"name": "Startups.com.br",       "region": "Brasil",         "country": "BR", "feed": "https://startups.com.br/feed/"},
    {"name": "NeoFeed",               "region": "Brasil",         "country": "BR", "feed": "https://neofeed.com.br/feed/"},
    {"name": "Exame",                 "region": "Brasil",         "country": "BR", "feed": "https://exame.com/feed/"},
    {"name": "Brazil Journal",        "region": "Brasil",         "country": "BR", "feed": "https://braziljournal.com/feed/"},
    {"name": "Pipeline Valor",        "region": "Brasil",         "country": "BR", "feed": "https://pipelinevalor.globo.com/rss/"},
    {"name": "IT Forum",              "region": "Brasil",         "country": "BR", "feed": "https://itforum.com.br/feed/"},
    {"name": "Olhar Digital",         "region": "Brasil",         "country": "BR", "feed": "https://olhardigital.com.br/feed/"},
    {"name": "Tecnoblog",             "region": "Brasil",         "country": "BR", "feed": "https://tecnoblog.net/feed/"},
    {"name": "Inovação Tecnológica",  "region": "Brasil",         "country": "BR", "feed": "https://www.inovacaotecnologica.com.br/boletim/rss.xml"},
    {"name": "InfoMoney",             "region": "Brasil",         "country": "BR", "feed": "https://www.infomoney.com.br/feed/"},
    {"name": "Baguete",               "region": "Brasil",         "country": "BR", "feed": "https://www.baguete.com.br/rss.xml"},
    {"name": "Época Negócios",        "region": "Brasil",         "country": "BR", "feed": "https://epocanegocios.globo.com/rss/epoca-negocios/"},
    # Internacional
    {"name": "TechCrunch Startups",   "region": "Internacional",  "country": "US", "feed": "https://techcrunch.com/category/startups/feed/"},
    {"name": "Crunchbase News",       "region": "Internacional",  "country": "US", "feed": "https://news.crunchbase.com/feed/"},
    {"name": "VentureBeat",           "region": "Internacional",  "country": "US", "feed": "https://venturebeat.com/feed/"},
    {"name": "Sifted",                "region": "Internacional",  "country": "EU", "feed": "https://sifted.eu/feed"},
    {"name": "Tech.eu",                "region": "Internacional",  "country": "EU", "feed": "https://tech.eu/feed/"},
    {"name": "EU-Startups",            "region": "Internacional",  "country": "EU", "feed": "https://www.eu-startups.com/feed/"},
    {"name": "Finsider",               "region": "Internacional",  "country": "EU", "feed": "https://finsider.eu/feed/"},
    {"name": "Business Insider Tech",  "region": "Internacional",  "country": "US", "feed": "https://www.businessinsider.com/sai/rss"},
    {"name": "Rest of World",         "region": "Internacional",  "country": "US", "feed": "https://restofworld.org/feed/latest/"},
    {"name": "The Verge",             "region": "Internacional",  "country": "US", "feed": "https://www.theverge.com/rss/index.xml"},
    {"name": "Ars Technica",          "region": "Internacional",  "country": "US", "feed": "https://feeds.arstechnica.com/arstechnica/index"},
    {"name": "Wired",                 "region": "Internacional",  "country": "US", "feed": "https://www.wired.com/feed/rss"},

    # Brasil — Economia e Mercado
    {"name": "Exame Economia",        "region": "Brasil",         "country": "BR", "feed": "https://exame.com/economia/feed/"},
    {"name": "Exame Invest",          "region": "Brasil",         "country": "BR", "feed": "https://exame.com/invest/feed/"},
    {"name": "G1 Economia",           "region": "Brasil",         "country": "BR", "feed": "https://g1.globo.com/dynamo/economia/rss2.xml"},
    {"name": "Valor Econômico",       "region": "Brasil",         "country": "BR", "feed": "https://valor.globo.com/rss/ultimas-noticias/"},
    {"name": "CNN Brasil Business",   "region": "Brasil",         "country": "BR", "feed": "https://www.cnnbrasil.com.br/economia/feed/"},
    {"name": "Infomoney Economia",    "region": "Brasil",         "country": "BR", "feed": "https://www.infomoney.com.br/economia/feed/"},
    {"name": "Broadcast Político",    "region": "Brasil",         "country": "BR", "feed": "https://www.estadao.com.br/economia/rss/"},
    # Internacional — Economia e Mercado
    {"name": "Reuters Business",      "region": "Internacional",  "country": "US", "feed": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "Bloomberg Markets",     "region": "Internacional",  "country": "US", "feed": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "FT Companies",          "region": "Internacional",  "country": "US", "feed": "https://www.ft.com/companies?format=rss"},
    # 🇨🇳 China
    {"name": "Caixin Global",         "region": "Internacional",  "country": "CN", "feed": "https://www.caixinglobal.com/rss/all.xml"},
    {"name": "SCMP Tech",             "region": "Internacional",  "country": "CN", "feed": "https://www.scmp.com/rss/36/feed"},
    {"name": "SCMP Business",          "region": "Internacional",  "country": "CN", "feed": "https://www.scmp.com/rss/92/feed"},
    {"name": "Reuters China",         "region": "Internacional",  "country": "CN", "feed": "https://feeds.reuters.com/reuters/CNTopNews"},
    {"name": "Nikkei Asia",           "region": "Internacional",  "country": "CN", "feed": "https://asia.nikkei.com/rss/feed/nar"},
    {"name": "TechNode",               "region": "Internacional",  "country": "CN", "feed": "https://technode.com/feed/"},
    {"name": "KrASIA",                 "region": "Internacional",  "country": "CN", "feed": "https://kr.asia/feed/"},
    # 🇮🇳 Índia
    {"name": "Inc42",                 "region": "Internacional",  "country": "IN", "feed": "https://inc42.com/feed/"},
    {"name": "YourStory",             "region": "Internacional",  "country": "IN", "feed": "https://yourstory.com/feed"},
    {"name": "ETtech",                "region": "Internacional",  "country": "IN", "feed": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"},
    {"name": "MediaNama",             "region": "Internacional",  "country": "IN", "feed": "https://www.medianama.com/feed/"},
    {"name": "YourStory Startups",     "region": "Internacional",  "country": "IN", "feed": "https://yourstory.com/category/startups/feed"},
    {"name": "Inc42 Startups",         "region": "Internacional",  "country": "IN", "feed": "https://inc42.com/startups/feed/"},
    {"name": "Indian Web2",            "region": "Internacional",  "country": "IN", "feed": "https://indianweb2.com/feed/"},

    # Alguns feeds mudam de URL ou exigem checagem. Rode o collector e veja se
    # aparecem em "falhas"; se falharem, ajuste a URL ou remova.
    # {"name": "MIT Tech Review BR",  "region": "Brasil",         "country": "BR", "feed": "https://mittechreview.com.br/feed/"},
    # {"name": "PEGN",                "region": "Brasil",         "country": "BR", "feed": "https://revistapegn.globo.com/rss/ultimas/feed.xml"},
    # {"name": "Axios",               "region": "Internacional",  "country": "US", "feed": "https://api.axios.com/feed/"},
]

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "news.json")
USER_AGENT = "StartupDropsBot/1.0 (+https://startupdrops)"
REQUEST_TIMEOUT = 20

# Portão de qualidade: resumo precisa ter pelo menos este tamanho pra virar matéria.
# Fontes que só entregam trecho curto (HBR, muitos paywalls) são descartadas
# em vez de virarem card raso.
MIN_SUMMARY_CHARS = 180

# Palavras que caracterizam o ecossistema. Pelo menos UMA precisa estar
# no título ou resumo para a notícia entrar no portal.
RELEVANCE_REQUIRED = [
    # startups e ecossistema
    "startup", "scale-up", "scaleup", "empreend", "founder", "venture",
    "investimento", "funding", "captação", "rodada", "aporte", "seed",
    "série a", "série b", "série c", "series a", "series b", "valuation",
    "m&a", "aquisição", "aquisiç", "acquire", "acquisition", "ipo", "unicórnio",
    "unicorn", "acelerador", "incubador",
    # tecnologia
    "tecnologia", "technology", "tech", "software", "saas", "plataforma",
    "inteligência artificial", "artificial intelligence", "ia ", " ai ",
    "machine learning", "llm", "chatgpt", "openai", "gemini", "deepmind",
    "robô", "robot", "automação", "automation", "chip", "semicondutor",
    "semiconductor", "data center", "cloud", "fintech", "edtech", "healthtech",
    "agtech", "proptech", "insurtech", "legaltech", "deeptech",
    # empresas relevantes do ecossistema
    "nubank", "ifood", "totvs", "stone", "rappi", "mercado livre", "magalu",
    "amazon", "google", "apple", "microsoft", "meta", "nvidia", "bytedance",
    "alibaba", "tencent", "baidu", "openai", "anthropic", "spacex",
]

# Termos que bloqueiam a notícia mesmo que passe no portão de relevância
BLOCKLIST = [
    "mega-sena", "loteria", "lotto", "sorteio", "futebol", "campeonato",
    "copa do mundo", "olimpíada", "olimpiad", "eleição", "candidato",
    "partido político", "deputado", "senador", "presidente da república",
    "horóscopo", "receita", "culinária", "novela", "série da netflix",
    "bbb ", "big brother", "reality show", "celebridade", "famoso",
    "bets ", "apostas esportivas", "cassino", "jogo do bicho",
    "saneamento básico", "abastecimento de água", "esgoto",
    "previsão do tempo", "temperatura", "chuva",
]


def normalize_txt(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s[:120]

# Termos que sobem o score de uma notícia (relevância p/ ecossistema de startups)
KEYWORDS_STRONG = [
    "rodada", "aporte", "investimento", "série a", "série b", "seed", "captação",
    "valuation", "unicórnio", "unicorn", "funding", "raises", "raised", "million",
    "milhões", "bilhões", "aquisição", "aquisiç", "acquire", "acquisition", "m&a",
    "fusão", "ipo", "venture", "fundo", "startup",
]
KEYWORDS_SOFT = ["fintech", "saas", "ia", "inteligência artificial", "ai ", "scale-up", "edtech", "healthtech",
                 "selic", "juros", "banco central", "copom", "inflação", "câmbio", "dólar", "pib", "economia"]


# ── UTIL ──────────────────────────────────────────────────────────────────────
def now_utc():
    return datetime.now(timezone.utc)


def parse_date(entry):
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return now_utc()


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = strip_photo_credit(text)
    return text.strip()


def strip_photo_credit(text):
    """Remove legenda/crédito de foto no início do texto."""
    patterns = [
        # "Legenda | Crédito: Fonte / site.com Texto..."
        r"^[^.!?]{0,120}\|\s*(?:Crédito|Credito|Foto|Fonte|Imagem|Reprodução)\s*:\s*[^.!?]{2,120}?(?:\.com|\.br|\.org|\.net)\s+(?=[A-ZÀ-Ú])",
        r"^(?:Crédito|Credito|Foto|Fonte|Imagem|Reprodução)\s*:\s*[^.!?]{2,120}?(?:\.com|\.br|\.org|\.net)\s+(?=[A-ZÀ-Ú])",
        r"^[^.!?]{0,120}\|\s*(?:Crédito|Credito|Foto|Fonte|Imagem|Reprodução)\s*:\s*[^.!?]{2,80}\s+(?=[A-ZÀ-Ú])",
        # "Descrição do local Fotógrafo/Reuters Texto real..." — padrão sem pipe
        r"^[^.!?]{0,180}\s+\w[\w\s]{2,30}/(?:Reuters|AFP|AP|Getty|Bloomberg|Shutterstock|EPA|EFE|Lusa|Folhapress|Agência Brasil)\s+(?=[A-ZÀ-Ú])",
        # "Descrição Fotógrafo/Agência\n" seguido do texto
        r"^[^.!?]{0,180}(?:Reuters|AFP|AP|Getty|Bloomberg|Shutterstock|EPA|EFE|Lusa|Folhapress|Agência Brasil)[^.!?]{0,60}\s+(?=[A-ZÀ-Ú][a-zà-ú])",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.I)
    return text.strip()


def first_image(entry):
    # media:content / media:thumbnail
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media and isinstance(media, list) and media[0].get("url"):
            return media[0]["url"]
    # enclosures
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    # <img> dentro do conteúdo/summary
    for field in ("summary", "content"):
        raw = entry.get(field)
        if isinstance(raw, list):
            raw = raw[0].get("value", "") if raw else ""
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw or "")
        if m:
            return m.group(1)
    return ""


def score_article(title, summary):
    text = f"{title} {summary}".lower()
    score = 30
    for kw in KEYWORDS_STRONG:
        if kw in text:
            score += 8
    for kw in KEYWORDS_SOFT:
        if kw in text:
            score += 3
    return min(score, 100)


def og_image(url):
    """Busca og:image / twitter:image na própria página quando o RSS não traz imagem."""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        html = r.text[:200000]
        for pattern in (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ):
            m = re.search(pattern, html, re.I)
            if m:
                img = m.group(1).strip()
                if img.startswith("http"):
                    return img
    except Exception:
        pass
    return ""


def resolve_image(entry, url):
    img = first_image(entry)
    if img and not re.search(r"youtube\.com/embed|youtu\.be|\.svg(\?|$)", img, re.I):
        return img
    return og_image(url)


def make_id(source, url):
    return f"{source}-{url}"


def canonical_key(url):
    """Chave p/ deduplicar: domínio + caminho, sem querystring/fragment."""
    u = re.sub(r"[#?].*$", "", url or "")
    u = re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower()
    return hashlib.md5(u.encode()).hexdigest()


# ── RESUMO ────────────────────────────────────────────────────────────────────
def summary_by_rule(title, raw_summary):
    """Fallback: limpa o texto e corta em frases completas (sem inventar dado)."""
    text = strip_html(raw_summary) or title
    text = re.sub(r"\[[…\.]+\]\s*$", "", text).strip()
    # corta em ~2 frases completas, máx ~280 chars
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out, total = [], 0
    for s in sentences:
        if total + len(s) > 280 and out:
            break
        out.append(s)
        total += len(s)
    result = " ".join(out).strip()
    return result if result else title


_anthropic_client = None


def get_anthropic():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=key)
        return _anthropic_client
    except Exception as e:
        print(f"  [ia] indisponível ({e}); usando regra", file=sys.stderr)
        return None


def summary_by_ai(title, raw_summary, region, country="US"):
    client = get_anthropic()
    if not client:
        return None, None
    source_text = strip_html(raw_summary)[:1500]
    
    is_chinese = country == "CN"
    lang_note = "O conteúdo pode estar em chinês — traduza e interprete para português do Brasil." if is_chinese else ""
    
    prompt = (
        f"Você é editor de um portal brasileiro de inteligência para founders sobre startups e tecnologia global.\n"
        f"{lang_note}\n"
        f"Com base no título e texto abaixo, gere em português do Brasil:\n\n"
        f"1. TÍTULO: título jornalístico específico e direto (máx 90 chars). Evite títulos vagos como 'X avança em Y'.\n"
        f"2. O QUE ACONTECEU: 2 frases objetivas explicando o fato. Inclua números e nomes quando disponíveis.\n"
        f"3. POR QUE IMPORTA: 1 frase explicando a relevância para founders, investidores ou quem trabalha com startups.\n\n"
        f"NÃO invente dados. NÃO inclua legendas de foto, créditos de imagem ou descrições visuais.\n"
        f"Responda APENAS neste formato exato:\n"
        f"TÍTULO: [título]\n"
        f"O QUE ACONTECEU: [2 frases]\n"
        f"POR QUE IMPORTA: [1 frase]\n\n"
        f"Título original: {title}\n"
        f"Texto: {source_text}"
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        out = " ".join(parts).strip()
        new_title, what_happened, why_matters = None, [], None
        for line in out.split("\n"):
            if line.startswith("TÍTULO:"):
                new_title = line.replace("TÍTULO:", "").strip()
            elif line.startswith("O QUE ACONTECEU:"):
                what_happened.append(line.replace("O QUE ACONTECEU:", "").strip())
            elif line.startswith("POR QUE IMPORTA:"):
                why_matters = line.replace("POR QUE IMPORTA:", "").strip()
        summary_text = " ".join(what_happened).strip()
        if why_matters:
            summary_text = summary_text + " ||WHY|| " + why_matters
        if summary_text and len(summary_text) >= 20:
            return summary_text, new_title
        return None, None
    except Exception as e:
        print(f"  [ia] falha na sumarização ({e}); usando regra", file=sys.stderr)
        return None, None
        return None


def build_summary(title, raw_summary, region, use_ai, country="US"):
    if use_ai:
        ai_summary, ai_title = summary_by_ai(title, raw_summary, region, country)
        if ai_summary:
            return ai_summary, "ia", ai_title
    return summary_by_rule(title, raw_summary), "regra", None


# ── COLETA ────────────────────────────────────────────────────────────────────
PROXY_URL = "https://api.allorigins.win/raw?url={url}"

def fetch_feed(source):
    headers = {"User-Agent": USER_AGENT}
    url = source["feed"]
    # Tenta direto primeiro
    for attempt_url in [url, PROXY_URL.format(url=requests.utils.quote(url, safe=''))]:
        try:
            r = requests.get(attempt_url, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            if parsed.entries:
                return parsed, None
        except Exception:
            continue
    return None, f"falhou direto e via proxy"


def collect(use_ai, max_age_days):
    existing = load_existing()
    by_key = {a.get("_key") or canonical_key(a["url"]): a for a in existing.get("articles", [])}

    articles = list(by_key.values())
    failures = []
    seen_now = set()
    new_count = 0
    skipped_thin = 0

    for source in SOURCES:
        print(f"→ {source['name']}", file=sys.stderr)
        parsed, err = fetch_feed(source)
        if err or parsed is None:
            failures.append({"source": source["name"], "url": source["feed"], "reason": err or "sem retorno"})
            continue

        for entry in parsed.entries[:25]:
            url = entry.get("link", "").strip()
            title = strip_html(entry.get("title", "")).strip()
            if not url or not title:
                continue
            key = canonical_key(url)
            if key in seen_now:
                continue
            seen_now.add(key)

            if key in by_key:
                # Reprocessa se: tem título genérico OU foi feito sem IA e IA está disponível agora
                existing_art = by_key[key]
                has_generic_title = bool(re.search(
                    r'\bavança em\b|\banuncia\b.*\bplano\b|\bapresenta\b|\blança\b|\batinge\b|\bregistra\b|\balcança\b',
                    existing_art.get("title",""), re.I
                ))
                was_rule_based = existing_art.get("summaryMethod","regra") == "regra"
                if not (use_ai and (has_generic_title or was_rule_based)):
                    continue
                # Cai através pra reprocessar

            raw_summary = entry.get("summary", "") or ""
            published = parse_date(entry)
            country = source.get("country", "US")
            summary, method, ai_title = build_summary(title, raw_summary, source["region"], use_ai, country)

            # Extrai "Por que importa" do summary se vier do formato AI
            why_matters = ""
            clean_summary = summary.strip()
            if "||WHY||" in clean_summary:
                parts_split = clean_summary.split("||WHY||", 1)
                clean_summary = parts_split[0].strip()
                why_matters = parts_split[1].strip()

            # Portão de qualidade
            enough_length = len(clean_summary) >= MIN_SUMMARY_CHARS
            enough_sentences = len(re.findall(r"[.!?]", clean_summary)) >= 1
            distinct_from_title = normalize_txt(clean_summary) != normalize_txt(title)

            # Portão de relevância: precisa ter pelo menos 1 palavra do ecossistema
            haystack = (title + " " + clean_summary).lower()
            is_relevant = any(kw in haystack for kw in RELEVANCE_REQUIRED)

            # Portão de bloqueio: termos que nunca devem entrar
            is_blocked = any(kw in haystack for kw in BLOCKLIST)

            if not (enough_length and enough_sentences and distinct_from_title and is_relevant) or is_blocked:
                skipped_thin += 1
                continue

            score = score_article(title, clean_summary)
            final_title = ai_title if ai_title else title

            article = {
                "id": make_id(source["name"], url),
                "_key": key,
                "title": final_title,
                "originalTitle": title,
                "summary": clean_summary,
                "whyMatters": why_matters,
                "summaryMethod": method,
                "url": url,
                "source": source["name"],
                "region": source["region"],
                "country": country,
                "image": resolve_image(entry, url),
                "publishedAt": published.isoformat(),
                "score": score,
                "alsoIn": [],
                "sourcesCovered": [source["name"]],
                "coverageCount": 1,
            }
            by_key[key] = article
            articles.append(article)
            new_count += 1

    # poda por idade
    cutoff = now_utc() - timedelta(days=max_age_days)
    kept = []
    for a in articles:
        try:
            dt = datetime.fromisoformat(a["publishedAt"])
        except Exception:
            dt = now_utc()
        if dt >= cutoff:
            kept.append(a)
    kept.sort(key=lambda a: (a.get("score", 0), a["publishedAt"]), reverse=True)

    payload = {
        "updatedAt": now_utc().isoformat(),
        "editorialFocus": "Brasil + Internacional equilibrado",
        "sources": [{"name": s["name"], "region": s["region"]} for s in SOURCES],
        "failures": failures,
        "articles": kept,
    }
    save(payload)
    print(f"\n✓ {new_count} novas · {len(kept)} no arquivo · {skipped_thin} descartadas (resumo raso) · {len(failures)} falhas", file=sys.stderr)
    return payload


def load_existing():
    if os.path.exists(DATA_PATH):
        try:
            with open(DATA_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Retroativamente corrige campo country ausente/inválido
            source_country = {s["name"]: s.get("country","US") for s in SOURCES}
            for a in data.get("articles", []):
                if not a.get("country") or a["country"] == "?":
                    a["country"] = source_country.get(a.get("source",""), "US")
            return data
        except Exception:
            pass
    return {"articles": []}


def save(payload):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true", help="força só a lógica de regras")
    ap.add_argument("--max-age", type=int, default=60, help="dias de notícia mantidos no arquivo")
    args = ap.parse_args()

    use_ai = (not args.no_ai) and bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"Resumo: {'IA (com fallback p/ regra)' if use_ai else 'somente regra'}", file=sys.stderr)
    collect(use_ai=use_ai, max_age_days=args.max_age)


if __name__ == "__main__":
    main()
