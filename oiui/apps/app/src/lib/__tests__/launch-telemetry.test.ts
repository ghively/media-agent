// @vitest-environment node
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LaunchTelemetry, observeRunResult, runtimeMethod, telemetryDistribution } from "../launch-telemetry";

type SentBody = {
  event: string;
  properties: Record<string, unknown>;
  package: Record<string, unknown>;
  global_properties: Record<string, unknown>;
};
type Sent = { identity: string; body: SentBody };

let dir: string;
let statePath: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "oiui-telemetry-"));
  statePath = join(dir, "state", "telemetry.json");
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function recorder() {
  const sent: Sent[] = [];
  const send = vi.fn(async (identity: string, body: Record<string, unknown>) => {
    sent.push({ identity, body: body as SentBody });
  });
  return { sent, send };
}

describe("LaunchTelemetry", () => {
  it("sends the opened event once per installation, with closed metadata", async () => {
    const { sent, send } = recorder();
    const telemetry = new LaunchTelemetry({ env: {}, statePath, send });

    await telemetry.recordOpened();
    await telemetry.recordOpened();

    expect(sent).toHaveLength(1);
    const [{ identity, body }] = sent;
    expect(body.event).toBe("oss.runtime.setup_step_viewed");
    expect(body.properties).toEqual({ kind: "step_viewed", step: "ready" });
    expect(body.package).toEqual({ name: "open-intelligent-ui", version: expect.any(String) });
    expect(body.global_properties).toMatchObject({
      accessibility_title: "Open Intelligent UI",
      openintelligentui_distribution: "self_hosted",
      runtime_env: "node",
      sampleRate: 1,
      installation_id: identity,
    });
    expect(Object.keys(body.global_properties).sort()).toEqual(
      [
        "accessibility_title",
        "installation_id",
        "openintelligentui_distribution",
        "openintelligentui_version",
        "runtime_env",
        "sampleRate",
        "sampleRateAdjustmentFactor",
        "sampleWeight",
        "server_arch",
        "server_platform",
      ].sort(),
    );
  });

  it("keeps the installation id across restarts", async () => {
    const first = recorder();
    await new LaunchTelemetry({ env: {}, statePath, send: first.send }).recordOpened();
    const second = recorder();
    const restarted = new LaunchTelemetry({ env: {}, statePath, send: second.send });
    await restarted.recordOpened();
    await restarted.recordActivated();

    expect(second.sent).toHaveLength(1);
    expect(second.sent[0].body.event).toBe("oss.runtime.setup_activated");
    expect(second.sent[0].identity).toBe(first.sent[0].identity);
  });

  it("sends the activated event once", async () => {
    const { sent, send } = recorder();
    const telemetry = new LaunchTelemetry({ env: {}, statePath, send });

    await Promise.all([telemetry.recordActivated(), telemetry.recordActivated()]);
    await telemetry.recordActivated();

    expect(sent.map((s) => s.body.event)).toEqual(["oss.runtime.setup_activated"]);
    expect(sent[0].body.properties).toEqual({ kind: "activated" });
  });

  it("retries after a failed delivery and never throws", async () => {
    const send = vi
      .fn<(identity: string, body: Record<string, unknown>) => Promise<void>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);
    const telemetry = new LaunchTelemetry({ env: {}, statePath, send, report: () => {} });

    await expect(telemetry.recordOpened()).resolves.toBeUndefined();
    await telemetry.recordOpened();
    await telemetry.recordOpened();

    expect(send).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["DO_NOT_TRACK", "1"],
    ["DO_NOT_TRACK", "true"],
    ["COPILOTKIT_TELEMETRY_DISABLED", "1"],
    ["COPILOTKIT_TELEMETRY_DISABLED", "true"],
    ["COPILOTKIT_TELEMETRY_SAMPLE_RATE", "0"],
  ])("sends nothing and stores nothing when %s=%s", async (key, value) => {
    const { send } = recorder();
    const telemetry = new LaunchTelemetry({ env: { [key]: value }, statePath, send });

    await telemetry.recordOpened();
    await telemetry.recordActivated();

    expect(send).not.toHaveBeenCalled();
    expect(existsSync(statePath)).toBe(false);
    expect(telemetry.runtimeProperties()).toBeUndefined();
  });

  it("deletes stored state after opting out", async () => {
    await new LaunchTelemetry({ env: {}, statePath, send: recorder().send }).recordOpened();
    expect(existsSync(statePath)).toBe(true);

    new LaunchTelemetry({ env: { DO_NOT_TRACK: "1" }, statePath, send: recorder().send });

    expect(existsSync(statePath)).toBe(false);
  });

  it("uses CPK_TELEMETRY_ID as the identity but keeps the installation id separate", async () => {
    const { sent, send } = recorder();
    const telemetry = new LaunchTelemetry({ env: { CPK_TELEMETRY_ID: "cli-account-1" }, statePath, send });

    await telemetry.recordOpened();

    expect(sent[0].identity).toBe("cli-account-1");
    expect(sent[0].body.global_properties.installation_id).not.toBe("cli-account-1");
  });

  it("stores only the installation id and delivery flags", async () => {
    await new LaunchTelemetry({ env: {}, statePath, send: recorder().send }).recordOpened();

    const saved = JSON.parse(readFileSync(statePath, "utf8"));
    expect(Object.keys(saved).sort()).toEqual(["installationId", "sent"]);
    expect(saved.sent).toEqual({ opened: true });
  });

  it("tags the runtime's own telemetry with the same metadata", () => {
    const telemetry = new LaunchTelemetry({ env: { OIUI_DISTRIBUTION: "hosted_demo" }, statePath, send: recorder().send });

    expect(telemetry.runtimeProperties()).toMatchObject({
      template: "open-intelligent-ui",
      openintelligentui_distribution: "hosted_demo",
      installation_id: expect.any(String),
    });
  });

  it("still works when the state file can't be written", async () => {
    const { sent, send } = recorder();
    const blocked = join(dir, "file");
    await import("node:fs").then((fs) => fs.writeFileSync(blocked, "not a directory"));
    const telemetry = new LaunchTelemetry({ env: {}, statePath: join(blocked, "telemetry.json"), send, report: () => {} });

    await expect(telemetry.recordOpened()).resolves.toBeUndefined();
    expect(sent).toHaveLength(1);
  });
});

describe("telemetryDistribution", () => {
  it("accepts the known values and defaults to self_hosted", () => {
    expect(telemetryDistribution({ OIUI_DISTRIBUTION: "hosted_demo" })).toBe("hosted_demo");
    expect(telemetryDistribution({ OIUI_DISTRIBUTION: "development" })).toBe("development");
    expect(telemetryDistribution({ OIUI_DISTRIBUTION: "anything else" })).toBe("self_hosted");
    expect(telemetryDistribution({})).toBe("self_hosted");
  });
});

describe("runtimeMethod", () => {
  it("reads the method without consuming the request body", async () => {
    const req = new Request("http://localhost/api/copilotkit", {
      method: "POST",
      body: JSON.stringify({ method: "agent/run", params: { agentId: "default" } }),
    });

    await expect(runtimeMethod(req)).resolves.toBe("agent/run");
    await expect(req.json()).resolves.toMatchObject({ method: "agent/run" });
  });

  it("returns undefined for bodies that aren't JSON", async () => {
    const req = new Request("http://localhost/api/copilotkit", { method: "POST", body: "not json" });
    await expect(runtimeMethod(req)).resolves.toBeUndefined();
  });
});

describe("observeRunResult", () => {
  const encoder = new TextEncoder();
  function sse(...events: Record<string, unknown>[]) {
    return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  }
  async function run(chunks: string[]) {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((c) => controller.enqueue(encoder.encode(c)));
        controller.close();
      },
    });
    return observeRunResult(stream);
  }

  it("reports success when an assistant answer streams and the run finishes", async () => {
    const body = sse(
      { type: "RUN_STARTED" },
      { type: "TEXT_MESSAGE_START", role: "assistant", messageId: "m1" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "Hello" },
      { type: "RUN_FINISHED" },
    );
    // Split mid-token to prove chunk boundaries don't matter.
    await expect(run([body.slice(0, 57), body.slice(57)])).resolves.toBe(true);
  });

  it("accepts streams of text chunks as well as bytes", async () => {
    const stream = new ReadableStream<string>({
      start(controller) {
        controller.enqueue(sse({ type: "TEXT_MESSAGE_CONTENT", delta: "Hi" }));
        controller.enqueue(sse({ type: "RUN_FINISHED" }));
        controller.close();
      },
    });
    await expect(observeRunResult(stream)).resolves.toBe(true);
  });

  it("reports failure on a run error", async () => {
    await expect(
      run([sse({ type: "TEXT_MESSAGE_CONTENT", delta: "Hi" }, { type: "RUN_ERROR" }, { type: "RUN_FINISHED" })]),
    ).resolves.toBe(false);
  });

  it("reports failure when the run finishes without any answer text", async () => {
    await expect(run([sse({ type: "RUN_STARTED" }, { type: "RUN_FINISHED" })])).resolves.toBe(false);
  });
});
