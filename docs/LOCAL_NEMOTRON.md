# Nemotron connections and optional local fallback

Verified 2026-11-07 on Arnav's RTX 4060 Laptop GPU (8188 MiB), driver 610.74, Windows, project Python 3.12.13, and existing Ollama 0.32.1. No system-wide software, CUDA or driver installation was performed.

## Hosted P2 result

Authenticated `GET https://integrate.api.nvidia.com/v1/models` confirms:

- `nvidia/nemotron-3.5-bolt-e4b`
- `nvidia/nemotron-3.5-embed-1b` (one synthetic embedding returned 2048 dimensions)

| Protocol | Cases passed | Median model step | Worst model step |
| --- | --- | --- | --- |
| Native tools (default) | 5/5 | 3082 ms | 3908 ms |
| JSON action fallback | 5/5 | 1128 ms | 2171 ms |

Both runs execute actual dummy tools and validate the final result with `app.contracts.AgentResult`. The runner permits one invalid-output retry; passing does not mean every first output was valid. The initial smoke prompts confused tool aliases, result schemas, and protocol envelopes. The final runner separates these instructions; use the current script for P2.

From `C:\HackUTD26-codex\backend`:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_nemotron --protocol native
.\.venv\Scripts\python.exe -m scripts.smoke_nemotron --protocol json_action
.\.venv\Scripts\python.exe -m pytest -q
```

Production loop/guardrails belong to L8, not this connection smoke. The client supplies a bounded 30-second timeout and exactly one retry on 429 or 5xx. It logs latency without message bodies or secrets. `NEMOTRON_PROTOCOL` chooses the wire protocol; native is the default. `NEMOTRON_TIMEOUT_SECONDS` and `NEMOTRON_MAX_TOKENS` are optional transport settings documented in `.env.example`.

L1 is still the cache scaffold at verification time. Calls already use its `cached_call` interface; the explicit `TODO(L1)` permits live bootstrap calls only. Record/replay fail closed until L1 is available. Never treat this as recorded offline demo readiness.

## Local artifact and exact setup

Source: [NVIDIA official Q4_K_M model](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB), revision `1db54d5b12533ff1bcaa8e42cf4c667988a1f1be`.

- File: `Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf`
- Bytes: 6180446208
- SHA-256: `c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612`
- License: OpenMDW-1.1, as recorded in the source model card.
- Download and imported Ollama data live under ignored `data/raw/local_nemotron/`.

The original shorthand HF repo in the prompt resolves to NVIDIA's current BF16 naming; this attempt used the official quantized repository above instead. No third-party model code was executed.

After the human runs `hf auth login`, reproduce the download from the worktree root:

```powershell
.\backend\.venv\Scripts\hf.exe download nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf README.md --revision 1db54d5b12533ff1bcaa8e42cf4c667988a1f1be --local-dir data/raw/local_nemotron
```

Create `data/raw/local_nemotron/Modelfile` with these contents:

```text
FROM C:\HackUTD26-codex\data\raw\local_nemotron\Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf
PARAMETER num_ctx 4096
PARAMETER num_predict 2048
PARAMETER temperature 0
```

Start an isolated instance using the already-installed Ollama. It leaves the user's default port 11434 and model directory alone:

```powershell
$env:OLLAMA_HOST = '127.0.0.1:8080'
$env:OLLAMA_MODELS = 'C:\HackUTD26-codex\data\raw\local_nemotron\ollama'
$localServer = Start-Process -FilePath (Get-Command ollama).Source -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput 'C:\HackUTD26-codex\backend\.venv\ollama-local.stdout.log' -RedirectStandardError 'C:\HackUTD26-codex\backend\.venv\ollama-local.stderr.log'
ollama create sentinel-bolt-e4b -f data/raw/local_nemotron/Modelfile
```

The import succeeded and advertised completion, tools and thinking capabilities. Run the exact same native smoke command, changing only URL and model (temporary environment overrides):

```powershell
Set-Location C:\HackUTD26-codex\backend
$env:NEMOTRON_BASE_URL = 'http://127.0.0.1:8080/v1'
$env:NEMOTRON_MODEL = 'sentinel-bolt-e4b'
try {
    .\.venv\Scripts\python.exe -m scripts.smoke_nemotron --protocol native
} finally {
    Remove-Item Env:NEMOTRON_BASE_URL, Env:NEMOTRON_MODEL
}
```

The transport uses a dummy key for loopback endpoints even when the hosted NVIDIA key remains configured. The worktree `.env` retains the hosted model/URL, native protocol, and ports 8002/5176.

## Local result

**Not selected as a fallback: 3/5 native cases passed.**

| Case | Result |
| --- | --- |
| overdue_bill | 30-second API timeout during startup |
| verify_link | 30-second API timeout during startup |
| bill_and_link | Passed; real native tool calls and schema-valid result |
| suspension | Passed; real native tool calls and schema-valid result |
| payment_claim | Passed; real native tool calls and schema-valid result |

Completed model calls had median 14278.5 ms and worst 18804 ms. These latency statistics exclude the two failed calls, which each took about 30 seconds. The GPU was sampled at 3518 MiB used during inference (not a peak measurement). The imported model reports a 4096-token context and approximately 3.3 GB resident model VRAM.

The attempted server was stopped and its model unloaded after the failed gate; downloaded/imported artifacts remain ignored on disk. The hosted `.env` remains selected. The attempt finished around 19:06 Central, within the 45-minute limit.

The optional attempt began at 18:53 Central, with a 45-minute ceiling of 19:38. Per the prompt, a failed local tool-calling gate is documented and the attempt stops; it is not selected as the demo fallback. A future separately authorized attempt can investigate cold-start time and output reliability. No system-wide upgrade was attempted.

After a failed attempt, unload only this model and stop only the separate server:

```powershell
$env:OLLAMA_HOST = '127.0.0.1:8080'
ollama stop sentinel-bolt-e4b
Stop-Process -Id $localServer.Id
Remove-Item Env:OLLAMA_HOST, Env:OLLAMA_MODELS
```

## A5 Hugging Face handoff

The human completed CLI login; both saved login and the `HF_TOKEN` in the worktree `.env` authenticate as `ItsArca`. Tokens were not printed or committed. `HF_TOKEN` was already present as an empty entry in `.env.example`.

From backend, `python -m scripts.setup_huggingface` routes bootstrap through the shared cache interface, invokes `hf download` with immutable revisions, and records local paths, bytes and SHA-256 in ignored `data/raw/public_sms/manifest.json`. It prints aggregate metadata only. All tests use synthetic file bytes.

| Artifact | Revision | Downloaded bytes | Use |
| --- | --- | --- | --- |
| `ucirvine/sms_spam` | `cae486f927c250fe1d4a5b55f11357964ed1646c` | 363852 including README; parquet 358869 | External evaluation only |
| `distilbert/distilbert-base-uncased` | `12040accade4e8a0f71eabdb258fecc2e7e948be` | 268672802 | Optional L7 encoder |

The local parquet has 5574 rows: label `0=ham` (4827), `1=spam` (747), with columns `sms` and `label`. Its upstream split happens to be named `train`; **every row is held out in SentinelAI**. Never use these messages for training, tuning, prompts, campaign seeds or blocklists. This is an older binary SMS-spam benchmark, not a labeled modern-smishing taxonomy benchmark. Aggregate counts were checked with project-venv-only pyarrow 26.0.1; no public message text is in fixtures or tests.

The [HF dataset card](https://huggingface.co/datasets/ucirvine/sms_spam) marks its license unknown. [UCI's upstream source](https://archive.ics.uci.edu/dataset/228/sms+spam+collection) lists CC BY 4.0; both facts are recorded, without relabeling the mirror's metadata.

[DistilBERT](https://huggingface.co/distilbert/distilbert-base-uncased) is an Apache-2.0 English encoder of approximately 67M parameters, below the 150M target. It has not been fine-tuned on SMS spam. Safetensors, config, tokenizer files and license/card are cached in the normal HF cache; their exact local paths are in the manifest. L7 can add a sequence-classification head and fine-tune only on allowed synthetic train data. Torch/Transformers training packages were not installed by this task. Offline consumers should pin the recorded revision and use `local_files_only=True`.
