import { z } from "zod";
import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { MediaApprovalCard } from "@/components/generative-ui/media-approval-card";

/** Media-agent's yes/no confirmation, shown as Approve / Decline buttons. */
export const useMediaApproval = () => {
  useHumanInTheLoop({
    name: "requestMediaApproval",
    description:
      "Ask the user to approve one media action (add, download, record, subscribe, rename, cleanup) before running it. " +
      "The server refuses the action unless the user clicks Approve for the exact same tool and arguments.",
    parameters: z.object({
      tool: z.string().describe("Exact name of the tool you will call after approval, e.g. add_movie."),
      argsJson: z.string().describe("Exact JSON object of the arguments you will pass to that tool."),
      summary: z.string().describe("One plain-English line: what will happen, including size for big downloads."),
    }),
    render: ({ respond, status, args }) => (
      <MediaApprovalCard status={status} respond={respond} {...args} />
    ),
  });
};
