import { NextResponse } from "next/server";
import { networkInterfaces } from "os";

/** Returns the machine's LAN IPv4 address so phones on the same network can connect. */
export async function GET() {
  const nets = networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name] ?? []) {
      if (!net.internal && net.family === "IPv4") {
        return NextResponse.json({ ip: net.address });
      }
    }
  }
  return NextResponse.json({ ip: null });
}
