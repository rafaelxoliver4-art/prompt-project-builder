# PROGRESS — Mobile Price Tracker

> The dated running log + status board. This is the **communication channel** between the Architect
> and Code (via the Bridge). Newest entries on top. Every working cycle appends here.

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
