import { useConfigureSuggestions } from "@copilotkit/react-core/v2";

// Media-agent starters. Each one runs the agent against your own services.
export const MEDIA_SUGGESTIONS = [
  { title: "What's downloading?", message: "What's downloading right now? Show progress for each item." },
  { title: "How full are my disks?", message: "How full are my media disks? Chart used vs free space." },
  { title: "Service health", message: "Are all my media services healthy? Show a status board." },
  { title: "Recently added", message: "What was added to Emby recently? Show it as a table." },
];

export const useExampleSuggestions = () => {
  useConfigureSuggestions({
    suggestions: MEDIA_SUGGESTIONS,
    available: "always",
  });
};
