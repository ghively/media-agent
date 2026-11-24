"use client";

import type { DemoItem } from "./demo-data";

const CATEGORY_COLORS: Record<string, { bg: string; text: string }> = {
  "3D / Animation": { bg: "rgba(139,92,246,0.12)", text: "rgba(139,92,246,1)" },
  "Data Visualization": { bg: "rgba(59,130,246,0.12)", text: "rgba(59,130,246,1)" },
  Diagrams: { bg: "rgba(16,185,129,0.12)", text: "rgba(16,185,129,1)" },
  Interactive: { bg: "rgba(245,158,11,0.12)", text: "rgba(245,158,11,1)" },
  "UI Components": { bg: "rgba(236,72,153,0.12)", text: "rgba(236,72,153,1)" },
};

interface DemoCardProps {
  demo: DemoItem;
  onTry: (demo: DemoItem) => void;
}

export function DemoCard({ demo, onTry }: DemoCardProps) {
  const categoryColor = CATEGORY_COLORS[demo.category] ?? {
    bg: "rgba(100,100,100,0.12)",
    text: "rgba(100,100,100,1)",
  };

  return (
    <button
      onClick={() => onTry(demo)}
      className="demo-gallery-card rounded-xl overflow-hidden flex flex-col text-left transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5 cursor-pointer w-full"
      style={{
        border: "1px solid var(--color-border-glass, rgba(0,0,0,0.1))",
        background: "var(--surface-primary, #fff)",
      }}
    >
      <div className="flex flex-col gap-1.5 p-4 flex-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">{demo.emoji}</span>
            <h3
              className="text-sm font-semibold truncate"
              style={{ color: "var(--text-primary, #1a1a1a)" }}
            >
              {demo.title}
            </h3>
          </div>
          <span
            className="text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0"
            style={{
              background: categoryColor.bg,
              color: categoryColor.text,
            }}
          >
            {demo.category}
          </span>
        </div>
        <p
          className="text-xs line-clamp-2"
          style={{ color: "var(--text-secondary, #666)" }}
        >
          {demo.description}
        </p>
      </div>
    </button>
  );
}
