"use client";

import { useEffect, useRef } from "react";

interface PlanCardProps {
  status: "executing" | "inProgress" | "complete";
  approach?: string;
  technology?: string;
  keyElements?: string[];
}

export function PlanCard({ status, approach, technology, keyElements }: PlanCardProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const isRunning = status === "executing" || status === "inProgress";

  useEffect(() => {
    if (!detailsRef.current) return;
    detailsRef.current.open = isRunning;
  }, [isRunning]);

  const spinner = (
    <span className="inline-block h-3 w-3 rounded-full border-2 border-gray-400 border-t-transparent animate-spin" />
  );
  const checkmark = <span className="text-green-500 text-xs">✓</span>;

  return (
    <div className="my-2 text-sm">
      <details ref={detailsRef} open>
        <summary className="flex items-center gap-2 text-gray-600 dark:text-gray-400 cursor-pointer list-none">
          {isRunning ? spinner : checkmark}
          <span className="font-medium">
            {isRunning ? "Planning visualization…" : `Plan: ${technology || "visualization"}`}
          </span>
          <span className="text-[10px]">▼</span>
        </summary>
        {approach && (
          <div className="pl-5 mt-1.5 space-y-1.5 text-xs text-gray-500 dark:text-zinc-400">
            {technology && (
              <span className="inline-block px-1.5 py-0.5 rounded bg-gray-100 dark:bg-zinc-700 text-gray-600 dark:text-zinc-300 font-medium text-[11px]">
                {technology}
              </span>
            )}
            <p className="text-gray-600 dark:text-gray-400">{approach}</p>
            {keyElements && keyElements.length > 0 && (
              <ul className="list-disc pl-4 space-y-0.5">
                {keyElements.map((el, i) => (
                  <li key={i}>{el}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </details>
    </div>
  );
}
