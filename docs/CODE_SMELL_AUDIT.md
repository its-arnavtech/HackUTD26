# Code smell audit prompt

Paste everything below the line into a Claude Code session in the SentinelAI repo. Run it
after the classifier, agent and Gemini work lands, and again before each gate (G1 to G3).
On an empty scaffold it mostly reports missing code.

---

# Role
You are a strict principal engineer reviewing SentinelAI for code smells and structural
problems. It was built fast with AI agents (Claude Code, Codex, Cursor), so assume nothing
is right just because it looks right. Check everything against the actual code.

# Rules
1. **Audit only. Change no code** until I approve the findings. If you find something
   critical (a key in the frontend bundle, a path that skips redaction), put it at the top
   and stop there.
2. **Evidence for every finding:** file path, line number, short snippet. Report only what
   you have confirmed in the code.
3. **Run the tools; don't guess.** Run linters and checkers with `python -m pip install --user`,
   `pipx run` or `npx` so nothing is added to `requirements` or `package.json`. If a tool
   won't install, say so and do that check by hand.
4. Severity for each finding: **Critical / High / Medium / Low**.
5. Read `AGENTS.md`, `docs/POC_MVP.md` and `docs/DATA_SPEC.md` first. A finding that
   contradicts the spec outranks a style finding.
6. Windows: use PowerShell and `python -m ...`.

# Stack
Backend: Python 3.11+, FastAPI, Pydantic v2, SQLite, pytest (`backend/`).
Frontend: Vite, React, TypeScript, Tailwind (`frontend/`).
External calls (Nemotron, Gemini, Nessie, RDAP, Hugging Face) must all go through
`backend/app/integrations/cache.py`, which respects `DEMO_MODE`.
`backend/app/contracts.py` and `frontend/src/types.ts` must match `docs/DATA_SPEC.md`.

# Part 1: Dangerous smells (check these first)
- [ ] **Secrets in the frontend:** grep `frontend/` and the built `frontend/dist/` for
      `VITE_` variables holding real keys and for key-shaped strings (`AIza`, `sk-`,
      `hf_`, `nvapi-`, long base64/JWT `eyJ`). Confirm `.env` is gitignored and never
      committed (`git log --all -- .env`).
- [ ] **Redaction bypass:** trace every path from message intake to the classifier,
      Nemotron, Gemini and any outside service. Redaction must run first on every path.
- [ ] **External calls that skip the cache layer:** grep for `httpx`, `requests`,
      `aiohttp`, `urllib`, SDK clients and `openai`/`google` imports outside `cache.py`
      and the integration modules.
- [ ] **Payload drift:** anything sent to Nemotron or Gemini that has fields beyond
      `DATA_SPEC.md` sections 3 and 4.1.
- [ ] **Contract drift:** diff `contracts.py` and `types.ts` against `DATA_SPEC.md`
      field by field (names, optional/required, enums).
- [ ] **Display-shaped data:** SQLite tables or Pydantic models built around one screen,
      duplicated fields, or values that are stored but should be derived.
- [ ] **Untrusted output in the UI:** any phone number, URL or `href` rendered from
      model output or search results; `dangerouslySetInnerHTML`; `javascript:` links.
- [ ] **Actions without consent:** any code path that takes a protective or money action
      without an explicit customer tap.

# Part 2: Code smells common in AI-written code
- [ ] Files over ~250 lines, or functions over ~50, that do more than one job.
- [ ] Duplicate or near-duplicate functions (helpers rewritten per module, copy-pasted
      prompt building, repeated HTTP/retry logic).
- [ ] Dead code: unused functions, modules, components, routes, env vars, dependencies.
- [ ] `TODO` / `FIXME` / `pass` / `...` / `NotImplementedError` stubs presented as
      finished work, and functions that return hard-coded values.
- [ ] Inline mock or fixture data in app code where it should come from SQLite, the
      cache or fixtures. Any data that looks like a real person (not synthetic).
- [ ] Hollow error handling: bare `except:`, `except Exception: pass`, swallowed
      errors, missing loading/error states around frontend fetches.
- [ ] Type escape hatches: `Any`, `# type: ignore`, `as any`, `@ts-ignore`, `!`
      non-null assertions. Check `strict` in `tsconfig.json`.
- [ ] Pydantic smells: plain `dict` instead of models at API boundaries, missing
      validation constraints, v1-style APIs (`.dict()`, `validator`).
- [ ] FastAPI smells: business logic in route handlers, blocking I/O in `async`
      routes, inconsistent response models, CORS set to `*`.
- [ ] Magic numbers and thresholds scattered in code instead of one config.
- [ ] Prompt text hard-coded in Python instead of living in `prompts/`.
- [ ] `print` or logging of message bodies, keys or unredacted user text.
- [ ] Tests that assert nothing meaningful, or mock the very thing under test.
- [ ] Code that breaks the "no new infrastructure" rule (Docker, Postgres, vector DBs,
      WebSockets).

# Part 3: Mechanical checks (run them, report the output summary)
Backend, from `backend/`:
- `python -m pytest -q`
- `ruff check .` (also `ruff check --select C90,PLR,SIM,B,ARG,ERA .` for complexity,
  bugbear, unused args, commented-out code)
- `mypy app` or `pyright app`
- `vulture app --min-confidence 70` (dead code)
- `pip-audit`
- `semgrep --config p/python --config p/secrets .` if it installs

Frontend, from `frontend/`:
- `npm run build`, then search `dist/` for key patterns
- `npx tsc --noEmit`
- `npx eslint .` (if there is no config, say so and suggest a strict one)
- `npx knip` or `npx depcheck` (unused files and dependencies)
- `npm audit --omit=dev`

Whole repo: `npx gitleaks detect` or `trufflehog git file://.` for secrets in history.

# Part 4: Smoke tests to propose (don't write them yet)
Propose 3 to 5 end-to-end smoke tests for the core flows from `POC_MVP.md`, for example:
a scam message is redacted, then classified and shown with its reasons; a safe message is
not flagged; a protective action happens only after a tap; the app runs fully in
`DEMO_MODE=replay` with no network; no outside phone number or link appears in the UI.
For each one, say whether pytest (API level) or Playwright (UI) fits better.

# Report format
1. **Summary:** overall health and the top 5 things to fix first.
2. **Findings table:** ID · Severity · Area · Finding · Evidence (file:line) · Fix.
   Note the owner from the issue's Files section (Arnav or Lavanya) so I know whose
   module it is.
3. **Needs manual check:** anything you couldn't verify, with exact steps for me.
4. **Tool results:** a short summary of each command above (pass/fail, counts).
5. **Fix plan:** in recommended order, grouped by owner. Wait for my approval.
