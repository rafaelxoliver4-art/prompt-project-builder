# WORKFLOW — the operating loop

> **Version:** 1.0.0 · **Last updated:** 2026-06-11
> How work actually moves through the three roles. Read with `INSTRUCTIONS.md` (roles & rules) and
> `GOVERNANCE.md` (what needs approval).

---

## The loop

```
        ┌─────────────────────────────────────────────────────────┐
        │                                                         │
   ┌────▼─────┐   CODE TASK    ┌──────────┐   runs on machine ┌───┴────┐
   │ ARCHITECT│ ─────────────▶ │  BRIDGE  │ ───────────────▶ │  CODE  │
   │  (chat)  │                │  (user)  │                  │ (CLI)  │
   └────▲─────┘ ◀───────────── └──────────┘ ◀─────────────── └────────┘
        │        REPORT BACK                  test output /
        │                                     errors / decisions
        └── updates CONTEXT.md + PROGRESS.md, issues next task ──┘
```

One cycle = **plan → hand off → execute → report → record → next**. Each cycle is small enough to verify.

---

## Templates

### A) CODE TASK (Architect → Bridge → Code)
The Architect emits this; the Bridge pastes it into Claude Code verbatim.

```
=== CODE TASK <project> #<n>: <short title> ===
GOAL: <one sentence outcome>
CONTEXT: read <files> first.
DO:
  1. <step>
  2. <step>
CONSTRAINTS: <governance / style / "ask before new heavy deps">
ACCEPTANCE CRITERIA:
  - [ ] <testable outcome>
  - [ ] tests pass: <command>
REPORT BACK: <exact output to paste back>
=== END TASK ===
```

### B) REPORT BACK (Code → Bridge → Architect)
What the Bridge pastes back into the chat. Ideally just copy Code's final summary, but it should include:

```
TASK: <project> #<n>
RESULT: done | partial | blocked
TEST OUTPUT:
<paste>
DECISIONS CODE MADE: <anything it had to choose>
NEW/CHANGED FILES: <list or `git status`>
ERRORS / BLOCKERS: <paste, or "none">
```

### C) DECISION note (recorded by Architect in CONTEXT.md)
```
[DECISION YYYY-MM-DD] <title>
Choice: <what we decided>
Why: <one or two lines>
Rejected: <the main alternative and why not>
```

---

## Tips for a smooth bridge

- Paste CODE TASKs **whole**; don't paraphrase them to Code.
- When Code asks *you* (the Bridge) a question that's really for the Architect, bring it back here.
- If Code hits a 🟡/🔴 governance item, it should stop and report — you decide, not Code.
- Keep one project per chat thread where practical, so the Architect's context stays focused.

---

## Changelog
- **1.0.0 — 2026-06-11** — Initial loop diagram and the CODE TASK / REPORT BACK / DECISION templates.
