# PROGRESS — Mobile Price Tracker

> The dated running log + status board. This is the **communication channel** between the Architect
> and Code (via the Bridge). Every working cycle appends here (chronological, newest at the bottom).
> **Standing rule (Bridge):** every CODE TASK ends by updating this file AND CONTEXT.md (durable
> knowledge), committed + pushed — new sessions bootstrap exclusively from these files. See INSTRUCTIONS §2.1.

---

## Status board

| Area | State | Notes |
|------|-------|-------|
| Foundations (root docs) | ✅ done | INSTRUCTIONS / GOVERNANCE / WORKFLOW / READMEs created. |
| Project scaffold | ✅ done | Folder layout, CONTEXT, PROGRESS, config, src skeleton, tests, CI workflow. |
| Reconnaissance | ✅ done | Stacks identified (TIM=Drupal, Claro=Next.js, Vivo=AEM). See CONTEXT §3. |
| Data schema | ✅ done | `Plan` dataclass defined (CONTEXT §6). |
| Excel writer | ✅ done (offline) | Works on fixture data; verified by demo run + unit test. |
| Adapters (vivo/claro/tim) | 🟡 stubs | Interfaces + documented strategy; **selectors/parsing TBD by Code on live sites.** |
| Live scraping | 🔌 not started | Needs Code on a real machine (sandbox can't reach the sites). |
| Scheduling (GitHub Actions) | 🟡 drafted | Workflow file present; needs repo + secrets + first run. |
| GitHub + Drive backup | 🟡 partial | GitHub repo live (private, pushed by Code). Drive mirror not started. |

Legend: ✅ done · 🟡 in progress / partial · 🔌 not started · ⛔ blocked

---

## Next actions (Architect's recommendation)
1. **Bridge:** create the GitHub repo and push this scaffold (CODE TASK #1).
2. **Code:** set up the Python env, install deps, run the offline demo + tests to prove the pipeline (CODE TASK #2).
3. **Code:** implement the **Claro** adapter first (cleanest — `__NEXT_DATA__` JSON), report a sample of real SP plans (CODE TASK #3).
4. Then Vivo (AEM `.model.json` probe), then TIM (HTML + image-price handling).
5. Wire GitHub Actions to run daily and commit the Excel; then add the Drive mirror.

---

## Log

### 2026-06-11 — Project initialized (Architect)
- Created the builder repo and the four root docs (INSTRUCTIONS, GOVERNANCE, WORKFLOW, README).
- Stood up the `mobile-price-tracker` project: CONTEXT, PROGRESS, `config/sources.yaml`, `src/mobile_tracker/*`, tests, and a GitHub Actions workflow.
- Ran reconnaissance on all three carriers via `web_fetch`; recorded stacks, data-access strategy, and gotchas in CONTEXT §3.
- Defined the `Plan` schema and the 4-sheet Excel layout; implemented `excel_writer.py` and a `--demo` mode in `main.py` seeded with sample data (incl. the real Vivo *60GB/R$150* offer found in recon) so the pipeline is verifiable offline.
- Wrote adapter **stubs** with documented per-carrier strategies; real parsing is deferred to Code on the live sites (sandbox is network-restricted).
- **Open questions for the Bridge:** see CONTEXT §10.
- **Handed off:** CODE TASK #1 (init repo) and #2 (env + verify pipeline).

### 2026-06-11 — Excel formula fix + offline verification (Architect)
- **Bug:** on LibreOffice recalc, the summary sheet's `MINIFS`/`MAXIFS` returned the `IFERROR` fallback (`"-"`) while `AVERAGEIFS`/`COUNTIF` worked.
- **Cause:** `MINIFS`/`MAXIFS` are post-2007 functions and must be stored with the `_xlfn.` prefix to be recognized by the OOXML engine; the pre-2007 functions don't need it.
- **Fix:** `excel_writer.py` now writes `=IFERROR(_xlfn.MINIFS(...),"-")` and `=IFERROR(_xlfn.MAXIFS(...),"-")`.
- **Verified:** rebuilt 3 synthetic snapshots (2026-06-09/10/11), recalced with LibreOffice → **0 formula errors, 12 formulas**; summary now computes real values (e.g. vivo min 14.99 / max 139, claro 59.99 / 119.99, tim 49.99 / 139.99). `pytest` → **6 passed**.
- **Status:** offline pipeline (schema → writer → 4 sheets → recalc) is green and idempotent. Ready to hand to Code.

### 2026-06-11 — Bridge decisions recorded (Architect)
- Resolved all four open questions; CONTEXT bumped to **v0.2.0** (§10 + §7/§8 + changelog).
  1. **Excel layout:** per-carrier sheets + dashboard = **backlog**, build after live pipeline works; keep interim function-sheets.
  2. **Plan depth:** **full detail** — adapters expand "ver mais"/modals. Noted in each adapter docstring + §8 (Playwright-favored, longer runs).
  3. **Drive mirror:** **rclone inside GitHub Actions** (runs unattended; desktop-sync needs machine on). One-time local `rclone config` by the user → `rclone.conf` stored as a GitHub Secret → `rclone copy` step after commit.
  4. **History:** keep all snapshots forever.
- `pytest` still **6 passed**; edited adapters parse clean.
- Unchanged: CODE TASK #1 (init repo) and #2 (offline verify) are unaffected by these choices and ready to run now. The decisions shape CODE TASK #3+ (live adapters) and the later Actions/Drive wiring.

### 2026-06-11 — CODE TASK #1 done: repo initialized and pushed (Code)
- Repo initialized and pushed: **https://github.com/rafaelxoliver4-art/prompt-project-builder** (private, branch `main`, root commit `463c0d3`). INSTRUCTIONS → **v1.1.0** (Code-writes-all-files role split; §6 "Where work is saved" added). Offline pipeline verified earlier by the Architect — 6 tests passing.
- **Caveat for the Actions wiring task:** `.github/workflows/mobile-price-tracker.yml` is **excluded from the push** (still on disk, untracked). The machine's `gh` OAuth token lacks the `workflow` scope, and GitHub rejects any push that adds a workflow file without it. Before wiring CI: run `gh auth refresh -h github.com -s workflow` (Bridge completes the device-code + email verification on github.com), then commit and push the workflow file.
- Repo-local git identity set (`rafaelxoliver4-art` / `rafaelxoliver4@gmail.com`); no global config touched. Verified no secrets staged (`.env`/`*.key`/`rclone.conf` excluded by `.gitignore`).

### 2026-06-11 — CODE TASK #2 done: offline pipeline verified on the real machine (Code)
- Environment: **Windows 11 Pro (10.0.26200), Python 3.13.13**, venv at `.venv/`, all `requirements.txt` deps installed, Playwright **Chromium installed** (ready for live tasks).
- `python -m pytest -q` → **6 passed** (17.50s).
- `python -m mobile_tracker.main --demo` → `Wrote data\mobile_plans.xlsx: 12 plans in latest (2026-06-11), 3 snapshot(s), 5 change(s).` (Note: `python -m` needs `PYTHONPATH=src` — pyproject only wires `src/` for pytest; consider `pip install -e .` or a runner script in a future task.)
- Workbook verified in **real Excel (COM recalc)**: 4 sheets (`history`/`latest`/`changes`/`summary`); summary KPIs compute real values — vivo 4 plans min R$ 14.99 / avg R$ 92.25 / max R$ 150.00; claro 4 plans 59.99 / 83.74 / 119.99; tim 4 plans 30.00 / 74.99 / 139.99. No `"-"` fallbacks.
- Demo-overwritten `data/mobile_plans.xlsx` restored via `git checkout --` (not committed, per task guardrail). **Offline pipeline verified on the real machine.**

### 2026-06-11 — Bridge standing rule: two-files closing ritual (Code, on Bridge's instruction)
- Rafael's rule, now codified: **every CODE TASK ends with BOTH PROGRESS.md (dated entry) and CONTEXT.md (durable knowledge) updated, committed, and pushed.** Rationale: new chat/Code sessions bootstrap exclusively from these files — anything not written here is lost.
- Written into INSTRUCTIONS **v1.2.0** (§2.1 "Closing ritual" + changelog) and into both files' headers. CONTEXT bumped to **0.2.2**.
- Also flagged by the Bridge: the prices in the workbook are **demo sample data, not real prices** (see CONTEXT §5 note); Bridge is raising it with the Architect. Real prices arrive with the live adapters (CODE TASK #3+).

### 2026-06-11 — Backup to Google Drive + machine transfer prep (Code)
- Bridge is moving to another computer; asked to ensure everything is saved to GitHub **and** Google Drive.
- **GitHub:** verified fully pushed — working tree clean, `origin/main` at `0587ba9` (only untracked item is `.github/`, the workflow file that can't be pushed yet — workflow-scope auth pending).
- **Google Drive:** copied the full project to **`G:\Meu Drive\prompt-project-builder`** (account `rafaelxoliver4@gmail.com`, Drive Desktop running) via `robocopy /E` excluding `.venv`/`__pycache__`/`.pytest_cache`. The Drive copy **includes `.git` history AND `.github/workflows/mobile-price-tracker.yml`** — so it is the only cloud copy that has the workflow file. ~0.2 MB; all key files verified present.
- Recorded the three-copy map + new-machine bootstrap steps in **CONTEXT §5** (v0.2.3). Key gotcha for the new machine: a fresh `git clone` will be **missing the `.github/` workflow file** — restore it from the Drive backup.
- ⚠️ Drive Desktop syncs the local `G:\Meu Drive` folder to the cloud in the background; allow a moment for upload to finish before powering down this machine.
