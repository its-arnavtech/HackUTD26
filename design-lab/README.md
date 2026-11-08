# SentinelAI · Steady prototype

A local Vite + React + TypeScript + Tailwind design lab. Main repo untouched.

```powershell
Set-Location C:\HackUTD26-design-lab
npm.cmd ci
npm.cmd run dev
```

Open http://127.0.0.1:5187/gallery for all screens and states, /result for the centered interactive demo, /consent for the beginning, or /accuracy for the judge page.

Deep ink brand/actions; green only for likely safe. Source Sans 3 and Newsreader are bundled. All data is synthetic, all actions simulated. The accuracy page uses illustrative fixtures, not measured results.

See DESIGN.md for tokens and contrast ratios, and HANDOFF.md for the complete file map, data requirements, backend adapter mapping, limitations, and validation. Original direction concepts remain in concepts/ and screenshots/01–03.

Verification: npm.cmd test; npm.cmd run build. Use npm.cmd run preview to serve the production output after building.
