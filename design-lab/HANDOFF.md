# SentinelAI design lab · Handoff

The selected Steady direction is implemented in Vite, React, TypeScript, and Tailwind v4. Deep ink is the brand/action color. Green is reserved for likely_safe. Source Sans 3 and Newsreader are bundled locally, with font licenses included.

Everything is isolated in C:\HackUTD26-design-lab. No file in C:\HackUTD26 was edited. The original two concepts remain in concepts/ and screenshots/01–03.

## Run and review

```powershell
Set-Location C:\HackUTD26-design-lab
npm.cmd ci
npm.cmd run dev
# http://127.0.0.1:5187/result
# http://127.0.0.1:5187/gallery
# http://127.0.0.1:5187/accuracy
npm.cmd test
npm.cmd run build
npm.cmd run preview
```

Use the screen navigation beside the centered phone, the three scenario links, or the gallery filters. Phone content scrolls independently on long screens. The gallery holds Checking so it can be reviewed; the standalone inbox resolves after 2.2 seconds.

## File list

| File                            | Purpose                                                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| package.json, package-lock.json | Scripts and locked dependency tree                                                                                   |
| index.html, public/favicon.svg  | Application entry and authored mark                                                                                  |
| vite.config.ts, tsconfig.json   | Vite/React/Tailwind and strict TypeScript configuration                                                              |
| src/main.tsx                    | React entry, local font imports, stylesheet                                                                          |
| src/theme.css                   | All color/type/spacing/radius/elevation/motion tokens, Tailwind @theme, styles, breakpoints, reduced-motion fallback |
| src/types.ts                    | DATA_SPEC 3.3 / 3.4 / 5 plus UI envelope types                                                                       |
| src/data/mocks.ts               | Authored scenarios, variants, privacy, recovery, campaigns, illustrative metrics                                     |
| src/api.ts                      | Sole data-access boundary; no screen fetches directly                                                                |
| src/hooks.ts                    | Async loading hook with cancellation guard                                                                           |
| src/components.tsx              | Reusable UI primitives listed below                                                                                  |
| src/App.tsx                     | Routes, centered desktop stage, screen/scenario navigation                                                           |
| src/screens/Consent.tsx         | Account-link and skip states                                                                                         |
| src/screens/Inbox.tsx           | Inbox, live Checking, empty/error variants                                                                           |
| src/screens/Result.tsx          | All verdicts, mixed evidence, result error, tapped-action receipts                                                   |
| src/screens/Trail.tsx           | Bank, billing, recovery re-plan; progressive trail and expandable reasons                                            |
| src/screens/Privacy.tsx         | Redaction, model boundaries, session-only data/storage explanation                                                   |
| src/screens/Recovery.tsx        | I clicked → transfer review → checklist and completion                                                               |
| src/screens/Campaigns.tsx       | Pattern summary, expanded template/guidance, empty state                                                             |
| src/screens/Accuracy.tsx        | Judge page, dataset selector, per-category comparison, FPR, redaction cost                                           |
| src/screens/Gallery.tsx         | 20 phone states and the judge screen outside the frame                                                               |
| src/api.test.tsx                | Contract, fixture integrity, consent, mock action, and no-percentage checks                                          |
| public/licenses/*.txt           | Font OFL licenses, copied to production output                                                                       |
| DESIGN.md                       | Tokens, calculated AA contrast ratios, type/spacing/motion/icon decisions                                            |
| screenshots/*.jpg               | Verified 1280px gallery groups, standalone desktop, mobile, accuracy                                                 |
| concepts/*                      | Archived direction-selection HTML/CSS/JS; not part of the React app                                                  |

## Component-to-screen map

| Component                                             | Screens                                                    |
| ----------------------------------------------------- | ---------------------------------------------------------- |
| PhoneFrame                                            | Every phone screen, standalone and gallery                 |
| MessageBubble                                         | Result; redacted message text or a short authored excerpt  |
| VerdictBadge                                          | Inbox and Result; amber/gray/green with icons and words    |
| ResultCard                                            | Scam, unsure, safe, mixed, and billing results             |
| ActionButton                                          | Consent, Inbox, Result, Recovery, error, Campaign detail   |
| TrailStep                                             | How we checked; bank, billing, recovery                    |
| PrivacyChip                                           | MessageBubble, Privacy, Campaign redacted template         |
| WasThisYouCard                                        | Recovery transfer review                                   |
| ChecklistItem                                         | Recovery checklist and complete state                      |
| CampaignCard                                          | Campaign overview/detail                                   |
| MetricTable                                           | Judge-facing Accuracy page, including the gallery specimen |
| PageTitle, Notice, EmptyState, PrivacyFootnote, Brand | Shared supporting primitives                               |

## Data fields required by the screens

The core AgentResult matches DATA_SPEC 3.3: plan, verdict, confidence_words, reason, evidence[{tool,finding}], actions, was_this_you, replan. The trail matches 3.4: step, kind, optional tool, why, finding, ms, at. Redaction matches section 5: counts{PERSON,PHONE,ACCOUNT_DIGITS,ADDRESS,EMAIL}, kept.

| Screen         | Additional display fields                                                                                                                                                                 |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Inbox          | id, brand, text, optional preview, received_at, status, verdict; authored marks lab fixtures                                                                                              |
| Result         | AgentResult plus activity_summary and next_step; these are trusted display summaries, not new Nemotron contract fields                                                                    |
| How we checked | TrailEntry[] plus selected scenario/message reference                                                                                                                                     |
| Privacy        | text_redacted, redaction report, recipients[{name,received[],never[]}], stored[], session_only[]                                                                                          |
| Was this you   | A separately resolved Transaction: ref, type, amount, payee, at, minutes_after_message, new_payee. Full payee details stay in the UI adapter and must not go back to Nemotron             |
| Checklist      | id, label, detail, action; customer-owned checked IDs                                                                                                                                     |
| Campaign       | id, brand, count_today, first_seen, template, example_redacted, message_ids, report publisher/date/claim                                                                                  |
| Accuracy       | dataset, sample_size, rows[{category,support,baseline{precision,recall,f1},sentinel{precision,recall,f1}}], false_positive_rate{baseline,sentinel}, redaction{before,after}, illustrative |

Amounts, dates, and campaign counts are fixture data in the mock boundary. Transfer time, message time, and first-seen date are formatted in America/Chicago. No source/phone/contact URL is displayed in the phone; public guidance is attributed with publisher and date. Current public guidance is explicitly authored, not a retrieved citation.

## Backend adapter mapping for the later port

| Mock API method        | Real API boundary                                                                                                           |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| getInbox               | GET /api/inbox                                                                                                              |
| runCheck / getScenario | POST /api/messages, then poll GET /api/messages/{id}/result every second; select actual message IDs instead of scenario IDs |
| getPrivacy             | GET /api/privacy/{id}; build received/never groups from actual boundary logs                                                |
| getRecovery            | POST /api/messages/{id}/clicked, then poll result and resolve was_this_you references for UI display                        |
| confirmTransaction     | POST /api/transactions/{ref}/confirm with was_me, only after a tap                                                          |
| performAction          | POST /api/actions with message_id and allowlisted action, only after a tap                                                  |
| getCampaigns           | GET /api/campaigns                                                                                                          |
| getMetrics             | GET /api/metrics; adapt eval/metrics.json without changing the model payload contracts                                      |

Keep the existing backend enum guardrails and contact stripping. The phone action labels are authored UI text. Replace mocks in api.ts; screens must continue to use this boundary. Wire useData.error to the existing error screens when network requests are introduced. Do not make changes to the main repo's shared contract files during a visual port; reconcile those in the separately reviewed contracts PR required by AGENTS.md.

## Prototype behavior and limits

- All three scenarios are authored fixtures, excluded from training. There are no external model, bank, SMS, search, or account calls.
- The demo initially assumes a linked fixture account. Consent can simulate linking or skipping. Skipping removes bank/bill checks from scam results and offers linking before recovery activity review. Gallery states are specimens of the seeded scenarios; link again to restore the full fixture after trying skip.
- Block/report receipts are simulated after an explicit tap. “Use the official app” gives instructions and never launches a model-generated link.
- “Was this you?” records a simulated answer. Checklist boxes only record progress in React state, reset when the screen remounts, and never freeze a card, change a password, or move money.
- Accuracy values are illustrative, conspicuously labeled. Replace all evaluation fixtures with measured results before judging. Per-category classifier values do not imply agent verdict accuracy.
- Recovery guidance and campaign text are authored demo copy; replace supporting public evidence with actual grounded publisher/date records. Keep search/model URLs out of phone UI.
- Long privacy/trail/checklist content scrolls. The design preserves 18px reading text rather than compressing it. Keyboard users can focus the scroll region.

## Validation

- npm.cmd test: 13 passing checks covering contracts, action allowlist/count, distinct evidence for strong verdicts, recovery references, different plans, no phone percentages/contact strings, consent skip, independent fixtures, simulated receipts, and illustrative metrics.
- npm.cmd run build: strict TypeScript and production Vite build pass; local font assets are present in dist/assets and licenses in dist/licenses.
- Browser checks: block receipt; both transaction answers; three checklist ticks; account-link and skip paths; Checking → completion; public/synthetic accuracy selector.
- Visual checks: gallery groups at 1280px; centered desktop phone; 375px responsive result with no horizontal overflow and 18px body text; local fonts confirmed loaded.
- Reduced-motion fallback is implemented in CSS. A real screen-reader/user study and device-level reduced-motion audit remain future validation, not claims of this prototype.
