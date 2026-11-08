# Gemini public-report lookup

The L4/L10 implementation sends exactly the four DATA_SPEC 4.1 fields:
claimed brand, category, parsed domain, and a fixed generic lure phrase. The
tool uses the pipeline's permitted fields rather than trusting model-written
tool arguments. Customer messages, names, phone numbers and bank records are
not part of this request.

Google Search grounding is enabled through the installed Google Gen AI SDK.
Only grounding support segments with valid chunk citations become reports;
uncited generated prose is dropped. Sources are ranked official, government,
known news/security vendors, then community. Community-only results are
withheld. Known publication dates older than 90 days are marked stale;
unknown dates remain unknown. Contact numbers and domains are stripped from
claim text. Citation URLs remain tool data and are never customer contact
actions. No source URL is fetched or followed by this integration.

Implementation reference: [Google Search grounding documentation](https://ai.google.dev/gemini-api/docs/google-search).

## Configuration and actual gate result

Set `GEMINI_API_KEY` privately and `GEMINI_MODEL` in your own `.env`. The
example selects `gemini-3.5-flash`, verified present in this project's model
listing. Listing a model does not establish quota or generation access.

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_gemini --list-models
.\.venv\Scripts\python.exe -m scripts.smoke_gemini
.\.venv\Scripts\python.exe -m pytest -q tests/test_gemini.py
```

On 2026-11-08, model listing succeeded, but grounded generation returned HTTP
429 for Gemini 3.5 Flash and Flash Lite. The listed older 2.5 Flash returned
404 on generation. P3 is therefore **blocked**, not passed. An enabled model
with usable quota is needed before a live cited-result pass can be recorded.
Provider bodies and credentials were not printed or committed.

The implementation has 14 passing synthetic tests for the four-field privacy
boundary, citation requirements, source ranking, stale/unknown dates, contact
stripping, exact-domain claims, missing keys, provider errors, and strict
record/replay. The combined backend suite passes 650 tests at this checkpoint.
The authored CLI replay profile explicitly disables optional public search and
continues to work offline. Do not claim Gemini-backed public reports in the
demo or submission until the live gate succeeds.
