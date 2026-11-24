import { useState } from "react";

export interface MediaApprovalCardProps {
  status: "inProgress" | "executing" | "complete";
  respond?: (response: string) => void;
  tool?: string;
  argsJson?: string;
  summary?: string;
}

function prettyArgs(argsJson?: string): string {
  if (!argsJson) return "";
  try {
    return JSON.stringify(JSON.parse(argsJson), null, 2);
  } catch {
    return argsJson;
  }
}

/**
 * Yes/no card for media-agent actions that add, download, rename or delete.
 * The agent server refuses those tools unless this card answered "APPROVED"
 * for the exact same tool and arguments in the current turn.
 */
export function MediaApprovalCard({ status, respond, tool, argsJson, summary }: MediaApprovalCardProps) {
  const [answer, setAnswer] = useState<"approved" | "declined" | null>(null);
  const waiting = status === "executing" && answer === null;

  const approve = () => {
    setAnswer("approved");
    respond?.("APPROVED by the user.");
  };
  const decline = () => {
    setAnswer("declined");
    respond?.("DECLINED by the user. Do not run this action.");
  };

  return (
    <div className="media-approval" role="group" aria-label="Approve media action">
      <p className="media-approval__summary">{summary || "Approve this action?"}</p>
      <details className="media-approval__details">
        <summary>Exact action</summary>
        <code>{tool}</code>
        <pre>{prettyArgs(argsJson)}</pre>
      </details>
      {answer === "approved" && <p className="media-approval__result">Approved</p>}
      {answer === "declined" && <p className="media-approval__result">Declined</p>}
      {answer === null && status === "complete" && <p className="media-approval__result">Answered</p>}
      {waiting && (
        <div className="media-approval__actions">
          <button type="button" className="media-approval__yes" onClick={approve}>
            Approve
          </button>
          <button type="button" className="media-approval__no" onClick={decline}>
            Decline
          </button>
        </div>
      )}
      {status === "inProgress" && <p className="media-approval__result">Preparing…</p>}
    </div>
  );
}
