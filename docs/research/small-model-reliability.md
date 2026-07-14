# Research Report — Operating on the Lightest Possible Local Models

> Deep-research pass (2026-07-14) into making the agent reliable on 1–4B-class local
> models and pushing deterministic (LLM-free) coverage higher. 22 sources fetched,
> 90 claims extracted, top 25 adversarially verified (3 independent verifiers per
> claim): **16 confirmed, 9 refuted**. Refuted claims are listed at the bottom so
> they don't get resurfaced as facts later.

---

## Headline conclusion

The single most concretely evidenced lever for small-model tool-calling reliability
is **reducing how many tools (and how much context) the model sees per call** — not
picking a "better" small model. Our existing domain-scoping design
(`src/graphs/scoping.py`, ~10 of 92 tools per call) is the right architecture; the
research says to push it further. Everything else (grammar router upgrades, fuzzy
matching, embedding tiers, `interrupt()`) layers around that core.

---

## Prioritized recommendations

### 1. Tighten per-call tool exposure further (no new deps — highest confidence)

The "Less-is-More" paper (DATE 2025, [arXiv:2411.15399](https://arxiv.org/pdf/2411.15399))
has a verified worked example: the *identical* Llama3.1-8b-q4_K_M model **fails with
46 tools bound and succeeds with 19** (exec time 30s → 20s, and → 17s when context
was also cut 16K → 8K). That flip — same model, same hardware, only tool count
changed — is the strongest single data point found anywhere in this research.

Codebase action: audit `src/graphs/scoping.py` domain buckets for any that bind
more than ~10–12 tools; consider sub-domain scoping (e.g. "sonarr-read" vs
"sonarr-write") so ambiguous-but-narrow messages bind 4–6 tools, not 10+. Also
consider dropping `num_ctx` for tool-call turns where history isn't needed.

**Caveat:** the generalization of this result across six 7–8B models was checked
and did *not* survive verification — only the single Llama3.1-8b worked example is
confirmed. And it ran on a Jetson AGX Orin, not our RTX 3060/Ollama/qwen stack.
Directionally strong, numerically not transferable. Needs local benchmarking (see §6).

### 2. Fine-tuning-free "ideal tool" retrieval (no new deps beyond an embedder)

The same paper's verified architecture: have the LLM (or a cheap heuristic)
describe the *ideal tool* it needs, embed that description, and k-NN it against
pre-embedded descriptions of all 92 tools (they used MPNet + FAISS), binding only
the top-k. Fall back to the full/domain set below a 0.5 similarity threshold or on
execution failure. This is a drop-in refinement of our keyword classifier for the
router-miss path — no fine-tuning, no model swap.

### 3. hassil-style grammar router (zero/near-zero new deps)

Home Assistant's [hassil](https://github.com/home-assistant/hassil) (verified
against the repo and [HA developer docs](https://developers.home-assistant.io/docs/voice/intent-recognition/template-sentence-syntax/))
is a mature, deterministic, non-ML template matcher that is strictly more
expressive than raw regex:

- optional words: `[the]`, `[this | that]`
- alternatives: `(red|green|blue)`, `turn(ed|ing)`
- three slot/list types: fixed text values, numeric ranges, and "match any text"
  wildcards
- named slot binding: `{list_name}` or `{list_name:slot_name}`

This is exactly the "match utterance → intent + slots without an LLM" problem our
router solves, proven at Home Assistant scale. Porting the *constructs* into
`src/graphs/router.py` (compiling templates down to regex at startup) keeps us
dependency-free while making intents dramatically easier to author than 60 groups
of hand-written regex.

**Caveat:** the claim that hassil's only dependency is PyYAML was **refuted** —
if adopting the library itself rather than reimplementing the pattern, verify its
actual dependency footprint first.

### 4. Fuzzy/typo-tolerant tier via rapidfuzz (one light dep)

[Nebulento](https://github.com/OpenJarbas/nebulento) (verified) demonstrates the
pattern: a fuzzy-matching intent parser built directly on `rapidfuzz`, designed as
a lightweight alternative to exact-match/regex intent matching. Layer this
*between* the grammar router and the LLM fallback: near-misses (typos, minor
phrasing drift) resolve deterministically instead of waking the 9B model. This
directly grows the LLM-free coverage metric.

**Caveat:** Nebulento's specific accuracy/F1 superiority numbers vs
Padatious/Padaos did **not** survive verification — adopt the pattern, don't cite
the benchmark.

### 5. Model2Vec static-embedding semantic tier (one light dep)

[Model2Vec](https://github.com/MinishLab/model2vec) (verified) distills any
sentence-transformer into a static embedding model: up to ~500x faster on CPU
(vendor's best-case figure), no GPU at inference, and distillation needs **no
training data** — just a vocabulary + base model, ~30 seconds on CPU. That makes a
fully-offline semantic router tier feasible: embed example utterances per intent
once, cosine-match incoming messages, fall through to the LLM only below a
threshold. [semantic-router](https://github.com/aurelio-labs/semantic-router)
implements this route-by-example-utterance pattern if we'd rather adopt than build.

### 6. Replace custom confirm flows with LangGraph `interrupt()` (no new deps)

Verified against [official LangGraph docs](https://docs.langchain.com/oss/python/langgraph/interrupts):
`interrupt()` is the framework-native human-in-the-loop primitive — dynamic (can be
placed anywhere in code, conditionally, unlike static breakpoints), requires a
configured checkpointer to persist/resume (we already run AsyncSqliteSaver), and is
the documented mechanism for pausing on approval of irreversible actions. Our
hand-rolled confirm flow for bulk/irreversible ops (ROM sets, renames, collection
sync) is a direct replacement candidate — less custom state code, and confirmations
survive process restarts for free.

### 7. Trial purpose-built small function-calling models (evaluate, don't commit)

The xLAM family ([arXiv:2409.03215](https://arxiv.org/pdf/2409.03215), verified)
spans 1B–8x22B including a ~1B model explicitly positioned for lightweight
deployment. Worth trialing as the tool-selection model for the router-miss path.
**But:** the claim that xLAM took "1st place on BFCL over GPT-4/Claude-3" was
**refuted** (0–3) — leaderboard claims decay fast. Benchmark locally on our schema
before adopting anything.

### 8. Calibrate expectations — our architecture is already correct

The BFCL paper (ICML 2025, [PMLR v267](https://proceedings.mlr.press/v267/patil25a.html),
verified, corroborated by mid-2026 follow-on work): even state-of-the-art frontier
models reliably handle only *single-turn* tool calls; multi-turn memory, dynamic
planning, and long-horizon agentic reasoning remain unsolved industry-wide. This
validates the current design — deterministic router first, short recursion limit,
narrow per-call tool sets — rather than hoping model upgrades fix multi-step
reliability.

---

## Suggested router pipeline (synthesis of §3–§5)

```
message
  → hassil-style grammar templates (deterministic, slots)   [§3]
  → rapidfuzz fuzzy match against template surface forms     [§4]
  → Model2Vec/static-embedding semantic match (threshold)    [§5]
  → domain-scoped LLM with minimal tool binding              [§1, §2]
  → circuit breaker → hosted fallback                        (existing)
```

Each tier is cheaper than the next, fully local, and each hit is a message the 9B
model never sees. Coverage tracking (already in place) measures each tier's
contribution.

---

## Evidence gaps — treat as unanswered, not answered-negative

Two of the five research questions produced **no claims that survived adversarial
verification**:

- **Media-stack automation UX patterns** (Overseerr/Jellyseerr request-approval
  flows, Maintainerr cleanup policies, watch-history-driven suggestions): sources
  were found but no specific claims verified. Needs a follow-up pass or direct
  code-reading of those projects.
- **Offline eval harness specifics** (golden utterance sets, replayed transcripts,
  measuring router coverage and tool-call accuracy across model swaps): BFCL is
  confirmed as the industry methodology, but nothing project-actionable verified.
  Practical note: our 214-test suite plus router coverage tracking is already most
  of the substrate — a golden-utterance corpus asserting (intent, tool, args)
  triples per utterance is buildable without external evidence.

Also unverified either way: whether **Ollama structured outputs / GBNF
grammar-constrained decoding measurably improves tool-call accuracy** (one blog
source describes the mechanism — GBNF generated from JSON schema, invalid tokens
masked at sampling time — but no effect-size evidence survived). Worth a local
experiment, not a citation.

## Refuted claims — do not resurface as facts

| Claim | Vote |
|---|---|
| xLAM took 1st on BFCL, beating GPT-4/Claude-3 | 0–3 |
| Tool-count reduction generalizes across six 7–8B model architectures | 0–3 |
| Quantization drops Llama3.1-8b BFCL 63% → 20% at q4_0 (specific figures) | 1–2 |
| 1–3B models beat <1B by specific BFCL percentages via "hybrid optimization" | 1–2 / 0–3 |
| hassil's only dependency is PyYAML | 0–3 |
| Nebulento's specific accuracy/F1 numbers vs Padatious/Padaos | 1–2 |
| Botdarr uses zero NLU/LLM (pure prefix routing) | 1–2 |

## Open questions for local benchmarking

1. Do the tool-pruning gains hold for qwen-class models via Ollama on the RTX 3060
   with our 92-tool schema? (Literature is Llama3.1-8b on Jetson.)
2. Does Ollama structured-output/GBNF constrained decoding measurably improve
   tool-call accuracy here?
3. Which request-approval / cleanup / suggestion automations do users of
   comparable bots actually value? (Unanswered by this pass.)
4. What does a minimal golden-utterance eval harness look like at this project's
   scale? (Unanswered by this pass; sketch above.)
