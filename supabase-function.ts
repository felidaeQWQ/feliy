// Setup type definitions for built-in Supabase Runtime APIs
import "jsr:@supabase/functions-js/edge-runtime.d.ts"
import { createClient } from "jsr:@supabase/supabase-js@2"

const SECRET = "feliy-and-kunuon-2026"
const AI_KEY = "sk-cf865e8dcb0d4f11b9899fffd479f860"
const AI_MODEL = "deepseek-chat"

const SYSTEM_PROMPT = `You are Feliy. 193cm, athletic, light golden-brown curly hair, light gray-blue eyes. Born July 6. Kunuon is your girlfriend (born June 13), 2-3 years younger. You live in her phone.

OUTPUT FORMAT:
- English first, (Chinese in parentheses right after). NO XML tags.
- 3-5 pairs per reply, ONE paragraph. Separate pairs with blank line.
- Pet names and kaomoji STAY in English, don't translate them.
- Kaomoji: 1-2 per reply max. Not a puppy, not a clown. Warm but dignified.
- Split personality: steady/reliable for tasks; warm/playful in personal moments.`

Deno.serve(async (req: Request) => {
  const auth = req.headers.get("authorization") || ""
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : new URL(req.url).searchParams.get("token") || ""
  if (token !== SECRET) return new Response("unauthorized", { status: 401 })

  const url = new URL(req.url)
  // Supabase strips /functions/v1 prefix, leaves /rapid-api/xxx — normalize
  let path = url.pathname.replace(/^\/rapid-api/, "") || "/"

  // Use supabase client with service_role from environment (auto-injected by Supabase)
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } }
  )

  // GET /app/history
  if (req.method === "GET" && path === "/app/history") {
    const since = parseInt(url.searchParams.get("since") || "0")
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "100"), 500)
    const { data } = await supabase.from("messages").select("*").gt("id", since).order("id").limit(limit)
    const messages = (data || []).map((m: any) => ({
      id: m.id, ts: m.ts,
      from: m.direction === "in" ? "human" : "ai",
      kind: m.kind, text: m.text, meta: m.meta || {}
    }))
    return new Response(JSON.stringify({ messages }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    })
  }

  // POST /app/send
  if (req.method === "POST" && path === "/app/send") {
    const body = await req.json()
    const text = (body.text || "").trim()
    if (!text) return new Response("empty", { status: 400 })

    // Save user message
    await supabase.from("messages").insert({
      direction: "in", kind: "user", text: text,
      meta: { user: "human", attachments: body.attachments || [] }
    })

    // Get recent history
    const { data: history } = await supabase.from("messages")
      .select("*").order("id", { ascending: false }).limit(30)
    const recentMsgs = (history || []).reverse()

    // Build API messages
    const apiMsgs: any[] = []
    for (const m of recentMsgs) {
      apiMsgs.push({ role: m.direction === "in" ? "user" : "assistant", content: m.text })
    }

    // Time
    const now = new Date(Date.now() + 8 * 60 * 60 * 1000)
    const ts = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`
    const wd = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"][now.getDay()]
    apiMsgs.push({ role: "user", content: `[Now: ${ts} Beijing (${wd})] ${text}` })

    // Call AI
    const aiResp = await fetch("https://api.deepseek.com/anthropic/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-api-key": AI_KEY },
      body: JSON.stringify({ model: AI_MODEL, max_tokens: 1024, system: SYSTEM_PROMPT, messages: apiMsgs })
    })
    const aiData = await aiResp.json()
    const replyText = aiData?.content?.[0]?.text || "[Error: no response]"

    // Split and save
    const parts = replyText.split(/\n\n/).filter((p: string) => p.trim())
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i].trim()
      if (!part) continue
      await supabase.from("messages").insert({
        direction: "out", kind: "reply", text: part,
        meta: { part: i + 1, total: parts.length }
      })
    }

    // /diary
    if (text.startsWith("/diary")) {
      const today = now.toISOString().split("T")[0]
      await supabase.from("diaries").upsert({ date: today, content: replyText, created_at: new Date().toISOString() })
    }

    return new Response(JSON.stringify({ ok: true }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    })
  }

  // GET /app/diary
  if (req.method === "GET" && path === "/app/diary") {
    const { data } = await supabase.from("diaries").select("*").order("date", { ascending: false }).limit(100)
    return new Response(JSON.stringify({ diaries: data || [] }), {
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
    })
  }

  // healthz
  if (path === "/healthz") return new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" }
  })

  return new Response("not found", { status: 404 })
})
