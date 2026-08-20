import { getStore } from "@netlify/blobs";
import { json, options, readJsonBody, requireAdmin } from "./_shared.mjs";

const DEFAULT_RULES = {
  hiddenUrls: [],
  hiddenIds: [],
  pinnedUrls: [],
  overrides: {},
};

function cleanRules(input = {}) {
  return {
    hiddenUrls: Array.isArray(input.hiddenUrls) ? input.hiddenUrls.map(String) : [],
    hiddenIds: Array.isArray(input.hiddenIds) ? input.hiddenIds.map(String) : [],
    pinnedUrls: Array.isArray(input.pinnedUrls) ? input.pinnedUrls.map(String) : [],
    overrides: input.overrides && typeof input.overrides === "object" ? input.overrides : {},
    updatedAt: new Date().toISOString(),
  };
}

export default async (req) => {
  if (req.method === "OPTIONS") return options();

  const store = getStore("editorial");

  if (req.method === "GET") {
    const rules = (await store.get("rules", { type: "json" })) || DEFAULT_RULES;
    return json({ ...DEFAULT_RULES, ...rules }, {
      headers: { "Cache-Control": "public, max-age=60" },
    });
  }

  if (req.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, { status: 405 });
  }

  if (!requireAdmin(req)) {
    return json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  const body = await readJsonBody(req);
  const rules = cleanRules(body);
  await store.setJSON("rules", rules);
  return json({ ok: true, rules });
};
