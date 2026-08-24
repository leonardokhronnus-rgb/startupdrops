import { getStore } from "@netlify/blobs";

// ─────────────────────────────────────────────────────────────
// StartupDrops · Robô de reescrita automática
// Roda 3x ao dia (manhã/tarde/noite) no fuso de Brasília.
// Puxa RSS das fontes, detecta matérias novas, reescreve com
// texto próprio via IA (OpenAI ou Anthropic) e grava no Netlify Blobs.
// ─────────────────────────────────────────────────────────────

// Fontes RSS (editoria é só um rótulo padrão; a IA confirma o tom)
const FONTES = [
  { outlet: "Startupi",         editoria: "Startups",   rss: "https://startupi.com.br/feed/" },
  { outlet: "Startups.com.br",  editoria: "Startups",   rss: "https://startups.com.br/feed/" },
  { outlet: "Pipeline Valor Startups", editoria: "Startups", rss: "https://news.google.com/rss/search?q=when:3d+site:pipelinevalor.globo.com/startups+startup+OR+rodada+OR+venture+OR+fintech&hl=pt-BR&gl=BR&ceid=BR:pt-419" },
  { outlet: "NeoFeed Startups", editoria: "Funding",    rss: "https://news.google.com/rss/search?q=when:3d+site:neofeed.com.br+startup+OR+fintech+OR+venture+OR+rodada+OR+aporte+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419" },
  { outlet: "Exame Startups",   editoria: "Startups",   rss: "https://news.google.com/rss/search?q=when:3d+site:exame.com+startup+OR+fintech+OR+venture+OR+IA+OR+inovacao&hl=pt-BR&gl=BR&ceid=BR:pt-419" },
  { outlet: "Brazil Journal Tech", editoria: "Funding", rss: "https://news.google.com/rss/search?q=when:3d+site:braziljournal.com+startup+OR+fintech+OR+venture+OR+spacex+OR+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419" },
  { outlet: "IT Forum",         editoria: "Tech",       rss: "https://news.google.com/rss/search?q=when:3d+site:itforum.com.br+startup+OR+fintech+OR+IA+OR+software+OR+cloud&hl=pt-BR&gl=BR&ceid=BR:pt-419" },
  { outlet: "TechCrunch Startups", editoria: "Startups", rss: "https://techcrunch.com/category/startups/feed/" },
  { outlet: "Crunchbase News",  editoria: "Funding",    rss: "https://news.crunchbase.com/feed/" },
  { outlet: "VentureBeat",      editoria: "AI",         rss: "https://venturebeat.com/feed/" },
  { outlet: "The Verge",        editoria: "Tech",       rss: "https://www.theverge.com/rss/index.xml" },
  { outlet: "Rest of World",    editoria: "Startups",   rss: "https://restofworld.org/feed/latest/" },
  { outlet: "Tech.eu",          editoria: "Startups",   rss: "https://tech.eu/feed/" },
  { outlet: "EU-Startups",      editoria: "Startups",   rss: "https://www.eu-startups.com/feed/" },
  { outlet: "Inc42",            editoria: "Startups",   rss: "https://inc42.com/feed/" },
  { outlet: "ETtech",           editoria: "Tech",       rss: "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms" },
  { outlet: "TechNode",         editoria: "Tech",       rss: "https://technode.com/feed/" },
];

// Quantas matérias novas reescrever por execução (controla custo/tempo)
const MAX_POR_RODADA = 6;
// Quantos candidatos avaliar para conseguir preencher a rodada sem publicar ruído
const MAX_TENTATIVAS_POR_RODADA = 24;
// Quantos itens olhar por feed
const ITENS_POR_FEED = 4;
const STARTUP_SIGNALS = [
  "startup", "startups", "scale-up", "scaleup", "founder", "fundador",
  "venture", "vc", "capital de risco", "rodada", "aporte", "captação",
  "captou", "levanta", "levantou", "funding", "seed", "série a", "série b",
  "series a", "series b", "valuation", "unicórnio", "unicorn", "fintech",
  "edtech", "healthtech", "agtech", "proptech", "insurtech", "legaltech",
  "deeptech", "saas", "b2b", "software", "plataforma", "inteligência artificial",
  "artificial intelligence", "llm", "openai", "anthropic", "climate tech", "venture capital"
];
const HARD_BLOCKS = [
  "pedágio", "pedagio", "free flow", "cnh", "ipva", "imposto de renda",
  "tarifaço", "tarifa", "inflação", "selic", "copom", "pib", "dólar",
  "bolsa", "ações", "short", "recomenda compra", "carteira recomendada",
  "economistas de stanford", "alerta urgente", "cães-robôs", "caes-robos",
  "pesquisas militares", "justa causa", "atestado", "petróleo", "foz do amazonas",
  "castelo", "mansão", "celebridade", "política", "trump", "lula", "eleições",
  "eleição", "datafolha", "governadores", "previdência social", "braskem",
  "endividamento das famílias", "emendas", "congressistas", "gás natural",
  "evergrande", "prisão perpétua", "tesouro direto", "taxas do tesouro",
  "nb steak", "casas bahia", "térmica", "wall street", "mercado de títulos",
  "liverpool", "eduardo saverin", "brb", "stf", "empréstimo público",
  "farmácias", "medicamentos", "ai slop", "programação 100%",
  "robôs humanoides", "robos humanoides", "pré-ipo ao investidor comum",
  "pre-ipo ao investidor comum", "bill ackman", "ultrarricos", "miami virou"
];
const ROLE_ANNOUNCEMENT_RE = /\b(nomeia|nomeou|contrata|contratou|assume|assumiu|promove|promoveu|troca|substitui|deixa|deixou)\b.{0,70}\b(ceo|cto|cfo|coo|cio|cmo|vp|diretor|diretora|head|country manager|presidente|conselho|cargo|lideran[çc]a)\b|\b(novo|nova)\b.{0,40}\b(ceo|cto|cfo|coo|cio|cmo|vp|diretor|diretora|head|country manager|presidente|lideran[çc]a)\b|\bdan[çc]a das cadeiras\b/i;
const ROLE_STRATEGIC_EXCEPTION_RE = /\b(rodada|aporte|capta|captou|funding|s[eé]rie\s+[a-k]|seed|aquisi[çc][aã]o|m&a|ipo|fus[aã]o|exit)\b/i;

// ── Utilidades de parsing de RSS (sem dependência externa) ──
function pegarTag(bloco, tag) {
  const m = bloco.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, "i"));
  return m ? m[1] : "";
}
function limparCDATA(s) {
  return (s || "").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1");
}
function tirarHTML(s) {
  return limparCDATA(s)
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&#8217;|&#039;|&rsquo;/g, "'").replace(/&#8220;|&#8221;|&ldquo;|&rdquo;/g, '"')
    .replace(/&#8211;|&#8212;/g, "-").replace(/&quot;/g, '"')
    .replace(/\s+/g, " ").trim();
}
function limparTituloEditorial(s) {
  return tirarHTML(s).replace(/^\s*(exclusivo|exclusiva|exclusive|breaking|urgente)\s*[:\-–—]\s*/i, "").trim();
}
function parseFeed(xml) {
  const itens = [];
  const blocos = xml.split(/<item[ >]/i).slice(1);
  for (const raw of blocos) {
    const bloco = raw.split(/<\/item>/i)[0];
    const titulo = limparTituloEditorial(pegarTag(bloco, "title"));
    let link = tirarHTML(pegarTag(bloco, "link"));
    if (!link) {
      const m = bloco.match(/<link[^>]*href="([^"]+)"/i);
      if (m) link = m[1];
    }
    const desc = tirarHTML(pegarTag(bloco, "description") || pegarTag(bloco, "content:encoded"));
    if (titulo && link) itens.push({ titulo, link, resumo: desc });
  }
  return itens;
}

function hasTerm(text, term) {
  if (/^[\wÀ-ÿ]+$/i.test(term)) return new RegExp(`(?<![\\wÀ-ÿ])${term}(?![\\wÀ-ÿ])`, "i").test(text);
  return text.includes(term);
}

function hasSignal(text, terms) {
  return terms.some(term => hasTerm(text, term));
}

function candidateScore(item, fonte) {
  const text = `${item.titulo} ${item.resumo || ""} ${fonte.outlet}`.toLowerCase();
  if (hasSignal(text, HARD_BLOCKS)) return -100;
  if (ROLE_ANNOUNCEMENT_RE.test(text) && !ROLE_STRATEGIC_EXCEPTION_RE.test(text)) return -100;
  let score = 0;
  for (const term of STARTUP_SIGNALS) if (hasTerm(text, term)) score += 6;
  if (/startupi|startups\.com|pipeline valor startups|techcrunch startups|crunchbase|eu-startups|tech\.eu/i.test(fonte.outlet)) score += 18;
  if (/rodada|aporte|capta|captou|funding|seed|série|series|valuation|venture|unicórnio|unicorn/i.test(text)) score += 18;
  if (/fintech|saas|healthtech|edtech|deeptech|climate tech|ia|inteligência artificial|llm|software|plataforma/i.test(text)) score += 10;
  if (/economia|mercado|business|markets/i.test(fonte.outlet) && score < 24) score -= 20;
  return score;
}

function isStartupCandidate(item, fonte) {
  return candidateScore(item, fonte) >= 12;
}

function montarPrompt(item, fonte) {
  const base = item.resumo && item.resumo.length > 40 ? item.resumo : item.titulo;
  return `Você é redator do StartupDrops, portal brasileiro de notícias do ecossistema de startups. Recebeu a notícia abaixo, publicada originalmente pelo veículo "${fonte.outlet}". Reescreva com texto 100% próprio, no tom editorial do StartupDrops, para publicar no portal.

REGRAS OBRIGATÓRIAS:
- Reescreva do zero, com suas próprias palavras e estrutura. Não copie frases do original nem parafraseie linha a linha.
- Mantenha TODOS os fatos, nomes, empresas e números presentes no original. NÃO invente nenhum dado, número, valor ou citação que não esteja no texto. Se algo não estiver claro, não afirme.
- Tom jornalístico, direto, escaneável. Português do Brasil.
- Se a notícia original estiver em inglês, chinês ou qualquer outro idioma, traduza e reescreva completamente em português do Brasil. Não deixe palavras, frases ou estruturas em inglês no texto final.
- Só publique se fizer sentido DIRETO para founders, investidores, operadores de startups, venture capital, tecnologia, IA, fintechs, SaaS ou empresas digitais.
- Escreva apenas uma linha curta de contexto. Não gere resumo longo, análise longa nem texto que substitua a leitura da fonte original.
- Descarte macroeconomia genérica, bolsa, recomendação de ações, pedágio/free flow, impostos, política, petróleo, celebridades, consumo comum, pesquisa militar sem startup/produto comercial, ou patrimônio pessoal de executivos. Para descartar, responda com {"descartar":true}.
- Descarte notas de cargo, como CEO novo, nomeação, contratação de head/diretor/VP/country manager ou dança das cadeiras, salvo quando a notícia trouxer rodada, aquisição, IPO, fusão ou outro movimento estratégico relevante. Para descartar, responda com {"descartar":true}.
- "Mercado" só é permitido quando houver ligação clara com startup, venture capital, M&A de tech, IPO de tech, fintech, SaaS, IA ou empresa digital. Não transforme economia geral em startup.
- NÃO use travessões (—). Use vírgula, ponto ou parênteses.
- Título curto e forte (máx ~12 palavras). Linha fina de até 150 caracteres. Corpo deve ser array vazio [].
- Nunca use selos editoriais da fonte no título, como "EXCLUSIVO:", "Exclusive:", "Breaking:" ou "Urgente:".

Editoria sugerida: ${fonte.editoria}

TÍTULO ORIGINAL: ${item.titulo}
RESUMO/CONTEÚDO ORIGINAL:
"""
${base}
"""

Responda APENAS com JSON válido, sem markdown nem crases, neste formato exato:
{"titulo":"...","linha_fina":"...","corpo":[],"editoria":"Funding|Startups|Economia|Tech|Unicórnios|AI"}`;
}

function parseArticleJson(text) {
  text = String(text || "").trim();
  text = text.replace(/^```json/i, "").replace(/^```/, "").replace(/```$/, "").trim();
  const a = text.indexOf("{"), b = text.lastIndexOf("}");
  if (a >= 0 && b >= 0) text = text.slice(a, b + 1);
  const art = JSON.parse(text);
  if (art.descartar) return null;
  return art;
}

function responseText(data) {
  if (typeof data.output_text === "string") return data.output_text;
  return (data.output || [])
    .flatMap(item => item.content || [])
    .filter(part => part.type === "output_text" && part.text)
    .map(part => part.text)
    .join("")
    .trim();
}

async function reescreverOpenAI(item, fonte, apiKey) {
  const prompt = montarPrompt(item, fonte);
  const resp = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || "gpt-5-mini",
      input: prompt,
      max_output_tokens: 1200,
      text: { format: { type: "json_object" } },
    }),
  });
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(("OpenAI status " + resp.status + " " + body).slice(0, 500));
  }
  const data = await resp.json();
  return parseArticleJson(responseText(data));
}

async function reescreverAnthropic(item, fonte, apiKey) {
  const prompt = montarPrompt(item, fonte);
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",
      max_tokens: 1200,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(("Anthropic status " + resp.status + " " + body).slice(0, 500));
  }
  const data = await resp.json();
  const text = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("").trim();
  return parseArticleJson(text);
}

// ── Reescrita via IA ──
async function reescrever(item, fonte, provider) {
  if (provider.name === "openai") return reescreverOpenAI(item, fonte, provider.key);
  return reescreverAnthropic(item, fonte, provider.key);
}

// ── Handler agendado ──
export default async (req) => {
  const providers = [
    process.env.OPENAI_API_KEY && { name: "openai", key: process.env.OPENAI_API_KEY },
    process.env.ANTHROPIC_API_KEY && { name: "anthropic", key: process.env.ANTHROPIC_API_KEY },
  ].filter(Boolean);
  if (!providers.length) {
    return new Response("Falta OPENAI_API_KEY ou ANTHROPIC_API_KEY nas variáveis de ambiente.", { status: 500 });
  }
  const provider = providers[0];

  const store = getStore("materias");
  // índice: lista de matérias publicadas (mais recentes primeiro)
  let indice = [];
  try {
    const raw = await store.get("indice", { type: "json" });
    if (Array.isArray(raw)) indice = raw;
  } catch { /* primeira execução */ }

  const jaPublicados = new Set(indice.map(m => m.url_fonte));
  const candidatos = [];

  // 1) Coletar itens novos de cada feed
  for (const fonte of FONTES) {
    try {
      const r = await fetch(fonte.rss, { headers: { "User-Agent": "StartupDrops/1.0" } });
      if (!r.ok) continue;
      const xml = await r.text();
      const itens = parseFeed(xml).slice(0, ITENS_POR_FEED);
      for (const it of itens) {
        if (!jaPublicados.has(it.link) && isStartupCandidate(it, fonte)) candidatos.push({ item: it, fonte });
      }
    } catch (e) {
      console.log("Falha no feed", fonte.outlet, e.message);
    }
  }

  // 2) Reescrever até preencher a rodada, tentando mais itens se a IA descartar ruído
  candidatos.sort((a, b) => candidateScore(b.item, b.fonte) - candidateScore(a.item, a.fonte));
  const aReescrever = candidatos.slice(0, MAX_TENTATIVAS_POR_RODADA);
  let publicadas = 0;
  let analisadas = 0;
  let descartadas = 0;
  let falhas = 0;
  let primeiroErro = "";

  for (const c of aReescrever) {
    if (publicadas >= MAX_POR_RODADA) break;
    analisadas++;
    try {
      const art = await reescrever(c.item, c.fonte, provider);
      if (!art) {
        descartadas++;
        continue;
      }
      const id = "m_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
      const registro = {
        id,
        titulo: art.titulo,
        linha_fina: art.linha_fina,
        corpo: art.corpo,
        editoria: art.editoria || c.fonte.editoria,
        outlet: c.fonte.outlet,
        url_fonte: c.item.link,
        publicado_em: new Date().toISOString(),
      };
      await store.setJSON("artigo_" + id, registro);
      indice.unshift({
        id,
        titulo: registro.titulo,
        editoria: registro.editoria,
        outlet: registro.outlet,
        url_fonte: registro.url_fonte,
        publicado_em: registro.publicado_em,
      });
      publicadas++;
    } catch (e) {
      falhas++;
      if (!primeiroErro) primeiroErro = e.message;
      console.log("Falha ao reescrever", c.item.titulo, e.message);
    }
  }

  // 3) Manter índice enxuto (últimas 200)
  indice = indice.slice(0, 200);
  await store.setJSON("indice", indice);

  return new Response(
    JSON.stringify({ ok: true, provider: provider.name, candidatos: candidatos.length, analisadas, publicadas, descartadas, falhas, primeiroErro, total: indice.length }),
    { headers: { "Content-Type": "application/json" } }
  );
};

// 3x ao dia em horário de Brasília (UTC-3): 08h, 14h e 20h BRT
// = 11:00, 17:00 e 23:00 UTC
export const config = {
  schedule: "0 11,17,23 * * *",
};
