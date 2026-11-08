# Provisional train split

`train.jsonl` holds 18 synthetic messages written by hand (A10, 2026-11-07) so `check_link`'s blocklist can be built and tested before A1 saves the real train split. Each line is a `contracts.Message`.

- All senders, domains and amounts are made up. No real person's data.
- It deliberately leaves out the three demo scenarios' domains.
- It is a stand-in for the **train** split only. Never use it for scoring.

When A1's split lands at `data/splits/train.jsonl`, `python -m scripts.build_blocklist` uses it automatically. Rebuild the blocklist then and delete this folder.
