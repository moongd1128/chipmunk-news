// 텔레그램 버튼 문지기 (Supabase Edge Function)
//
// 텔레그램 버튼을 누르면 이 함수가 바로 받는다 (텔레그램 webhook).
//   1) 눌린 버튼을 비공개 버킷 private/queue/ 에 저장한다 → 칩다람 봇(GitHub·PC)이 꺼내서 처리
//   2) 봇이 깨어 있지 않으면: 버튼에 바로 "⏳ 받았어요"라고 답하고, GitHub 버튼 처리를 바로 깨운다
//      (깨어 있으면 봇이 2~3초 안에 직접 답하니까 아무것도 안 한다)
//
// 필요한 비밀값 (Supabase → Edge Functions → Secrets):
//   TELEGRAM_BOT_TOKEN       텔레그램 봇 토큰
//   TELEGRAM_WEBHOOK_SECRET  텔레그램이 보낸 요청인지 확인하는 비밀 글자 (아무나 이 주소로 보내지 못하게)
//   GH_DISPATCH_TOKEN        GitHub 토큰 (moongd1128/chipmunk-news의 Actions 쓰기 권한만)
//   (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY는 Supabase가 자동으로 넣어 줌)

const TG = Deno.env.get("TELEGRAM_BOT_TOKEN") ?? "";
const SECRET = Deno.env.get("TELEGRAM_WEBHOOK_SECRET") ?? "";
const GH = Deno.env.get("GH_DISPATCH_TOKEN") ?? "";
const SB_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const REPO = "moongd1128/chipmunk-news";
const AWAKE_SECONDS = 60; // 봇이 이 시간 안에 '깨어 있음' 표시를 남겼으면 깨어 있는 걸로 본다

const sb = (path: string, init: RequestInit = {}) =>
  fetch(`${SB_URL}/storage/v1/object/${path}`, {
    ...init,
    headers: { apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}`, ...(init.headers ?? {}) },
  });

async function botAwake(): Promise<boolean> {
  const r = await sb("private/queue/_awake.json");
  if (!r.ok) return false;
  const { at } = await r.json();
  return Date.now() / 1000 - at < AWAKE_SECONDS;
}

Deno.serve(async (req) => {
  if (req.method !== "POST" || req.headers.get("x-telegram-bot-api-secret-token") !== SECRET) {
    return new Response("no", { status: 401 });
  }
  const update = await req.json();

  // 1) 대기열에 저장 (이름 순서 = 누른 순서)
  const name = String(update.update_id).padStart(14, "0");
  await sb(`private/queue/${name}.json`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-upsert": "true" },
    body: JSON.stringify(update),
  });

  // 2) 봇이 자고 있으면 바로 답하고 깨운다
  if (!(await botAwake())) {
    const cq = update.callback_query;
    if (cq) {
      await fetch(`https://api.telegram.org/bot${TG}/answerCallbackQuery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_query_id: cq.id, text: "⏳ 받았어요! 1분쯤 뒤에 바뀌어요" }),
      });
    }
    await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/buttons.yml/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${GH}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { live: "false" } }),
    });
  }
  // 텔레그램에는 항상 '잘 받았다'고 답한다 (아니면 같은 걸 계속 다시 보냄)
  return new Response("ok");
});
