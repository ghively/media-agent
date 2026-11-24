# Human in the Loop

Human-in-the-loop lets the agent pause execution and render an interactive UI that waits for user input before continuing.

## How It Works

1. The agent calls a tool (e.g., `scheduleTime`)
2. Instead of executing server-side, CopilotKit renders a React component in the chat
3. The user interacts with the component (picks an option, fills a form, etc.)
4. The user's response is sent back to the agent as the tool result
5. The agent continues with the user's choice

## useHumanInTheLoop Hook

Register a human-in-the-loop component with `useHumanInTheLoop`:

```tsx
import { z } from "zod";
import { useHumanInTheLoop } from "@copilotkit/react-core/v2";

useHumanInTheLoop({
  name: "scheduleTime",
  description: "Schedule a meeting with the user.",
  parameters: z.object({
    reasonForScheduling: z.string().describe("Reason for scheduling, very brief"),
    meetingDuration: z.number().describe("Duration in minutes"),
  }),
  render: ({ respond, status, args }) => {
    return (
      <MeetingTimePicker
        status={status}
        respond={respond}
        {...args}
      />
    );
  },
});
```

### Render Props

| Prop | Type | Description |
|------|------|-------------|
| `respond` | `(response: string) => void` | Call this with the user's response to resume the agent |
| `status` | `"executing" \| "complete"` | `"executing"` while waiting for input, `"complete"` after response |
| `args` | `object` | The parameters the agent passed when calling the tool |

## Example: Meeting Time Picker

The demo includes a `MeetingTimePicker` component that shows time slots for the user to choose from:

```tsx
// apps/app/src/components/generative-ui/meeting-time-picker.tsx

function MeetingTimePicker({ status, respond, reasonForScheduling, meetingDuration }) {
  const [confirmed, setConfirmed] = useState(false);

  const handleSelect = (slot: TimeSlot) => {
    setConfirmed(true);
    respond(`User selected: ${slot.date} at ${slot.time} for ${slot.duration}`);
  };

  const handleDecline = () => {
    setConfirmed(true);
    respond("User declined all time slots.");
  };

  if (confirmed) {
    return <div>Meeting confirmed!</div>;
  }

  return (
    <div>
      <h3>Schedule: {reasonForScheduling}</h3>
      {timeSlots.map(slot => (
        <button key={slot.id} onClick={() => handleSelect(slot)}>
          {slot.date} at {slot.time}
        </button>
      ))}
      <button onClick={handleDecline}>None of these work</button>
    </div>
  );
}
```

Key points:
- Call `respond(string)` with whatever text you want the agent to receive
- The agent treats this string as the tool's return value
- After calling `respond`, the component should show a confirmation state
- The `status` prop changes to `"complete"` once the response is sent

## Building Your Own

1. **Define parameters** — What context does the agent provide? (Zod schema)
2. **Build the component** — Render UI based on `args`, call `respond()` on user action
3. **Register with `useHumanInTheLoop`** — The agent sees it as a callable tool
4. **Agent calls it naturally** — Based on the `description`, the agent decides when to use it

The agent doesn't need any special backend tool for this — `useHumanInTheLoop` creates a frontend-only tool that the agent can call.

## Next Steps

- [Generative UI](generative-ui.md) — Other ways the agent can render UI
- [Agent Tools](agent-tools.md) — Backend tools that complement human-in-the-loop
