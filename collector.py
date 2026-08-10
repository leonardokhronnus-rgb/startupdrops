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
    {"name": "Startupi",              "region": "Brasil",         "feed": "https://startupi.com.br/feed/"},
    {"name": "Startups.com.br",       "region": "Brasil",         "feed": "https://startups.com.br/feed/"},
    {"name": "NeoFeed",               "region": "Brasil",         "feed": "https://neofeed.com.br/feed/"},
    {"name": "Exame",                 "region": "Brasil",         "feed": "https://exame.com/feed/"},
    {"name": "Brazil Journal",        "region": "Brasil",         "feed": "https://braziljournal.com/feed/"},
    {"name": "Pipeline Valor",        "region": "Brasil",         "feed": "https://pipelinevalor.globo.com/rss/"},
    {"name": "IT Forum",              "region": "Brasil",         "feed": "https://itforum.com.br/feed/"},
    {"name": "Olhar Digital",         "region": "Brasil",         "feed": "https://olhardigital.com.br/feed/"},
    {"name": "Tecnoblog",             "region": "Brasil",         "feed": "https://tecnoblog.net/feed/"},
    {"name": "Inovação Tecnológica",  "region": "Brasil",         "feed": "https://www.inovacaotecnologica.com.br/boletim/rss.xml"},
    {"name": "InfoMoney",             "region": "Brasil",         "feed": "https://www.infomoney.com.br/feed/"},
    {"name": "Baguete",               "region": "Brasil",         "feed": "https://www.baguete.com.br/rss.xml"},
    {"name": "Época Negócios",        "region": "Brasil",         "feed": "https://epocanegocios.globo.com/rss/epoca-negocios/"},
    # Internacional
    {"name": "TechCrunch Startups",   "region": "Internacional",  "feed": "https://techcrunch.com/category/startups/feed/"},
    {"name": "Crunchbase News",       "region": "Internacional",  "feed": "https://news.crunchbase.com/feed/"},
    {"name": "VentureBeat",           "region": "Internacional",  "feed": "https://venturebeat.com/feed/"},
    {"name": "Sifted",                "region": "Internacional",  "feed": "https://sifted.eu/feed"},
    {"name": "Business Insider Tech",  "region": "Internacional",  "feed": "https://www.businessinsider.com/sai/rss"},
    {"name": "Rest of World",         "region": "Internacional",  "feed": "https://restofworld.org/feed/latest/"},
    {"name": "The Verge",             "region": "Internacional",  "feed": "https://www.theverge.com/rss/index.xml"},
    {"name": "Ars Technica",          "region": "Internacional",  "feed": "https://feeds.arstechnica.com/arstechnica/index"},
    {"name": "Wired",                 "region": "Internacional",  "feed": "https://www.wired.com/feed/rss"},

    # Brasil — Economia e Mercado
    {"name": "Exame Economia",        "region": "Brasil",         "feed": "https://exame.com/economia/feed/"},
    {"name": "Exame Invest",          "region": "Brasil",         "feed": "https://exame.com/invest/feed/"},
    {"name": "G1 Economia",           "region": "Brasil",         "feed": "https://g1.globo.com/dynamo/economia/rss2.xml"},
    {"name": "Valor Econômico",       "region": "Brasil",         "feed": "https://valor.globo.com/rss/ultimas-noticias/"},
    {"name": "CNN Brasil Business",   "region": "Brasil",         "feed": "https://www.cnnbrasil.com.br/economia/feed/"},
    {"name": "Infomoney Economia",    "region": "Brasil",         "feed": "https://www.infomoney.com.br/economia/feed/"},
    {"name": "Broadcast Político",    "region": "Brasil",         "feed": "https://www.estadao.com.br/economia/rss/"},
    # Internacional — Economia e Mercado
    {"name": "Reuters Business",      "region": "Internacional",  "feed": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "Bloomberg Markets",     "region": "Internacional",  "feed": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "FT Companies",          "region": "Internacional",  "feed": "https://www.ft.com/companies?format=rss"},
    # Alguns feeds mudam de URL ou exigem checagem. Rode o collector e veja se
    # aparecem em "falhas"; se falharem, ajuste a URL ou remova.
    # {"name": "MIT Tech Review BR",  "region": "Brasil",         "feed": "https://mittechreview.com.br/feed/"},
    # {"name": "PEGN",                "region": "Brasil",         "feed": "https://revistapegn.globo.com/rss/ultimas/feed.xml"},
    # {"name": "Axios",               "region": "Internacional",  "feed": "https://api.axios.com/feed/"},
]

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "news.json")
USER_AGENT = "StartupDropsBot/1.0 (+https://startupdrops)"
REQUEST_TIMEOUT = 20

# Portão de qualidade: resumo precisa ter pelo menos este tamanho pra virar matéria.
# Fontes que só entregam trecho curto (HBR, muitos paywalls) são descartadas
# em vez de virarem card raso.
MIN_SUMMARY_CHARS = 180


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
    """Remove legenda/crédito de foto no início do texto.
    Ex.: 'Claude Fable | Crédito: RixAiArt / Shutterstock.com Empresa diz...' -> 'Empresa diz...'"""
    patterns = [
        r"^[^.!?]{0,120}\|\s*(?:Crédito|Credito|Foto|Fonte|Imagem|Reprodução)\s*:\s*[^.!?]{2,120}?(?:\.com|\.br|\.org|\.net)\s+(?=[A-ZÀ-Ú])",
        r"^(?:Crédito|Credito|Foto|Fonte|Imagem|Reprodução)\s*:\s*[^.!?]{2,120}?(?:\.com|\.br|\.org|\.net)\s+(?=[A-ZÀ-Ú])",
        r"^[^.!?]{0,120}\|\s*(?:Crédito|Credito|Foto|Fonte|Imagem|Reprodução)\s*:\s*[^.!?]{2,80}\s+(?=[A-ZÀ-Ú])",
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


def summary_by_ai(title, raw_summary, region):
    client = get_anthropic()
    if not client:
        return None
    source_text = strip_html(raw_summary)[:1500]
    lang = "português do Brasil" if region == "Internacional" else "português do Brasil"
    prompt = (
        f"Resuma a notícia de startup abaixo em 2 frases claras em {lang}, tom jornalístico e direto. "
        f"NÃO invente dados, valores ou nomes que não estejam no texto. Se um número não estiver claro, omita. "
        f"Responda apenas com o resumo, sem preâmbulo.\n\n"
        f"Título: {title}\n"
        f"Texto: {source_text}"
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        out = " ".join(parts).strip()
        # segurança: se a IA devolver algo vazio ou suspeito, cai na regra
        if len(out) < 20:
            return None
        return out
    except Exception as e:
        print(f"  [ia] falha na sumarização ({e}); usando regra", file=sys.stderr)
        return None


def build_summary(title, raw_summary, region, use_ai):
    if use_ai:
        ai = summary_by_ai(title, raw_summary, region)
        if ai:
            return ai, "ia"
    return summary_by_rule(title, raw_summary), "regra"


# ── COLETA ────────────────────────────────────────────────────────────────────
def fetch_feed(source):
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(source["feed"], headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return feedparser.parse(r.content), None
    except Exception as e:
        return None, str(e)


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

            if key in by_key:  # já arquivada; não re-resume nem gasta IA
                continue

            raw_summary = entry.get("summary", "") or ""
            published = parse_date(entry)
            summary, method = build_summary(title, raw_summary, source["region"], use_ai)

            # Portão de qualidade: se não dá pra entregar um resumo denso, não entra.
            # Regra: precisa ter substância (>= MIN_SUMMARY_CHARS) e mais de uma frase,
            # ou seja, nada de card raso com meia frase e link pra fora.
            clean_summary = summary.strip()
            enough_length = len(clean_summary) >= MIN_SUMMARY_CHARS
            enough_sentences = len(re.findall(r"[.!?]", clean_summary)) >= 1
            distinct_from_title = normalize_txt(clean_summary) != normalize_txt(title)
            if not (enough_length and enough_sentences and distinct_from_title):
                skipped_thin += 1
                continue

            score = score_article(title, summary)

            article = {
                "id": make_id(source["name"], url),
                "_key": key,
                "title": title,
                "summary": summary,
                "summaryMethod": method,
                "url": url,
                "source": source["name"],
                "region": source["region"],
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
                return json.load(f)
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
