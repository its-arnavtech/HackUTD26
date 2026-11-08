# Codex 01: Hugging Face and Nemotron connections (Arnav's laptop)

**Tool:** Codex (local, with access to the laptop) · **Folder:** `C:\HackUTD26-codex` (ports 8002 and 5176) · **Run:** after the issues exist

Paste everything below the line.

---

I'm Arnav. You're my Codex agent for SentinelAI. On my Windows laptop (Asus Vivobook Pro, RTX 4060 Laptop GPU with 8 GB VRAM, Core Ultra 185H), you set up and verify the **Hugging Face and Nemotron connections**. My other agents work in parallel in other folders, so stay in `C:\HackUTD26-codex` and touch only the files your issues list.

## Start

1. `git fetch`. Read `AGENTS.md` (your rules, including the CHANGELOG handoff protocol in section 5), `CHANGELOG.md`, `docs/POC_MVP.md` sections 3, 7.3 and 13, and `docs/DATA_SPEC.md` section 3.
2. `gh issue list --label agent:codex --state open`. You own **A4** and **A5**. Resume from any checkpoint comment first.
3. Check the machine and report in a short table: Python version, the venv in `backend/`, git, gh, Node, and `nvidia-smi` (driver, VRAM). Ask me before installing anything system-wide (winget, CUDA, drivers). Installing pip packages into the project venv is fine.

## Branch

You share the remote branch `arnav-shared` with my Claude Code session. Follow AGENTS.md section 4, "Exception: Arnav's Claude Code and Codex (connections) share one branch", exactly: work on local branch `codex-shared` tracking `origin/arnav-shared`, push with `git push origin HEAD:arnav-shared`, run `git pull --rebase` before every commit, and stage only your own files.

## Secrets

Never print, log or commit a key. When a key is needed, tell me which variable to set in `C:\HackUTD26-codex\.env` and wait for me to say "done". For `hf auth login`, ask me to run it myself in a terminal.

## A4: Nemotron connection and tool-calling smoke test (gate P2)

1. Claim the issue (AGENTS.md section 5).
2. Check `NVIDIA_API_KEY` works: call `GET {NEMOTRON_BASE_URL}/models` and list the models with "nemotron" in the ID. Use **Nemotron 3.5 Bolt E4B** (expected ID `nvidia/nemotron-3.5-bolt-e4b`; use the exact ID the list shows). Set `NEMOTRON_MODEL`. If `nemotron-3.5-embed-1b` is listed, set `NEMOTRON_EMBED_MODEL` too and confirm one embedding call works.
3. Implement `backend/app/integrations/nemotron.py`: the OpenAI SDK with `base_url` and the model from settings, timeouts, one retry on 429 and 5xx, latency logged per call, and a `chat(messages, tools=None)` function that returns tool calls or text. Route the call through `integrations/cache.py` if Lavanya's L1 has merged; otherwise leave a `# TODO(L1): wrap with cache` at the call site.
4. Write `backend/scripts/smoke_nemotron.py`: two dummy tools (`get_bill_status(payee)` and `check_domain(domain)` returning fixed JSON), five fixed inputs, and a final answer validated against the agent result model in `contracts.py`. Print pass or fail per input and latency per step.
5. If native tool calling fails on any of the five, implement the JSON action protocol from POC_MVP.md 7.3 behind a setting, and rerun.
6. Add unit tests that mock HTTP, so CI never calls NVIDIA.
7. Post the results (pass count, protocol used, median and worst latency) as an issue comment, record the model ID and protocol in CHANGELOG Decisions, then finish with a PR.

## A5: Hugging Face connection

1. Claim the issue.
2. Make sure `huggingface_hub` is in the venv and the `hf` CLI works. Ask me to run `hf auth login`, then confirm with `hf auth whoami`. Add `HF_TOKEN` to `.env.example` (empty).
3. Find a public, real-world SMS spam dataset on Hugging Face (ham and spam labels, ideally with smishing examples), download it to `data/raw/public_sms/` with `hf download`, and record its ID, size and license in CHANGELOG Decisions. Don't commit it. Claude Code's evaluation harness (A13) uses it as a second test set.
4. Cache one small English text-classification base model (under about 150M parameters) for Lavanya's optional transformer classifier (L7). Record its exact ID and why you picked it in CHANGELOG Decisions.
5. **Optional local Nemotron fallback (time box: 45 minutes).** Get Nemotron 3.5 Bolt E4B from Hugging Face (`nvidia/Nemotron-3.5-Bolt-E4B`, or a quantized GGUF of it that fits in 8 GB VRAM). Serve it with an OpenAI-compatible local server (llama.cpp server or Ollama) on port 8080. Run `scripts/smoke_nemotron.py` against it by changing only `NEMOTRON_BASE_URL` and `NEMOTRON_MODEL`. Write `docs/LOCAL_NEMOTRON.md` with the exact steps and results. If it doesn't pass tool calling, or the time box runs out, write down why and stop.
6. Finish with a PR.

## When you're done

Tell me in three lines what works and what doesn't. Then ask whether to take overflow issues from Cursor (`agent:cursor`); start one only if I say yes, and claim it the same way.
