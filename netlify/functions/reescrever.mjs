import { getStore } from "@netlify/blobs";

// ─────────────────────────────────────────────────────────────
// StartupDrops · Robô de reescrita automática
// Roda 3x ao dia (manhã/tarde/noite) no fuso de Brasília.
// Puxa RSS das fontes, detecta matérias novas, reescreve com
// texto próprio via API Anthropic e grava no Netlify Blobs.
// ─────────────────────────────────────────────────────────────

// Fontes RSS (editoria é só um rótulo padrão; a IA confirma o tom)
const FONTES = [
  { outlet: "Startupi",         editoria: "Startups",   rss: "https://startupi.com.br/feed/" },
  { outlet: "Startups.com.br",  editoria: "Startups",   rss: "https://startups.com.br/feed/" },
  { outlet: "NeoFeed",          editoria: "Funding",    rss: "https://neofeed.com.br/feed/" },
  { outlet: "Exame",            editoria: "Economia",   rss: "https://exame.com/feed/" },
  { outlet: "Brazil Journal",   editoria: "Funding",    rss: "https://braziljournal.com/feed/" },
  { outlet: "IT Forum",         editoria: "Tech",       rss: "https://itforum.com.br/feed/" },
  { outlet: "TechCrunch",       editoria: "Tech",       rss: "https://techcrunch.com/feed/" },
  { outlet: "Crunchbase News",  editoria: "Funding",    rss: "https://news.crunchbase.com/feed/" },
  { outlet: "VentureBeat",      editoria: "AI",         rss: "https://venturebeat.com/feed/" },
  { outlet: "Sifted",           editoria: "Startups",   rss: "https://sifted.eu/feed" },
];

// Quantas matérias novas reescrever por execução (controla custo/tempo)
const MAX_POR_RODADA = 6;
// Quantos itens olhar por feed
const ITENS_POR_FEED = 4;

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
function parseFeed(xml) {
  const itens = [];
  const blocos = xml.split(/<item[ >]/i).slice(1);
  for (const raw of blocos) {
    const bloco = raw.split(/<\/item>/i)[0];
    const titulo = tirarHTML(pegarTag(bloco, "title"));
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

// ── Reescrita via API Anthropic ──
async function reescrever(item, fonte, apiKey) {
  const base = item.resumo && item.resumo.length > 40 ? item.resumo : item.titulo;
  const prompt = `Você é redator do StartupDrops, portal brasileiro de notícias do ecossistema de startups. Recebeu a notícia abaixo, publicada originalmente pelo veículo "${fonte.outlet}". Reescreva com texto 100% próprio, no tom editorial do StartupDrops, para publicar no portal.

REGRAS OBRIGATÓRIAS:
- Reescreva do zero, com suas próprias palavras e estrutura. Não copie frases do original nem parafraseie linha a linha.
- Mantenha TODOS os fatos, nomes, empresas e números presentes no original. NÃO invente nenhum dado, número, valor ou citação que não esteja no texto. Se algo não estiver claro, não afirme.
- Tom jornalístico, direto, escaneável. Português do Brasil.
- NÃO use travessões (—). Use vírgula, ponto ou parênteses.
- Título curto e forte (máx ~12 palavras). Linha fina de 1 a 2 frases. Corpo em 3 a 5 parágrafos.

Editoria sugerida: ${fonte.editoria}

TÍTULO ORIGINAL: ${item.titulo}
RESUMO/CONTEÚDO ORIGINAL:
"""
${base}
"""

Responda APENAS com JSON válido, sem markdown nem crases, neste formato exato:
{"titulo":"...","linha_fina":"...","corpo":["parágrafo 1","parágrafo 2"],"editoria":"Funding|Startups|Economia|Tech|Unicórnios|AI"}`;

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
  if (!resp.ok) throw new Error("Anthropic status " + resp.status);
  const data = await resp.json();
  let text = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("").trim();
  text = text.replace(/^```json/i, "").replace(/^```/, "").replace(/```$/, "").trim();
  const a = text.indexOf("{"), b = text.lastIndexOf("}");
  if (a >= 0 && b >= 0) text = text.slice(a, b + 1);
  return JSON.parse(text);
}

// ── Handler agendado ──
export default async (req) => {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return new Response("Falta ANTHROPIC_API_KEY nas variáveis de ambiente.", { status: 500 });
  }

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
        if (!jaPublicados.has(it.link)) candidatos.push({ item: it, fonte });
      }
    } catch (e) {
      console.log("Falha no feed", fonte.outlet, e.message);
    }
  }

  // 2) Reescrever até o limite da rodada
  const aReescrever = candidatos.slice(0, MAX_POR_RODADA);
  let publicadas = 0;

  for (const c of aReescrever) {
    try {
      const art = await reescrever(c.item, c.fonte, apiKey);
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
      console.log("Falha ao reescrever", c.item.titulo, e.message);
    }
  }

  // 3) Manter índice enxuto (últimas 200)
  indice = indice.slice(0, 200);
  await store.setJSON("indice", indice);

  return new Response(
    JSON.stringify({ ok: true, candidatos: candidatos.length, publicadas, total: indice.length }),
    { headers: { "Content-Type": "application/json" } }
  );
};

// 3x ao dia em horário de Brasília (UTC-3): 08h, 14h e 20h BRT
// = 11:00, 17:00 e 23:00 UTC
export const config = {
  schedule: "0 11,17,23 * * *",
};
