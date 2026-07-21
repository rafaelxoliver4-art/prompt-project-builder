# Prompt & Project Builder

A workbench for building real software projects through a disciplined three-role loop:

- **Architect** — Claude in the chat interface. Plans, designs, writes prompts & tests, keeps the knowledge files, reviews results.
- **Implementer** — Claude Code on the local machine. Executes the Architect's tasks, runs the live system, commits to git.
- **Bridge** — you. You carry tasks and results between the two, and you're the only one who approves anything risky.

This repo is a **monorepo**: shared operating rules at the root, one self-contained folder per project under `projects/`.

## Read these first
| File | What it's for |
|------|----------------|
| [`RULEBOOK.md`](RULEBOOK.md) | **Authoritative.** The shared rulebook (v1.2.0) — roles, connectivity, prime directives, governance, project isolation. Mirrors the live claude.ai instructions box. |
| [`INSTRUCTIONS.md`](INSTRUCTIONS.md) | ⚠️ Superseded by `RULEBOOK.md`. The former Architect playbook, kept for history. |
| [`GOVERNANCE.md`](GOVERNANCE.md) | ⚠️ Superseded by `RULEBOOK.md`. Former approval / security / legal rules, kept for history. |
| [`WORKFLOW.md`](WORKFLOW.md) | ⚠️ Superseded by `RULEBOOK.md`. Former operating loop + templates, kept for history. |

## Projects
| Project | Status | Description |
|---------|--------|-------------|
| [`mobile-price-tracker`](projects/mobile-price-tracker/) | 🟡 scaffolding | Daily tracker of Vivo / Claro / TIM mobile plan prices (pré, controle, pós, Vivo Lite, Claro Flex), São Paulo first, into a versioned Excel time-series. |

## How a project works here
Every project folder is self-contained and always contains:
- `CONTEXT.md` — the *what / how / why* and all decisions (the project's brain & IP).
- `PROGRESS.md` — the dated running log and status board (the comms channel with Code).
- `config/` — everything that changes (URLs, states, schedules, selectors).
- `src/` and `tests/`.

## Backups & remote access
Source of truth is **GitHub**; the daily run is executed by **GitHub Actions** (so it works with your machine off) and the output Excel is mirrored to **Google Drive** for easy human access. See `GOVERNANCE.md §5`.
