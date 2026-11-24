# Telemetry

Open Intelligent UI reports anonymous usage so CopilotKit can see how many people run the template. It uses the same CopilotKit telemetry ingest as the CopilotKit runtime and OpenDots. You can turn it off with one environment variable.

## Turning it off

Set either variable on the frontend (`apps/app`) and restart:

```bash
DO_NOT_TRACK=1
# or
COPILOTKIT_TELEMETRY_DISABLED=1
```

`COPILOTKIT_TELEMETRY_SAMPLE_RATE=0` also turns it off. Opting out deletes the stored installation id.

## What is sent

The frontend server sends at most two events per installation, each once:

| Event                           | When                                                                 | Properties                       |
| ------------------------------- | -------------------------------------------------------------------- | -------------------------------- |
| `oss.runtime.setup_step_viewed` | The app's UI first reaches the runtime (`/api/copilotkit`)           | `kind=step_viewed`, `step=ready` |
| `oss.runtime.setup_activated`   | The agent's first run finishes with an assistant answer and no error | `kind=activated`                 |

Every event carries this metadata and nothing else:

- `accessibility_title`: `Open Intelligent UI`
- `openintelligentui_distribution`: `self_hosted` by default, `hosted_demo` for CopilotKit's hosted demo, or `development`
- `openintelligentui_version`: the app's package version
- `runtime_env`: `node`
- `server_platform` (`macos`, `windows`, `linux`, `other`) and `server_arch` (`aarch64`, `x86_64`, `other`)
- `installation_id`: a random UUID created on first run

No prompts, answers, API keys, URLs, file paths, model names, emails, or error details are sent. Activation is detected by reading the event types of the first run's response stream; no message text is kept.

The installation id and two delivered/not-delivered flags are stored in `apps/app/.open-intelligent-ui/telemetry.json` (ignored by git). Set `OIUI_TELEMETRY_STATE_PATH` to store it elsewhere. If `CPK_TELEMETRY_ID` is set (by the CopilotKit CLI), it is used as the telemetry identity; the installation id stays separate.

A failed delivery is retried on a later request. Delivery never blocks or fails a chat request.

## Runtime telemetry

The CopilotKit runtime already sends its own sampled, anonymous telemetry (see the CopilotKit docs). This app adds the same metadata (`template`, `openintelligentui_distribution`, `openintelligentui_version`, `installation_id`) to those events so they can be told apart from other CopilotKit apps. The opt-out variables above turn both off.

## Hosted demo analytics

The hosted demo loads PostHog page analytics in the browser. It only loads when `NEXT_PUBLIC_POSTHOG_KEY` is set at build time, so your own deployments and local runs don't load it unless you add a key. Session recording is always off, because visitors can type API keys into the app. `NEXT_PUBLIC_POSTHOG_HOST` defaults to `https://eu.i.posthog.com`.

## Hosted demo setup

On the Render frontend service (see `render.yaml`):

- `OIUI_DISTRIBUTION=hosted_demo`, so the demo's runs are not counted as self-hosted installs.
- `NEXT_PUBLIC_POSTHOG_KEY`: the CopilotKit PostHog project key. It must be present when the app is built.

## Checking delivery

Unit tests intercept the transport and never send events:

```bash
pnpm --filter @repo/app exec vitest run src/lib/__tests__/launch-telemetry.test.ts src/app/__tests__/posthog-analytics.test.tsx
```

To check live delivery, run the app with `OIUI_DISTRIBUTION=development`, open it and send a prompt, then look for the two events with that distribution in PostHog. HTTP acceptance by the ingest alone does not prove the events reached PostHog.
