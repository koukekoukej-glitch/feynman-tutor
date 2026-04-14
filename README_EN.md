# Feynman Tutor

**A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) Skill based on the Feynman Technique — instead of explaining concepts to you, it makes YOU explain them, exposing the exact gaps in your understanding.**

[中文版 README](README.md)

---

## The Problem It Solves

You've probably experienced this:

- You read a deep article and thought "I get it" — but when someone asks you to explain, you can't
- You asked AI to "teach you" something, it gave a perfect explanation, you nodded along — but nothing actually stuck
- You've learned lots of fragments, but they don't connect into anything usable

The problem isn't that AI explains poorly. The problem is: **passively listening ≠ learning.**

Feynman Tutor's core design: **it doesn't give you answers — it makes you articulate them yourself.** Where you can't articulate, that's where you don't understand.

---

## How Is This Different From "Ask AI to Explain"?

|  | Typical AI Chat | Feynman Tutor |
|---|---|---|
| **Who's talking?** | AI explains to you | **You explain to AI** |
| **Finding blind spots** | You don't know what you don't know | AI probes with follow-up questions to expose cracks |
| **Difficulty** | Either too easy or too hard | Always one step beyond your knowledge boundary (ZPD) |
| **Cross-session memory** | Starts from zero every time | Remembers what you've learned, where you got stuck, which analogies worked |
| **External materials** | "Summarize this video for me" | Turns the video into teaching material, uses Feynman method to help you internalize |
| **Cross-topic connections** | Each topic is an island | Automatically discovers structural analogies and shared patterns across topics |

---

## Core Features

### 1. Role-Reversal Teaching

You're not the student — you're the "teacher." Feynman Tutor plays a curious friend who knows nothing, and asks you to explain concepts. When you hesitate, go in circles, or get vague — that's your knowledge boundary.

> "Wait, you said A leads to B, but what if the situation is C?"

Not trying to trip you up — helping you see what you can't see yourself. Even if you're stuck and say "I don't know," the tutor won't just give you the answer — it'll probe from a different angle until you figure it out yourself.

### 2. Precise Knowledge Boundary Detection (ZPD)

Based on Vygotsky's **Zone of Proximal Development**: learning only happens at the boundary between "known" and "unknown." The tutor uses 2-3 progressive questions to locate your knowledge boundary, then works exactly one step beyond it — never boring, never overwhelming.

```
Concept level → "What do you know about X?"
Mechanism level → "What do you think the underlying principle is?"
Application level → "How would you apply this in situation Y?"

Observe where the "fluency cliff" appears → that's the knowledge boundary
```

### 3. Multi-Source Material Extraction Pipeline

Drop a link, and it doesn't "summarize" — it turns the material into personalized teaching content. Built-in production-grade extraction pipeline covering major content platforms:

| Source | Extraction Method |
|--------|------------------|
| **YouTube** | Transcript API + yt-dlp (with Cookie auth for IP blocks) |
| **Bilibili** | bilibili-api AI subtitles + yt-dlp CC subtitles |
| **WeChat Articles** | Camoufox anti-detection browser + DOM extraction |
| **PDF / arXiv** | pymupdf4llm structured Markdown extraction |
| **Web pages** | trafilatura + Playwright JS rendering fallback |
| **X/Twitter** | GraphQL API (requires additional setup) |

Extracted materials are cached automatically — no re-extraction needed across sessions. Long materials are loaded on-demand via topic maps — even a 200K-word PDF won't blow up the context.

### 4. Persistent Cognitive System

This is not a stateless chatbot. It maintains three layers of persistent memory:

```
notes/
├── INDEX.md          # Index of all studied topics
├── LEARNER.md        # Learner model (cross-topic cognitive style, blind spots, effective strategies)
├── GRAPH.md          # Cognitive map (cross-topic connections, structural analogies, domain frameworks)
├── attention.md      # Topic notes: mastered / misconceptions / boundary / effective analogies
├── tcp-protocol.md
└── ...
```

- **Topic Notes**: Recorded in your own words (not textbook definitions) — what you've mastered, corrected misconceptions, current knowledge boundary, areas to strengthen, effective analogies
- **Learner Model** (`LEARNER.md`): Cross-topic metacognitive analysis — your cognitive style, habitual blind spots, teaching strategies that work for you
- **Cognitive Map** (`GRAPH.md`): Structural analogies between different topics, shared patterns, cognitive transfer paths

Next time you learn something new, the tutor automatically loads your full cognitive landscape, picks up where you left off, and proactively bridges existing knowledge: "Remember the concept of [X] from [old topic]? This is actually the same pattern in a different domain."

### 5. Tiered Diagnostic Feedback

Not just "right/wrong":

- 🔴 **Critical misconception** — directional error, corrected with an analogy or counterexample that triggers an "aha moment"
- 🟡 **Incomplete understanding** — right direction but gaps, guided to fill them yourself
- 🟢 **Could be phrased better** — understanding is correct, given a more precise formulation

Also reinforces what you got right — positive feedback matters equally.

### 6. Dynamic Calibration

Continuously reads your signals throughout the session and adjusts pace in real-time:

| Your Signal | Tutor's Response |
|-------------|-----------------|
| Answers getting faster and more confident | Increase stride, introduce deeper concepts |
| Stuck on the same point repeatedly | Switch to a completely different analogy or angle |
| Short, dismissive answers | Step back to comfort zone, consolidate before pushing |
| Asking questions ahead of the curriculum | Jump directly to deeper level |
| "I think I get it" | Throw a variant scenario — transfer ability = true understanding |

---

## Installation

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and working
- Python 3.10+ (needed for the material extraction pipeline; pure concept learning doesn't require it)

### One-Step Install

```bash
git clone https://github.com/YOUR_USERNAME/feynman-tutor.git ~/.claude/skills/feynman-tutor
```

Done. No additional configuration needed.

The first time you use the material extraction feature, the script automatically creates an isolated Python virtual environment and installs all dependencies (~2 minutes).

### Optional: Cookie Setup (Improves Extraction Success Rate)

Some platforms require authentication in certain network environments:

**YouTube** (if you hit IP blocks):
1. Install the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension
2. Open YouTube and make sure you're logged in
3. Click the extension icon → Export → Save as `~/.claude/skills/feynman-tutor/scripts/youtube_cookies.txt`

**Bilibili** (AI subtitles require login):
- Same process, save as `scripts/bilibili_cookies.txt`

---

## Usage

After installation, just speak naturally in Claude Code — the skill triggers automatically, no prefix commands needed.

### Concept Learning

```
> Teach me about attention mechanisms
> Help me understand the TCP three-way handshake
> I want to understand what ZPD means
> What is the fundamental theorem of calculus really saying?
```

### Material Learning

```
> https://www.youtube.com/watch?v=aircAruvnKk I want to learn what this video covers
> Help me digest this article https://example.com/deep-learning-intro
> ~/Documents/paper.pdf help me study this paper
```

### Save Learning Progress

```
> Save notes
> Record what I learned today
> Update my learning progress
```

---

## Learning Flow

### Concept Learning

```
"Teach me X"
    │
    ▼
┌──────────────────────┐
│  Load cognitive       │ ← Notes + learner model + cognitive map
│  landscape            │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Cognitive probing    │ ← 2-3 progressive questions to find the boundary
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Role reversal        │ ← "You teach me" — probing questions expose gaps
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Diagnostic feedback  │ ← 🔴🟡🟢 tiered assessment + positive reinforcement
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐     🔴 unresolved
│  Reinforcement &      │ ──────────────────→ Back to "Role Reversal"
│  output               │
└──────────┬───────────┘
           │ All resolved
           ▼
┌──────────────────────┐
│  Save notes           │ ← Update topic notes + cognitive map
└──────────────────────┘
```

### Material Learning

```
User drops a URL
    │
    ▼
┌──────────────────────┐
│  Check cache          │ ← Previously extracted materials loaded directly
└──────────┬───────────┘
           │ Cache miss
           ▼
┌──────────────────────┐
│  Extract content      │ ← Auto-detect source type, run corresponding extractor
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Analysis report      │ ← Topic map + knowledge map + recommended learning path
└──────────┬───────────┘
           │ User selects a topic
           ▼
┌──────────────────────┐
│  Feynman-style        │ ← Guide → Role reversal → Diagnose → Reinforce
│  deep discussion      │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Update progress      │ ← Mark discussed topics, ask to continue or switch
└──────────────────────┘
```

---

## Project Structure

```
feynman-tutor/
├── SKILL.md                      # Core skill definition (triggers + full teaching flow)
├── references/
│   ├── material-analysis.md      # Material learning flow (extract → analyze → discuss)
│   └── note-management.md        # Note management + cognitive map update flow
├── scripts/
│   ├── run.py                    # Environment bootstrapper (auto venv + dependency install)
│   └── extract_content.py        # Multi-source content extraction engine (~1500 lines)
├── notes/                        # Learning notes (auto-generated during use, gitignored)
└── materials/                    # Material cache (auto-generated during use, gitignored)
```

---

## Design Philosophy

This Skill is not a "prompt template" — it's a complete **cognitive engineering system**:

1. **Pedagogy-driven.** The Feynman Technique and ZPD aren't decorative name-drops — they're the decision criteria behind every design choice. "What should I say next?" always resolves to "Is this one step beyond the user's knowledge boundary?"

2. **Stateful, not stateless.** Topic notes, learner models, cognitive maps — every session builds on previous ones. Traditional prompt engineering loses all state when the context window ends. This system doesn't.

3. **Materials are input, not authority.** The tutor encourages critical thinking; if the material contains errors, it points them out. "Why does the author say this? Is there another perspective?"

4. **Flexible flow, not rigid pipeline.** A quick confirmation doesn't need the full four stages. A zero-background user gets more time in the probing phase. When you say "just explain it to me first," the tutor can temporarily switch modes.

5. **In your own words.** Notes record your phrasing and your validated analogies, not textbook definitions. Because the next "tutor" reading these notes needs your actual cognitive state, not standard answers.

---

## Best Suited For

**Excels at:**
- Concepts that require deep understanding (not just looking up a definition)
- Extracting and internalizing knowledge from videos, articles, and papers
- Cross-domain learning that needs to connect to existing knowledge
- Long-term, systematic study of a domain

**Not ideal for:**
- Quick fact lookups (asking AI directly is faster)
- Just needing a summary (this Skill's goal is to make you *learn*, not save you time)

---

## FAQ

**Q: What if material extraction fails?**

The script outputs detailed error messages with solutions. The most common case is needing Cookie configuration (YouTube IP blocks, Bilibili AI subtitles). You can also paste content directly to Claude, skipping automatic extraction.

**Q: Does it work in languages other than Chinese?**

The teaching methodology is language-agnostic — the tutor matches your conversation language. However, the Skill definition files themselves are written in Chinese. Community translations are welcome.

**Q: Can it coexist with other Claude Code Skills?**

Yes. Feynman Tutor only triggers when it detects learning intent and won't interfere with other Skills.

---

## Contributing

PRs and Issues welcome. Especially:

- New content source extractors (Podcasts, Notion, etc.)
- Additional evaluation cases
- Skill definition translations to other languages
- Bug fixes and extraction pipeline improvements

---

## License

[MIT](LICENSE)
