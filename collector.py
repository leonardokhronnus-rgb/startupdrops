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
    # Google News RSS e usado como resgate quando o feed nativo da publicacao
    # esta quebrado. Formato: news.google.com/rss/search?q=when:2d site:DOMINIO
 
    # -- BRASIL: startups e tech (feeds nativos funcionando) --
    {"name": "Startupi",              "region": "Brasil",         "country": "BR", "feed": "https://startupi.com.br/feed/"},
    {"name": "Startups.com.br",       "region": "Brasil",         "country": "BR", "feed": "https://startups.com.br/feed/"},
    {"name": "NeoFeed Startups",      "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:neofeed.com.br+startup+OR+fintech+OR+venture+OR+rodada+OR+aporte+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Brazil Journal Tech",   "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:braziljournal.com+startup+OR+fintech+OR+venture+OR+spacex+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "InfoMoney Startups",    "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:infomoney.com.br+startup+OR+fintech+OR+venture+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Exame Startups",        "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:exame.com+startup+OR+fintech+OR+venture+OR+IA+OR+inovacao&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Bloomberg Linea Tech",  "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:bloomberglinea.com.br+startup+OR+fintech+OR+venture+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Finsiders Brasil",      "region": "Brasil",         "country": "BR", "feed": "https://finsidersbrasil.com.br/feed/"},
    {"name": "Money Times Tech",      "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:moneytimes.com.br/tecnologia+startup+OR+fintech+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Inovação Tecnológica",  "region": "Brasil",         "country": "BR", "feed": "https://www.inovacaotecnologica.com.br/boletim/rss.xml"},
    {"name": "G1 Startups e Tech",    "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:g1.globo.com+startup+OR+fintech+OR+IA+OR+tecnologia&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
 
    # -- BRASIL: resgate via Google News (feeds nativos quebrados) --
    {"name": "IT Forum",              "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:2d+site:itforum.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Pipeline Valor Startups","region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:pipelinevalor.globo.com/startups+startup+OR+rodada+OR+venture+OR+fintech&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Valor Startups",        "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:valor.globo.com+startup+OR+fintech+OR+venture+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Epoca Negocios",        "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:2d+site:epocanegocios.globo.com&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "CNN Brasil Tech",       "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:cnnbrasil.com.br+startup+OR+fintech+OR+IA+OR+tecnologia&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Estadao Startups",      "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:estadao.com.br+startup+OR+fintech+OR+venture+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "PEGN",                  "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:2d+site:pegn.globo.com&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "MIT Tech Review BR",    "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:mittechreview.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "E-Commerce Brasil",     "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:ecommercebrasil.com.br+tecnologia+OR+marketplace+OR+startup&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
 
    # -- BRASIL: fontes extras de startup/tech (adicionadas) --
    {"name": "Draft",                 "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:projetodraft.com&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Distrito",              "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:5d+site:distrito.me&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Abstartups",            "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:7d+site:abstartups.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "StartSe",               "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:startse.com&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "MobileTime",            "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:mobiletime.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "Convergencia Digital",  "region": "Brasil",         "country": "BR", "feed": "https://news.google.com/rss/search?q=when:3d+site:convergenciadigital.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
 
    # -- EUA / GLOBAL: startups, VC e tech --
    {"name": "TechCrunch Startups",   "region": "Internacional",  "country": "US", "feed": "https://techcrunch.com/category/startups/feed/"},
    {"name": "Crunchbase News",       "region": "Internacional",  "country": "US", "feed": "https://news.crunchbase.com/feed/"},
    {"name": "VentureBeat",           "region": "Internacional",  "country": "US", "feed": "https://venturebeat.com/feed/"},
    {"name": "The Verge",             "region": "Internacional",  "country": "US", "feed": "https://www.theverge.com/rss/index.xml"},
    {"name": "Wired",                 "region": "Internacional",  "country": "US", "feed": "https://www.wired.com/feed/rss"},
    {"name": "Rest of World",         "region": "Internacional",  "country": "US", "feed": "https://restofworld.org/feed/latest/"},
    {"name": "a16z",                  "region": "Internacional",  "country": "US", "feed": "https://a16z.com/feed/"},
    {"name": "First Round Review",    "region": "Internacional",  "country": "US", "feed": "https://review.firstround.com/feed.xml"},
    {"name": "Axios Pro Rata",        "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:2d+site:axios.com+venture+OR+startup&hl=en-US&gl=US&ceid=US:en"},
 
    # -- EUA / GLOBAL: resgate via Google News --
    {"name": "Reuters Startups",      "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:2d+site:reuters.com+startup+OR+venture+OR+fintech+OR+artificial+intelligence&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Reuters Tech",          "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:2d+site:reuters.com+technology&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Bloomberg Tech",        "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:2d+site:bloomberg.com+technology+OR+startup&hl=en-US&gl=US&ceid=US:en"},
    {"name": "Bloomberg Startups",    "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:2d+site:bloomberg.com+startup+OR+venture+OR+fintech+OR+artificial+intelligence&hl=en-US&gl=US&ceid=US:en"},
    {"name": "The Information",       "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:2d+site:theinformation.com&hl=en-US&gl=US&ceid=US:en"},
 
    # -- EUROPA --
    {"name": "Tech.eu",               "region": "Internacional",  "country": "EU", "feed": "https://tech.eu/feed/"},
    {"name": "EU-Startups",           "region": "Internacional",  "country": "EU", "feed": "https://www.eu-startups.com/feed/"},
    {"name": "Sifted",                "region": "Internacional",  "country": "EU", "feed": "https://news.google.com/rss/search?q=when:3d+site:sifted.eu&hl=en-US&gl=US&ceid=US:en"},
 
    # -- AMERICA LATINA (novo eixo) --
    {"name": "Contxto",               "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:3d+site:contxto.com&hl=pt-BR&gl=BR&ceid=BR:pt-419"},
    {"name": "LABS Latam",            "region": "Internacional",  "country": "US", "feed": "https://news.google.com/rss/search?q=when:3d+site:labsnews.com&hl=en-US&gl=US&ceid=US:en"},
 
    # -- CHINA --
    {"name": "SCMP Tech",             "region": "Internacional",  "country": "CN", "feed": "https://www.scmp.com/rss/36/feed"},
    {"name": "SCMP Business",         "region": "Internacional",  "country": "CN", "feed": "https://www.scmp.com/rss/92/feed"},
    {"name": "TechNode",              "region": "Internacional",  "country": "CN", "feed": "https://technode.com/feed/"},
    {"name": "Caixin Global",         "region": "Internacional",  "country": "CN", "feed": "https://news.google.com/rss/search?q=when:2d+site:caixinglobal.com&hl=en-US&gl=US&ceid=US:en"},
    {"name": "KrASIA",                "region": "Internacional",  "country": "CN", "feed": "https://news.google.com/rss/search?q=when:3d+site:kr-asia.com&hl=en-US&gl=US&ceid=US:en"},
 
    # -- INDIA --
    {"name": "Inc42",                 "region": "Internacional",  "country": "IN", "feed": "https://inc42.com/feed/"},
    {"name": "YourStory",             "region": "Internacional",  "country": "IN", "feed": "https://yourstory.com/feed"},
    {"name": "ETtech",                "region": "Internacional",  "country": "IN", "feed": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"},
    {"name": "Entrackr",              "region": "Internacional",  "country": "IN", "feed": "https://news.google.com/rss/search?q=when:2d+site:entrackr.com&hl=en-IN&gl=IN&ceid=IN:en"},
]
 
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "news.json")
USER_AGENT = "StartupDropsBot/1.0 (+https://startupdrops)"
REQUEST_TIMEOUT = 20
ACTIVE_COUNTRIES = {"BR", "US", "EU", "CN", "IN"}
 
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
    "pedágio", "pedagio", "free flow", "cnh", "ipva", "imposto de renda",
    "tarifaço", "tarifa", "pib", "selic", "copom", "inflação", "dólar",
    "eleições", "eleição", "datafolha", "governador", "governadores",
    "previdência social", "déficit da previdência", "lula", "flávio",
    "emendas", "congressistas", "irã", "gás natural", "braskem",
    "crédito sem garantia", "endividamento das famílias",
    "recessão", "tesouro ipca", "ipca+", "lei ambiental", "segurança jurídica",
    "prime video", "câmeras espiãs", "cameras espias", "soberania tecnológica",
    "soberania tecnologica", "plano de ia", "supercomputadores", "nuvem brasileira",
    "evergrande", "prisão perpétua", "prisao perpetua", "tesouro direto",
    "taxas do tesouro", "nb steak", "casas bahia", "térmica", "termica",
    "wall street", "mercado de títulos", "mercado de titulos",
    "crédito ao endividado", "credito ao endividado", "inadimplência",
    "inadimplencia", "masters 1000", "joão fonseca", "joao fonseca",
    "discord avisa", "suspensão de lives", "suspensao de lives",
    "liverpool", "eduardo saverin",
    "brb", "banco de brasília", "banco de brasilia", "stf",
    "destravar empréstimo", "destravar emprestimo", "empréstimo bilionário",
    "emprestimo bilionario", "farmácias", "farmacias", "medicamentos",
    "remédios", "remedios", "ai slop", "programação 100%",
    "robôs humanoides", "robos humanoides", "pré-ipo ao investidor comum",
    "pre-ipo ao investidor comum", "bill ackman", "ultrarricos", "miami virou",
    "emissão recorde de títulos", "emissao recorde de titulos",
    "mercado de títulos", "mercado de titulos", "jp morgan", "lucro",
    "itau no varejo", "itaú no varejo", "banir o discord", "julgamento da meta",
    "algoritmos e publicidade",
    "recomenda compra", "carteira recomendada", "ações", " short ", "buy",
    "economistas de stanford", "alerta urgente", "pesquisas militares",
    "cães-robôs", "caes-robos", "petróleo", "foz do amazonas",
    # empresas fora do ecossistema de tech/startups
    "jbs ", " jbs", "batista clan", "meat supplier", "meatpacker",
    "frigorífico", "frigorif",
    # propaganda e eventos
    "save $", "register now", "buy tickets", "early bird",
    "disrupt ", "techcrunch disrupt",
]

# Fontes tech generalistas são úteis, mas trazem muito gadget, promoção, games
# e consumo. Para elas, exigimos sinal claro de negócio/ecossistema.
NOISY_TECH_SOURCES = {"Tecnoblog", "Canaltech", "Olhar Digital"}

BROAD_BUSINESS_SOURCES = {
    "G1 Startups e Tech", "Exame Startups", "Brazil Journal Tech",
    "InfoMoney Startups", "Bloomberg Linea Tech", "Valor Startups",
    "CNN Brasil Tech", "Estadao Startups", "Reuters Startups",
    "Reuters Tech", "Bloomberg Tech", "Bloomberg Startups",
    "G1 Economia", "Exame", "Brazil Journal", "InfoMoney", "Bloomberg Linea BR",
    "Valor Economico", "Exame Economia", "CNN Brasil Business",
    "Estadao Economia", "Reuters Business", "Bloomberg Markets",
    "NeoFeed", "Startupi",
}

STARTUP_FIRST_REQUIRED = [
    "startup", "startups", "scale-up", "scaleup", "founder", "fundador",
    "empreendedor", "venture", "capital de risco", "vc ", "rodada", "aporte",
    "captação", "captou", "levanta", "levantou", "funding", "seed", "série a",
    "série b", "series a", "series b", "valuation", "unicórnio", "unicorn",
    "fintech", "edtech", "healthtech", "agtech", "proptech", "insurtech",
    "legaltech", "deeptech", "saas", "b2b", "software", "plataforma",
    "empresa digital", "produto digital", "inteligência artificial",
    "artificial intelligence", "llm", "openai", "anthropic", "climate tech",
    "nubank", "ifood", "stone", "mercado livre", "quintoandar", "kovi",
    "tractian", "neon", "c6 bank", "inter", "picpay", "gympass", "wellhub",
    "olist", "loft", "loggi", "wildlife", "ebury", "pismo", "celcoin",
]

TRUSTED_STARTUP_SOURCES = {
    "Startupi", "Startups.com.br", "Pipeline Valor Startups", "TechCrunch Startups",
    "Crunchbase News", "Tech.eu", "EU-Startups", "Inc42", "YourStory", "Entrackr",
}

CORE_STARTUP_CONTEXT = [
    "startup", "startups", "scale-up", "scaleup", "founder", "fundador",
    "empreendedor", "venture", "capital de risco", "rodada", "aporte",
    "captação", "captou", "funding", "seed", "série a", "série b",
    "series a", "series b", "valuation", "unicórnio", "unicorn",
    "fintech", "edtech", "healthtech", "agtech", "proptech", "insurtech",
    "legaltech", "deeptech", "saas", "b2b", "vc ",
]

ROLE_ANNOUNCEMENT_RE = re.compile(
    r"\b(nomeia|nomeou|contrata|contratou|assume|assumiu|promove|promoveu|"
    r"troca|substitui|deixa|deixou)\b.{0,80}\b(ceo|cto|cfo|coo|cio|cmo|vp|"
    r"diretor|diretora|head|country manager|presidente|conselho|cargo|"
    r"lideran[çc]a)\b|"
    r"\b(novo|nova)\b.{0,50}\b(ceo|cto|cfo|coo|cio|cmo|vp|diretor|diretora|"
    r"head|country manager|presidente|lideran[çc]a)\b|"
    r"\bdan[çc]a das cadeiras\b",
    re.I,
)
ROLE_STRATEGIC_EXCEPTION_RE = re.compile(
    r"\b(rodada|aporte|capta|captou|funding|s[eé]rie\s+[a-k]|seed|"
    r"aquisi[çc][aã]o|m&a|ipo|fus[aã]o|exit)\b",
    re.I,
)

BROAD_SOURCE_REQUIRED = [
    "startup", "startups", "scale-up", "scaleup", "founder", "fundador",
    "empreendedor", "venture", "capital de risco", "rodada", "aporte",
    "captação", "captou", "funding", "seed", "série a", "série b",
    "series a", "series b", "valuation", "unicórnio", "unicorn",
    "fintech", "edtech", "healthtech", "agtech", "proptech", "insurtech",
    "legaltech", "deeptech", "saas", "b2b", "venture capital",
    "nubank", "ifood", "stone", "mercado livre", "quintoandar", "kovi",
    "tractian", "neon", "c6 bank", "inter", "picpay", "gympass", "wellhub",
    "olist", "loft", "loggi", "wildlife", "ebury", "pismo", "celcoin",
]

NOISY_TECH_REQUIRED = [
    "startup", "fintech", "healthtech", "edtech", "agtech", "proptech", "saas",
    "venture", "investimento", "rodada", "aporte", "captação", "valuation",
    "aquisição", "m&a", "ipo", "unicórnio", "mercado", "empresa", "companhia",
    "negócio", "receita", "lucro", "cliente empresarial", "clientes empresariais",
    "b2b", "corporativo", "empresarial", "executivo", "executivos", "conselho",
    "acionistas",
    "open finance", "pix", "banco central", "regulação", "regulatório", "lgpd",
    "cibersegurança", "segurança cibernética", "data center", "cloud",
    "mercado financeiro", "cade",
]

NOISY_TECH_BLOCKLIST = [
    "promoção", "oferta", "amazon", "magalu", "mercado livre", "cupom",
    "smartphone", "celular", "tablet", "smartwatch", "fone", "bluetooth",
    "headset", "soundbar", "tv ", "fire tv", "ssd", "monitor", "mouse",
    "notebook gamer", "jogo", "games", "gamer", "playstation", "xbox",
    "nintendo", "streaming", "filme", "série", "cinema", "anime",
    "onde assistir", "horário e escalação", "brasileirão", "futebol",
    "roteador", "wi-fi", "smart speaker", "alexa", "iphone", "windows",
    "chrome", "edge", "ublock", "senha", "foto é real", "câmera de ação",
    "npcs", "multiplayer", "pubg", "marvel rivals", "spotify", "criadores",
    "sol", "matemático", "riemann", "marca d'água", "marca d’água",
    "pornografia", "sexual", "imagens criminosas", "enteada", "padrasto",
]

BLOCKED_DISPLAY_SOURCES = NOISY_TECH_SOURCES | {
    "Business Insider Tech", "Ars Technica", "Finsider",
}


def article_source_names(article):
    names = set()
    source = article.get("source")
    if source:
        names.add(source)
    for field in ("sources", "sourcesCovered"):
        for item in article.get(field, []) or []:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict) and item.get("source"):
                names.add(item["source"])
    for item in article.get("alsoIn", []) or []:
        if isinstance(item, dict) and item.get("source"):
            names.add(item["source"])
    return names


def clean_title(text):
    """Limpa titulo: remove so HTML/entidades e espacos. NUNCA remove credito de
    foto (isso decepava titulos com AP/capta/Apple, gerando 'Meta', 'mudou')."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"^\s*(exclusivo|exclusiva|exclusive|breaking|urgente)\s*[:\-–—]\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def title_broken(a):
    """Titulo corrompido: palavra solta ou comeca minusculo."""
    t = (a.get("title") or "").strip()
    if len(t.split()) <= 2:
        return True
    return bool(t) and t[0].islower()


ENGLISH_RESIDUE = re.compile(
    r"\b(the|with|from|for|and|company|companies|market|growth|announced|"
    r"acquisition|raises|raised|funding|round|seed|series|backed|launches|"
    r"launched|unveils|based|develop|platform|to build|first close|its|"
    r"expand|new|deal|invests|invested|startup founders|venture-backed)\b",
    re.I,
)


def looks_translated(article):
    """Internacional so deve aparecer se estiver em pt-BR fluente."""
    if article.get("country") == "BR":
        return True
    if article.get("summaryMethod") != "ia":
        return False
    text = f"{article.get('title','')} {article.get('summary','')} {article.get('whyMatters','')}"
    return not ENGLISH_RESIDUE.search(text)


def startup_term_in_text(text, term):
    term = term.strip().lower()
    if re.fullmatch(r"[\wÀ-ÿ]+", term):
        return re.search(rf"(?<![\wÀ-ÿ]){re.escape(term)}(?![\wÀ-ÿ])", text) is not None
    return term in text


def is_allowed_display_article(article):
    text = f" {article.get('title','')} {article.get('summary','')} {article.get('whyMatters','')} ".lower()
    has_startup_context = any(startup_term_in_text(text, term) for term in STARTUP_FIRST_REQUIRED)
    has_core_startup_context = any(startup_term_in_text(text, term) for term in CORE_STARTUP_CONTEXT)
    source_names = article_source_names(article)
    broad_source_ok = True
    if not source_names.isdisjoint(BROAD_BUSINESS_SOURCES):
        broad_source_ok = any(startup_term_in_text(text, term) for term in BROAD_SOURCE_REQUIRED)
    is_blocked = any(term in text for term in BLOCKLIST)
    is_role_announcement = ROLE_ANNOUNCEMENT_RE.search(text) and not ROLE_STRATEGIC_EXCEPTION_RE.search(text)
    trusted_source = not source_names.isdisjoint(TRUSTED_STARTUP_SOURCES)
    return (
        article.get("country") in ACTIVE_COUNTRIES
        and not title_broken(article)
        and looks_translated(article)
        and source_names.isdisjoint(BLOCKED_DISPLAY_SOURCES)
        and has_startup_context
        and (trusted_source or has_core_startup_context)
        and broad_source_ok
        and not is_blocked
        and not is_role_announcement
    )


def contains_term(text, term):
    term = term.strip().lower()
    if not term:
        return False
    if re.fullmatch(r"[\wÀ-ÿ]+", term):
        return re.search(rf"(?<![\wÀ-ÿ]){re.escape(term)}(?![\wÀ-ÿ])", text) is not None
    return term in text


def passes_editorial_scope(source_name, title, summary):
    text = f" {title} {summary} ".lower()
    if ROLE_ANNOUNCEMENT_RE.search(text) and not ROLE_STRATEGIC_EXCEPTION_RE.search(text):
        return False
    if source_name in BROAD_BUSINESS_SOURCES:
        return any(contains_term(text, term) for term in BROAD_SOURCE_REQUIRED)
    if source_name not in NOISY_TECH_SOURCES:
        return True
    if len([w for w in title.split() if len(w) > 2]) < 3:
        return False
    if any(contains_term(text, term) for term in NOISY_TECH_BLOCKLIST):
        return False
    return any(contains_term(text, term) for term in NOISY_TECH_REQUIRED)
 
 
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
        # "Divulgação/Instagram", "Reprodução/Twitter", "Divulgação" solto
        r"(?:^|\s)(?:Divulgação|Reprodução|Getty\s+Images)\s*/?\s*[A-Za-zÀ-Ú][\w.\-]{0,25}?\s+(?=[A-ZÀ-Ú])",
        # "Descrição Fotógrafo/Agência" (agencia precedida de espaco ou barra, com \b)
        r"^[^.!?]{0,180}[\s/]\b(?:Reuters|AFP|Getty|Bloomberg|Shutterstock|EPA|EFE|Lusa|Folhapress|Agência\s+Brasil)\b[^.!?]{0,40}\s+(?=[A-ZÀ-Ú])",
    ]
    for p in patterns:
        text = re.sub(p, " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()
 
 
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
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
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
        f"Você é editor sênior de um portal brasileiro sobre startups e tecnologia global.\n"
        f"REGRAS ABSOLUTAS:\n"
        f"- Escreva TUDO em português do Brasil correto e fluente. ZERO palavras em inglês no texto final.\n"
        f"- Se o original estiver em inglês ou chinês, TRADUZA completamente. Não misture idiomas.\n"
        f"- O TÍTULO deve ser específico: diga O QUE aconteceu, com QUEM e POR QUÊ importa. NUNCA use 'X avança em Y' ou 'X anuncia Z'.\n"
        f"- NÃO invente dados. NÃO inclua legendas de foto ou créditos de imagem.\n\n"
        f"Com base no título e texto abaixo, gere:\n"
        f"TÍTULO: [título específico em pt-BR, máx 90 chars, sem verbos vagos]\n"
        f"O QUE ACONTECEU: [2 frases objetivas em pt-BR com fatos, números e nomes]\n"
        f"POR QUE IMPORTA: [1 frase em pt-BR sobre relevância para founders/investidores]\n\n"
        f"Título original: {title}\n"
        f"Texto: {source_text}"
    )
    try:
        resp = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        out = " ".join(parts).strip()
        new_title, what_happened, why_matters = None, [], None
        for raw_line in out.split("\n"):
            # tolera negrito markdown, marcadores, espacos e acento no rotulo
            line = raw_line.strip().lstrip("*#->").strip().replace("*", "").strip()
            u = line.upper().replace("Í", "I").replace(" :", ":")
            if u.startswith("TITULO:"):
                new_title = line.split(":", 1)[1].strip()
            elif u.startswith("O QUE ACONTECEU:"):
                what_happened.append(line.split(":", 1)[1].strip())
            elif u.startswith("POR QUE IMPORTA:"):
                why_matters = line.split(":", 1)[1].strip()
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
 
    articles = [a for a in by_key.values() if is_allowed_display_article(a)]
    failures = []
    seen_now = set()
    new_count = 0
    skipped_thin = 0
    skipped_untranslated = 0
 
    for source in SOURCES:
        if source.get("country") not in ACTIVE_COUNTRIES:
            continue
        if source.get("country") != "BR" and not use_ai:
            continue
        print(f"→ {source['name']}", file=sys.stderr)
        parsed, err = fetch_feed(source)
        if err or parsed is None:
            failures.append({"source": source["name"], "url": source["feed"], "reason": err or "sem retorno"})
            continue
 
        for entry in parsed.entries[:25]:
            url = entry.get("link", "").strip()
            title = clean_title(entry.get("title", ""))
            if not url or not title:
                continue
            key = canonical_key(url)
            if key in seen_now:
                continue
            seen_now.add(key)
 
            if key in by_key:  # já arquivada
                continue
 
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
 
            in_editorial_scope = passes_editorial_scope(source["name"], title, clean_summary)

            if not (enough_length and enough_sentences and distinct_from_title and is_relevant and in_editorial_scope) or is_blocked:
                skipped_thin += 1
                continue
 
            score = score_article(title, clean_summary)
            final_title = clean_title(ai_title if ai_title else title)
 
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
            if not is_allowed_display_article(article):
                skipped_untranslated += 1
                continue
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
    # Ordena por DATA primeiro (mais recente no topo), score so como desempate
    kept.sort(key=lambda a: (a["publishedAt"], a.get("score", 0)), reverse=True)
 
    payload = {
        "updatedAt": now_utc().isoformat(),
        "editorialFocus": "Brasil: startups, negócios, inovação e tecnologia aplicada",
        "sources": [
            {"name": s["name"], "region": s["region"]}
            for s in SOURCES
            if s.get("country") in ACTIVE_COUNTRIES and s["name"] not in BLOCKED_DISPLAY_SOURCES
        ],
        "failures": failures,
        "articles": kept,
    }
    save(payload)
    print(f"\n✓ {new_count} novas · {len(kept)} no arquivo · {skipped_thin} descartadas (resumo raso) · {skipped_untranslated} internacionais sem tradução · {len(failures)} falhas", file=sys.stderr)
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
    ap.add_argument("--max-age", type=int, default=120, help="dias de notícia mantidos no arquivo")
    args = ap.parse_args()
 
    use_ai = (not args.no_ai) and bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"Resumo: {'IA (com fallback p/ regra)' if use_ai else 'somente regra'}", file=sys.stderr)
    collect(use_ai=use_ai, max_age_days=args.max_age)
 
 
if __name__ == "__main__":
    main()
