import { render, cleanup, fireEvent, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

const captured = vi.hoisted(() => ({ configs: [] as Array<Record<string, unknown>> }));

vi.mock("@copilotkit/react-core/v2", () => ({
  useHumanInTheLoop: (config: Record<string, unknown>) => {
    captured.configs.push(config);
  },
}));

import { useMediaApproval } from "../use-media-approval";
import { MediaApprovalCard } from "@/components/generative-ui/media-approval-card";

function Probe() {
  useMediaApproval();
  return null;
}

afterEach(() => {
  cleanup();
  captured.configs.length = 0;
});

describe("media approval", () => {
  it("registers the requestMediaApproval tool the server gate expects", () => {
    render(<Probe />);
    expect(captured.configs.map((c) => c.name)).toEqual(["requestMediaApproval"]);
  });

  it("answers APPROVED only when Approve is clicked", () => {
    const respond = vi.fn();
    render(
      <MediaApprovalCard
        status="executing"
        respond={respond}
        tool="add_movie"
        argsJson='{"tmdb_id":603,"title":"The Matrix"}'
        summary="Add The Matrix (1999) to Radarr"
      />,
    );
    expect(screen.getByText("Add The Matrix (1999) to Radarr")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(respond).toHaveBeenCalledWith(expect.stringMatching(/^APPROVED/));
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("answers DECLINED when Decline is clicked", () => {
    const respond = vi.fn();
    render(<MediaApprovalCard status="executing" respond={respond} tool="add_movie" argsJson="{}" />);
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(respond).toHaveBeenCalledWith(expect.stringMatching(/^DECLINED/));
  });
});
