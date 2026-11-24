"use client";

import type { DemoCategory } from "./demo-data";
import { DEMO_CATEGORIES } from "./demo-data";

interface CategoryFilterProps {
  selected: DemoCategory | null;
  onSelect: (category: DemoCategory | null) => void;
}

export function CategoryFilter({ selected, onSelect }: CategoryFilterProps) {
  const categories: (DemoCategory | null)[] = [null, ...DEMO_CATEGORIES];

  return (
    <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
      {categories.map((cat) => {
        const isActive = cat === selected;
        return (
          <button
            key={cat ?? "all"}
            onClick={() => onSelect(cat)}
            className="demo-gallery-chip shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-150 cursor-pointer"
            style={{
              background: isActive
                ? "linear-gradient(135deg, var(--color-lilac-dark, #6366f1), var(--color-mint-dark, #10b981))"
                : "var(--surface-primary, rgba(255,255,255,0.6))",
              color: isActive ? "#fff" : "var(--text-secondary, #666)",
              border: isActive
                ? "none"
                : "1px solid var(--color-border-glass, rgba(0,0,0,0.1))",
            }}
          >
            {cat ?? "All"}
          </button>
        );
      })}
    </div>
  );
}
