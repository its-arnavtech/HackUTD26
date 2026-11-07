# Codex design 00: Design lab (start now, while setup runs)

**Tool:** Codex, model GPT 6 Astra · **Folder:** `C:\HackUTD26-design-lab` (a new folder outside the repo) · **Run:** any time, even before the scaffold exists

Paste everything below the line.

---

I'm Arnav. You're my frontend designer for SentinelAI, a scam protection app we're building at HackUTD 2026. We're competing for HackUTD's Best Design prize, and T-Mobile's judges score usability. I want the frontend to be genuinely beautiful and calm, not a generic dashboard.

Other agents are setting up the main repo in `C:\HackUTD26` right now. **Don't edit anything there.** You can read these files for context: `C:\HackUTD26\docs\POC_MVP.md` (sections 1, 2, 4.3, 4.4, 8 and 9) and `C:\HackUTD26\docs\DATA_SPEC.md` (sections 3.3, 3.4 and 5). Work only in `C:\HackUTD26-design-lab`.

## Who it's for

Linda, 67, just got a text saying her bank account will be locked in 2 hours. She's scared and not technical. In about five seconds the screen must tell her three things: is this a scam, how sure are we, and what should she do.

## Step 1: Two directions, then I pick (about 30 minutes)

Design the **result card** for scenario 1 ("Very likely a scam") in two clearly different visual directions. Show each inside a phone frame with a short rationale: palette, type, mood, and why it suits Linda. Calm and trustworthy, like a great bank or health app. No dark "hacker" look, no glowing shields, no alarm red. Show me both and wait for my pick.

## Step 2: Build the prototype in the chosen direction

Use the same stack as the real app, so it ports straight in: Vite, React, TypeScript, Tailwind.

1. `DESIGN.md`: direction, color tokens with contrast ratios (WCAG AA minimum), type scale (body at least 18px), spacing, radius, elevation, motion (durations and easing, plus a `prefers-reduced-motion` fallback), and the icon set.
2. Tailwind tokens and theme in one file.
3. A component library: PhoneFrame, MessageBubble, VerdictBadge (likely scam: amber; not sure: gray; likely safe: green, always with an icon and words), ResultCard, ActionButton (44px minimum), TrailStep, PrivacyChip (redacted tokens like `<PERSON>` as soft chips), WasThisYouCard, ChecklistItem, CampaignCard, MetricTable.
4. Screens from POC_MVP section 8: Consent, Inbox (with the "Checking…" state), Result card, How we checked (steps slide in one by one), Privacy panel ("What we checked, what we never saw"), Recovery ("I clicked", "Was this you?", checklist), Campaign view, and the judge-facing Accuracy page outside the phone frame.
5. A `/gallery` route showing every screen in every state: checking, each verdict, mixed evidence, recovery, empty and error.
6. Mock data as typed JSON shaped exactly like DATA_SPEC 3.3, 3.4 and 5, for all three scenarios in POC_MVP 4.3. Keep all data access in one `api.ts` that returns mocks, so the screens never fetch directly.

Rules: UI copy follows POC_MVP 4.4 (say what was checked; never "your account is fine"; no percentages inside the phone). One primary action per screen, at most three actions on the result card. It must look great on a projector at 1280px wide, with the phone centered.

## Step 3: Hand off

Write `HANDOFF.md`: the file list, which components map to which screen, and anything the real contracts will need. When the repo's `C:\HackUTD26-design` folder and issues A7, A14, A15 and A16 exist, I'll start you on `prompts/design-01-frontend.md`, and you'll port this prototype in instead of redesigning.

Show me screenshots of the gallery as you finish each screen.
