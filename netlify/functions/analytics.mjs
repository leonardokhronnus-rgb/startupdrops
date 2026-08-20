import { getStore } from "@netlify/blobs";
import { json, options, readJsonBody, requireAdmin } from "./_shared.mjs";

const ALLOWED_EVENTS = new Set([
  "page_view",
  "article_open",
  "original_click",
  "branded_click",
  "newsletter_submit",
  "filter_click",
  "search",
]);

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

export default async (req) => {
  if (req.method === "OPTIONS") return options();

  const store = getStore("analytics");

  if (req.method === "GET") {
    if (!requireAdmin(req)) return json({ ok: false, error: "unauthorized" }, { status: 401 });
    const url = new URL(req.url);
    const day = url.searchParams.get("day") || todayKey();
    const summary = (await store.get(`summary_${day}`, { type: "json" })) || {};
    const events = (await store.get(`events_${day}`, { type: "json" })) || [];
    return json({ ok: true, day, summary, events });
  }

  if (req.method !== "POST") {
    return json({ ok: false, error: "method_not_allowed" }, { status: 405 });
  }

  const body = await readJsonBody(req);
  const event = String(body.event || "").trim();
  if (!ALLOWED_EVENTS.has(event)) {
    return json({ ok: false, error: "invalid_event" }, { status: 400 });
  }

  const day = todayKey();
  const payload = {
    event,
    path: String(body.path || "").slice(0, 300),
    label: String(body.label || "").slice(0, 220),
    value: String(body.value || "").slice(0, 220),
    ts: new Date().toISOString(),
    referrer: String(body.referrer || "").slice(0, 300),
    userAgent: req.headers.get("user-agent") || "",
  };

  const eventsKey = `events_${day}`;
  const summaryKey = `summary_${day}`;
  const events = (await store.get(eventsKey, { type: "json" })) || [];
  const summary = (await store.get(summaryKey, { type: "json" })) || {};

  events.unshift(payload);
  summary[event] = (summary[event] || 0) + 1;
  if (payload.label) {
    const labelKey = `${event}:${payload.label}`;
    summary[labelKey] = (summary[labelKey] || 0) + 1;
  }

  await store.setJSON(eventsKey, events.slice(0, 2000));
  await store.setJSON(summaryKey, summary);

  return json({ ok: true });
};
