# SentinelAI · Steady design system

Chosen direction: warm editorial clarity, adjusted to deep ink for brand and actions. Green is reserved exclusively for the likely_safe verdict. No remote font service or CDN is needed.

## Color tokens and contrast

All tokens and Tailwind v4 @theme declarations live in src/theme.css. Ratios below use WCAG relative luminance, rounded to two decimals. All text combinations exceed AA's 4.5:1 normal-text minimum. Color never communicates the verdict alone: every verdict has an icon and words.

| Token / foreground | Background           | Contrast | Use                          |
| ------------------ | -------------------- | -------- | ---------------------------- |
| ink #233B4D        | paper #FAF8F1        | 10.95:1  | Brand, body, headings, icons |
| surface #FFFEF9    | ink #233B4D          | 11.53:1  | Primary button label         |
| muted #5C666A      | paper #FAF8F1        | 5.55:1   | Secondary text and metadata  |
| caution #795117    | surface #FFFEF9      | 6.93:1   | Large scam verdict           |
| caution #795117    | caution-bg #FBF0D7   | 6.18:1   | Scam badge                   |
| uncertain #50585E  | uncertain-bg #ECEEED | 6.22:1   | Not-sure badge               |
| safe #286044       | safe-bg #EAF3E9      | 6.50:1   | Likely-safe badge only       |
| focus #855C17      | paper #FAF8F1        | 5.58:1   | 3px focus outline            |
| chip text #344E60  | chip fill #E9EFEF    | 7.51:1   | Redacted tokens              |

Canvas: #F3F1EB. Lines: #DCDED7, decorative only. Checkbox boundaries use #6C7F89; checked controls use ink rather than green. Hovered primary: #182C3B with surface text. Disabled controls have lower opacity and are inactive, never a confidence cue.

## Typography

- Body: locally bundled Source Sans 3, Latin, weights 400 / 600 / 700.
- Headlines: locally bundled Newsreader Variable, normal style. Georgia is an emergency serif fallback, never the intended rendering.
- Fonts are package imports in src/main.tsx, emitted as local WOFF/WOFF2 assets by Vite. OFL licenses ship in public/licenses/ and dist/licenses/.
- Phone body and instructions: 18px / 1.4–1.5, minimum. Body text never scales down to fit.
- Phone headlines: 40px / 1.04, 37–38px at narrower widths. Verdict: 42px / 1.03, 38–39px at narrower widths.
- Secondary phone headings: 20–22px; recovery amount: 53px; campaign count: 58px.
- Supporting timestamps, chips, counts, and navigation labels: 12–16px. Eyebrows: 10–11px with 1.4–1.7px tracking. These are metadata, not instructions.
- Judge/gallery hero: 60–64px, down to 46–49px on small screens.

## Spacing, shape, and elevation

- Base spacing rhythm: 4px; common steps 8, 12, 16, 20, 24, 32, 40, 48.
- Phone content inset: 23px, 19–20px in the gallery or narrower viewports.
- Primary controls: minimum 54px, transfer answers minimum 50px. All actionable targets minimum 44px. Each phone screen has at most one filled primary action.
- Radii: controls 12px; cards 22px; small panels 14–18px; phone 48px.
- Card shadow: 0 3px 16px -10px at 15% ink. Phone shadow: 0 28px 64px -32px at 28% ink plus 0 2px 5px at 8% ink.
- Phone: 400 × 850px; gallery height 820px. At desktop heights below 850px it becomes 380 × 680px. Long screens scroll inside a keyboard-focusable region; text retains its size. At 1280px wide, the prototype phone is centered between two quiet explanatory columns. The gallery has three columns.

## Motion

- Hover / press: 140ms, cubic-bezier(.2,.7,.2,1). Press translates by 1px.
- Trail: each step slides up 10px and fades in over 280ms with the same easing, staggered by 130ms. The readable plan and findings remain in semantic DOM order.
- Checking: 1.6s linear spinner and 1.4s ease-in-out dot pulse. Live mock checks finish after 2.2s. The gallery holds its Checking fixture for review.
- prefers-reduced-motion: reduce disables all animation, transitions, and smooth scrolling. Trail content is fully visible immediately; checking retains the words “Checking…” and a static icon.

## Icons and accessibility

Lucide React, locally bundled, 1.65px stroke. Standard size 20–24px. AlertTriangle / CircleHelp / CheckCircle2 distinguish verdicts. LockKeyhole supports privacy; WalletCards supports account context; HeartHandshake supports recovery. The small brand mark is authored CSS, not a shield.

Native buttons, links, details/summary, labeled checkboxes, visible focus, skip link, table headers/caption, and status notices. No result percentages. Contact guidance says to use the official app or the number on the back of the card. No model/search contact links or phone numbers appear. Protective actions in this lab are simulated after a tap; checklist boxes record progress only.

Visual QA covers the 1280px projector layout and a 375px mobile viewport. This is not a formal assistive-technology audit; test with Linda-like users before claiming accessibility certification.
