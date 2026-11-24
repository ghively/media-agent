import { NextRequest, NextResponse } from "next/server";
import { getSession, setSession } from "./store";

/** GET — poll session status (desktop polls this) */
export async function GET(req: NextRequest) {
  const sessionId = req.nextUrl.searchParams.get("sessionId");
  if (!sessionId) return NextResponse.json({ error: "missing sessionId" }, { status: 400 });

  const session = getSession(sessionId);
  if (!session) return NextResponse.json({ status: "waiting" });

  // Consume the prompt on first read so duplicate polls don't re-trigger
  if (session.status === "picked" && session.prompt) {
    const prompt = session.prompt;
    setSession(sessionId, { status: "picked" });
    return NextResponse.json({ status: "picked", prompt });
  }

  return NextResponse.json(session);
}

/** PUT — mark session as scanned (mobile calls this on page load) */
export async function PUT(req: NextRequest) {
  const { sessionId } = await req.json();
  if (!sessionId) return NextResponse.json({ error: "missing sessionId" }, { status: 400 });

  const existing = getSession(sessionId);
  if (!existing || existing.status === "waiting") {
    setSession(sessionId, { status: "scanned" });
  }

  return NextResponse.json({ ok: true });
}

/** POST — submit picked prompt (mobile calls this when user picks an option) */
export async function POST(req: NextRequest) {
  const { sessionId, prompt } = await req.json();
  if (!sessionId || !prompt) {
    return NextResponse.json({ error: "missing sessionId or prompt" }, { status: 400 });
  }

  setSession(sessionId, { status: "picked", prompt });
  return NextResponse.json({ ok: true });
}
