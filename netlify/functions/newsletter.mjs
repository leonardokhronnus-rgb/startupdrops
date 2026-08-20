import { getStore } from "@netlify/blobs";
import { json, options, readJsonBody, requireAdmin } from "./_shared.mjs";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

export default async (req) => {
  if (req.method === "OPTIONS") return options();

  const store = getStore("newsletter");

  if (req.method === "GET") {
    if (!requireAdmin(req)) return json({ ok: false, error: "unauthorized" }, { status: 401 });
    const subscribers = (await store.get("subscribers", { type: "json" })) || [];
    const leads = (await store.get("leads", { type: "json" })) || [];
    return json({ ok: true, subscribers, leads });
  }

  if (req.method === "DELETE") {
    if (!requireAdmin(req)) return json({ ok: false, error: "unauthorized" }, { status: 401 });
    const body = await readJsonBody(req);
    const email = normalizeEmail(body.email);
    if (!EMAIL_RE.test(email)) {
      return json({ ok: false, error: "invalid_email" }, { status: 400 });
    }
    const subscribers = (await store.get("subscribers", { type: "json" })) || [];
    const nextSubscribers = subscribers.filter((item) => item.email !== email);
    await store.setJSON("subscribers", nextSubscribers);
    return json({ ok: true, removed: subscribers.length - nextSubscribers.length });
  }

  if (req.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, { status: 405 });
  }

  const body = await readJsonBody(req);
  const email = normalizeEmail(body.email);
  if (!EMAIL_RE.test(email)) {
    return json({ ok: false, error: "invalid_email" }, { status: 400 });
  }

  const now = new Date().toISOString();
  const record = {
    email,
    name: String(body.name || "").trim(),
    source: String(body.source || "site").slice(0, 80),
    page: String(body.page || "").slice(0, 300),
    userAgent: req.headers.get("user-agent") || "",
    createdAt: now,
  };

  const subscribers = (await store.get("subscribers", { type: "json" })) || [];
  const existing = subscribers.find((item) => item.email === email);
  if (existing) {
    existing.updatedAt = now;
    existing.source = record.source;
    existing.page = record.page;
  } else {
    subscribers.unshift(record);
  }

  await store.setJSON("subscribers", subscribers.slice(0, 5000));
  return json({ ok: true, alreadyExists: Boolean(existing) });
};
