# FinEdvise v3.0.0 upgrade notes

## Brand and interaction
- Product and login experience rebranded as **FinEdvise** with the tagline “Smarter Financial Decisions for Education.”
- Added responsive interface polish, current Bangladesh-time display, friendlier Copilot prompts and an activity planner for picnics, class parties, school feast/food days, sports days, decoration refreshes and playground repairs.
- Activity budgets show suggested allocations and safety/inclusiveness ideas. Saving creates a planned expense entry, not an authorization or payment.
- The Records area uses searchable, paginated tables and collapsible monthly/dues sections.
- Removed third-party font fetches from the UI to avoid an unnecessary external request on page load.

## Accounts and data separation
- Each newly registered school receives a separate empty workspace instead of copied showcase transactions and student dues.
- Added a synthetic judge-demo login for Golapgonj Ideal Public School, with populated student/staff/income/expense/fee/inventory records and the existing illustrative finance scenario.
- Demo credentials are shared by design and must only be used for a controlled local presentation. Demo mode can be disabled with `FINEDVISE_ENABLE_DEMO_ACCOUNT=0`.

## Copilot / web search
- Warmer English/Bengali help and empty-workspace guidance; current-time questions use the application server's `Asia/Dhaka` clock.
- Optional Google Programmable Search integration returns topical links only when configured, and builds generic category queries rather than forwarding raw user questions. It intentionally skips some sensitive-looking prompts.

## Important remaining limitation

School records in SQLite now remain separate per school and update record summaries, but are **not yet connected to the deterministic forecast/financing engine**, which still reads `data/school.json`. New schools see setup guidance instead of a misleading populated forecast. The forecast must not be represented as a new school's real-world position.

See `README.md`, `docs/TECHNICAL.md` and `docs/SECURITY_SELF_ASSESSMENT.md` for setup, architecture and security limitations.
