import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const posthog = vi.hoisted(() => ({ __loaded: false, init: vi.fn(), register: vi.fn() }));
vi.mock("posthog-js", () => ({ default: posthog }));

import { PostHogAnalytics } from "../posthog-analytics";

afterEach(() => {
  vi.unstubAllEnvs();
  posthog.init.mockReset();
  posthog.register.mockReset();
  posthog.__loaded = false;
});

describe("PostHogAnalytics", () => {
  it("loads nothing without a PostHog key", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "");
    render(<PostHogAnalytics />);
    expect(posthog.init).not.toHaveBeenCalled();
  });

  it("starts PostHog with session recording off when a key is set", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "phc_test");
    render(<PostHogAnalytics />);
    expect(posthog.init).toHaveBeenCalledWith(
      "phc_test",
      expect.objectContaining({ api_host: "https://eu.i.posthog.com", disable_session_recording: true }),
    );
    expect(posthog.register).toHaveBeenCalledWith({ app: "open-intelligent-ui" });
  });

  it("does not start twice", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "phc_test");
    posthog.__loaded = true;
    render(<PostHogAnalytics />);
    expect(posthog.init).not.toHaveBeenCalled();
  });
});
