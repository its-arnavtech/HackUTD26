# Agent worktrees

Arnav runs four agents at once. Two agents in one folder overwrite each other, so each agent gets its own git worktree with its own ports (`POC_MVP.md` section 12.2, `AGENTS.md` section 3). Lavanya works in her own clone on 8000 and 5173.

All worktrees share one `.git` object store: a `git fetch` in any folder updates `origin/*` for all of them. Everything untracked is per folder: `.env`, `backend\.venv`, `frontend\node_modules`, SQLite files.

| Folder | Agent | `API_PORT` | `WEB_PORT` | Branch |
| --- | --- | --- | --- | --- |
| `C:\HackUTD26` | Cursor (main checkout) | 8000 | 5173 | one per issue |
| `C:\HackUTD26-cc` | Claude Code | 8001 | 5174 | `arnav-shared` |
| `C:\HackUTD26-codex` | Codex (connections) | 8002 | 5176 | `codex-shared`, pushes to `arnav-shared` |
| `C:\HackUTD26-design` | Codex design (GPT 6 Astra) | 8003 | 5175 | one per issue |

## Create the worktrees (once)

From the main checkout, with `.env` already filled in:

```powershell
cd C:\HackUTD26
git fetch
git worktree add --detach ..\HackUTD26-cc origin/main
git worktree add --detach ..\HackUTD26-codex origin/main
git worktree add --detach ..\HackUTD26-design origin/main
Copy-Item .env ..\HackUTD26-cc\.env; Copy-Item .env ..\HackUTD26-codex\.env; Copy-Item .env ..\HackUTD26-design\.env
git worktree list
```

Then set each folder's ports from the table. For example, in `C:\HackUTD26-cc\.env`:

```
API_PORT=8001
WEB_PORT=5174
```

`git worktree list` should show the main checkout on its branch and the three new folders as `(detached HEAD)`.

## Set up each folder

Each folder needs its own Python environment and Node packages:

```powershell
cd C:\HackUTD26-cc            # or whichever folder
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install
cd ..
.\scripts\dev.ps1             # API on API_PORT, app on WEB_PORT, Ctrl+C stops both
```

`scripts\dev.ps1` reads the ports from that folder's `.env` and refuses to start if a port is already taken, which usually means another folder's `.env` has the same ports. `-BackendOnly`, `-FrontendOnly` and `-NoReload` are available.

## Branches

**Cursor and the design session** create a branch per issue. Use `--no-track` so the new branch doesn't track `origin/main`, then set its own upstream on the first push:

```powershell
git fetch
git switch --no-track -c a10-link-sender origin/main
git push -u origin a10-link-sender
```

Without `--no-track`, `git switch -c <branch> origin/main` makes `origin/main` the upstream. A plain `git push` then fails with "The upstream branch of your current branch does not match the name of your current branch", and `git pull` pulls `main` instead of your branch. If that already happened, fix it with `git push -u origin <branch>`.

**Claude Code and Codex share `arnav-shared`** (`AGENTS.md` section 4). Git won't check out one branch in two folders (`fatal: 'arnav-shared' is already used by worktree at ...`), so Codex uses a local branch with a different name:

```powershell
# C:\HackUTD26-cc
git fetch
git switch -c arnav-shared --track origin/arnav-shared

# C:\HackUTD26-codex
git fetch
git switch -c codex-shared --track origin/arnav-shared
git pull --rebase
git push origin HEAD:arnav-shared
```

Both agents run `git pull --rebase` before every commit and stage only their own files.

## Remove or recreate a worktree

```powershell
cd C:\HackUTD26
git worktree remove ..\HackUTD26-design    # add --force if it has uncommitted changes you don't need
git worktree prune                         # clears entries for folders deleted by hand
```

Copy `.env` back in and set its ports after recreating a folder.

## Verification

Checked on 2026-11-07 against a fresh clone (Linux paths, same git commands):

- `git worktree add --detach` created the three folders at `origin/main`, and `git worktree list` showed them detached.
- Copied `.env` files are ignored by git in every worktree.
- A `git fetch` in the main checkout updated `origin/main` in the other folders.
- `git switch arnav-shared` in a second folder failed as expected; `codex-shared` tracking `origin/arnav-shared` worked.
- `git switch -c <branch> origin/main` set the upstream to `origin/main` and a plain `git push` failed, which is why the per-issue steps use `--no-track`.
- `git worktree remove` and `git worktree prune` cleaned up a folder.
- `scripts\dev.ps1` ran on ports 8011 and 5181 from `.env`, the Vite proxy reached the API, and Ctrl+C stopped both servers. The CI job `dev-script` runs it on Windows for every PR.
