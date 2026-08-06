import { getStore } from "@netlify/blobs";

// Retorna o índice de matérias publicadas (para a home)
// ou uma matéria completa se ?id=... for passado.
export default async (req) => {
  const store = getStore("materias");
  const url = new URL(req.url);
  const id = url.searchParams.get("id");

  const headers = {
    "Content-Type": "application/json",
    "Cache-Control": "public, max-age=300",
    "Access-Control-Allow-Origin": "*",
  };

  try {
    if (id) {
      const art = await store.get("artigo_" + id, { type: "json" });
      if (!art) return new Response(JSON.stringify({ erro: "não encontrada" }), { status: 404, headers });
      return new Response(JSON.stringify(art), { headers });
    }
    let indice = await store.get("indice", { type: "json" });
    if (!Array.isArray(indice)) indice = [];
    return new Response(JSON.stringify({ materias: indice }), { headers });
  } catch (e) {
    return new Response(JSON.stringify({ materias: [], erro: e.message }), { headers });
  }
};
