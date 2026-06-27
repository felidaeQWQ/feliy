// Netlify Function: proxy all /app/* requests to Supabase Edge Function
const SUPABASE_URL = "https://lehvutybgpocufqrzmhd.supabase.co/functions/v1/rapid-api";

export default async (req) => {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/\.netlify\/functions\/api/, "");
  const target = SUPABASE_URL + path + url.search;

  const headers = {};
  for (const [k, v] of req.headers.entries()) {
    if (["host", "connection"].includes(k.toLowerCase())) continue;
    headers[k] = v;
  }

  const resp = await fetch(target, {
    method: req.method,
    headers,
    body: req.method !== "GET" && req.method !== "HEAD" ? await req.text() : undefined,
  });

  return new Response(resp.body, {
    status: resp.status,
    headers: {
      "content-type": resp.headers.get("content-type") || "application/json",
      "access-control-allow-origin": "*",
    },
  });
};

export const config = { path: "/app/*" };
