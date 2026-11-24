"use client";

import { useSyncExternalStore, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { useAgent } from "@copilotkit/react-core/v2";

/**
 * Manages the DOM element used as the portal container for the template chip.
 * Uses a subscribe/getSnapshot pattern compatible with useSyncExternalStore
 * to avoid setState-in-effect and ref-during-render lint violations.
 *
 * COUPLING NOTE: This depends on CopilotKit's internal DOM structure —
 * specifically that `[data-testid="copilot-chat-textarea"]` exists and sits inside
 * a parent column div. If CopilotKit changes this structure, the chip falls back
 * to rendering inline instead of portaling into the textarea.
 */
let chipContainer: HTMLElement | null = null;
const listeners = new Set<() => void>();

function getChipContainer() {
  return chipContainer;
}

function subscribeChipContainer(cb: () => void) {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

function ensureChipContainer(active: boolean) {
  if (!active) {
    if (chipContainer) {
      chipContainer.remove();
      chipContainer = null;
      listeners.forEach((cb) => cb());
    }
    return;
  }

  if (chipContainer) return;

  const textarea = document.querySelector<HTMLElement>(
    '[data-testid="copilot-chat-textarea"]'
  );
  const textareaColumn = textarea?.parentElement;
  if (!textareaColumn) return;

  let el = textareaColumn.querySelector<HTMLElement>("[data-template-chip]");
  if (!el) {
    el = document.createElement("div");
    el.setAttribute("data-template-chip", "");
    el.style.cssText = "display: flex; padding: 4px 0 0 0;";
    textareaColumn.insertBefore(el, textarea);
  }
  chipContainer = el;
  listeners.forEach((cb) => cb());
}

export function TemplateChip() {
  const { agent } = useAgent();
  const pending = agent.state?.pending_template as
    | { id: string; name: string }
    | null
    | undefined;

  const container = useSyncExternalStore(subscribeChipContainer, getChipContainer, () => null);

  useEffect(() => {
    ensureChipContainer(!!pending?.name);
  }, [pending?.name]);

  // Clean up DOM node on unmount
  useEffect(() => {
    return () => {
      ensureChipContainer(false);
    };
  }, []);

  const handleDismiss = useCallback(() => {
    agent.setState({ ...agent.state, pending_template: null });
  }, [agent]);

  if (!pending?.name) return null;

  const chipContent = (
    <div
      className="inline-flex items-center gap-1.5 pl-2 pr-1 py-0.5 rounded-md text-xs font-medium select-none"
      style={{
        background:
          "linear-gradient(135deg, rgba(99,102,241,0.12), rgba(16,185,129,0.12))",
        border: "1px solid rgba(99,102,241,0.22)",
        color: "var(--copilot-kit-contrast-color, #1a1a1a)",
        animation: "chipIn 0.15s ease-out",
      }}
    >
      <svg
        width="11"
        height="11"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ opacity: 0.55, flexShrink: 0 }}
      >
        <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" />
      </svg>
      <span className="max-w-[140px] truncate" style={{ lineHeight: "16px" }}>
        {pending.name}
      </span>
      <button
        onClick={handleDismiss}
        className="p-0.5 rounded transition-colors duration-100 hover:bg-black/10 dark:hover:bg-white/10"
        style={{ lineHeight: 0 }}
        aria-label="Remove template"
        type="button"
      >
        <svg
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </button>
    </div>
  );

  // Fallback: render inline when CopilotKit DOM structure isn't available
  if (!container) return chipContent;

  return createPortal(chipContent, container);
}
