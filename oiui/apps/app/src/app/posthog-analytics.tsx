"use client";

import { useEffect } from "react";
import posthog from "posthog-js";

// Page analytics for the hosted demo only. Nothing loads unless
// NEXT_PUBLIC_POSTHOG_KEY is set at build time, so clones of this template
// don't report page views. See docs/telemetry.md.
export function PostHogAnalytics() {
  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    if (!key || posthog.__loaded) return;
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com",
      defaults: "2025-05-24",
      person_profiles: "identified_only",
      // Visitors type provider API keys into this app; never record sessions.
      disable_session_recording: true,
    });
    posthog.register({ app: "open-intelligent-ui" });
  }, []);
  return null;
}
