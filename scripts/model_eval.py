#!/usr/bin/env python3
"""Repeatable model comparison for Media Agent (Profile A vs Profile B).

Sends a fixed prompt set to the running agent's OpenAI-compatible API and
records, per prompt: latency, response length, and hygiene checks (no
<think> leakage, no raw tool-call JSON). Run once per model profile and
diff the JSON reports.

Usage:
    python scripts/model_eval.py --base-url http://localhost:8088 \
        --label qwen2.5-7b [--api-key KEY]

Services don't need to be reachable — tool errors still exercise tool
CHOICE, which is what differs between models. Judge tool-choice quality by
reading the transcript in the report.
"""
import argparse
import json
import time
from pathlib import Path

import httpx

PROMPTS = [
    # tool choice: read-only lookups
    "what's airing this week?",
    "list my movies",
    "check the health of all services",
    "how much disk space is left?",
    # search → disambiguate flow (should ask, not add blindly)
    "add the movie Heat",
    # follow-up reference resolution (depends on client resending history —
    # the script sends both turns)
    "the 1995 one",
    # approval flow (must NOT execute, must ask)
    "organize /media/music",
    # unavailable capability (should say so, not hallucinate)
    "rip the audio from this DVD",
    # multi-step
    "is anything stuck in the download queues?",
]

HYGIENE_MARKERS = ("<think>", "<tool_call>", '"tool_calls"', '"arguments"')


def run(base_url: str, api_key: str, label: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    history: list[dict] = []
    results = []

    with httpx.Client(base_url=base_url, headers=headers, timeout=300) as client:
        for prompt in PROMPTS:
            history.append({"role": "user", "content": prompt})
            start = time.time()
            try:
                resp = client.post("/v1/chat/completions", json={
                    "model": "media-agent",
                    "messages": history,
                })
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                error = None
            except Exception as e:
                content, error = "", f"{type(e).__name__}: {e}"
            elapsed = time.time() - start
            history.append({"role": "assistant", "content": content})

            leaks = [m for m in HYGIENE_MARKERS if m in content]
            results.append({
                "prompt": prompt,
                "seconds": round(elapsed, 1),
                "chars": len(content),
                "hygiene_leaks": leaks,
                "error": error,
                "response": content,
            })
            status = "ERR" if error else ("LEAK" if leaks else "ok")
            print(f"[{status:4}] {elapsed:6.1f}s  {prompt}")

    return {
        "label": label,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totals": {
            "prompts": len(results),
            "errors": sum(1 for r in results if r["error"]),
            "hygiene_leaks": sum(1 for r in results if r["hygiene_leaks"]),
            "total_seconds": round(sum(r["seconds"] for r in results), 1),
        },
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8088")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--label", required=True,
                        help="model label for the report filename, e.g. qwen2.5-7b")
    args = parser.parse_args()

    report = run(args.base_url, args.api_key, args.label)
    out = Path(f"eval_{args.label}.json")
    out.write_text(json.dumps(report, indent=2))
    print(f"\nTotals: {report['totals']}")
    print(f"Report written to {out} — compare reports across model profiles.")


if __name__ == "__main__":
    main()
