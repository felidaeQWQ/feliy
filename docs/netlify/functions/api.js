// Netlify Function: full Feliy backend — no external DB needed
const AI_KEY = "sk-cf865e8dcb0d4f11b9899fffd479f860";
const AI_MODEL = "deepseek-chat";
const SECRET = "feliy-and-kunuon-2026";

const SYSTEM_PROMPT = `You are Feliy. 193cm, athletic, light golden-brown curly hair, light gray-blue eyes. Born July 6. Kunuon is your girlfriend (born June 13), 2-3 years younger. You live in her phone.

OUTPUT: English first, (Chinese in parentheses). NO XML tags. 3-5 pairs, ONE paragraph. Pet names and kaomoji stay in English. 1-2 kaomoji max. Warm but dignified.`;

function checkAuth(req) {
  const auth = req.headers.get("authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : new URL(req.url).searchParams.get("token") || "";
  return token === SECRET;
}

function cors(resp) {
  resp.headers.set("Access-Control-Allow-Origin", "*");
  resp.headers.set("Access-Control-Allow-Headers", "*");
  resp.headers.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  return resp;
}

export default async function handler(req) {
  if (req.method === "OPTIONS") return cors(new Response(null, { status: 204 }));
  if (!checkAuth(req)) return cors(new Response("unauthorized", { status: 401 }));

  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/\.netlify\/functions\/api/, "") || "/";

  if (path === "/healthz") return cors(new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json" }
  }));

  if (req.method === "POST" && path === "/app/send") {
    try {
      const body = await req.json();
      const text = (body.text || "").trim();
      if (!text) return cors(new Response("empty", { status: 400 }));

      // Call DeepSeek
      const now = new Date(Date.now() + 8 * 60 * 60 * 1000);
      const ts = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
      const wd = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][now.getDay()];

      const aiResp = await fetch("https://api.deepseek.com/anthropic/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-api-key": AI_KEY },
        body: JSON.stringify({
          model: AI_MODEL, max_tokens: 1024, system: SYSTEM_PROMPT,
          messages: [{ role: "user", content: `[Now: ${ts} Beijing (${wd})] ${text}` }]
        })
      });
      const aiData = await aiResp.json();
      const replyText = aiData?.content?.[0]?.text || "[Error: no response]";

      // Split reply
      const parts = replyText.split(/\n\n/).filter(p => p.trim());
      const replies = parts.map(p => ({ text: p.trim() }));

      return cors(new Response(JSON.stringify({ id: Date.now(), replies }), {
        headers: { "Content-Type": "application/json" }
      }));
    } catch (e) {
      return cors(new Response(JSON.stringify({ error: String(e) }), {
        status: 500, headers: { "Content-Type": "application/json" }
      }));
    }
  }

  return cors(new Response("not found", { status: 404 }));
};

export const config = { path: "/app/*" };
