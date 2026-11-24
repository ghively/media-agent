"use client";

import { ReactNode } from "react";

interface ExampleLayoutProps {
  chatContent: ReactNode;
}

export function ExampleLayout({
  chatContent,
}: ExampleLayoutProps) {
  return (
    <div className="flex-1 min-h-0 flex flex-row">
      {/* Chat Content */}
      <div className="h-full flex-1 max-lg:px-4">
        {chatContent}
      </div>
    </div>
  );
}
