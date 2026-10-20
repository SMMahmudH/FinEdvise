# FinEdvise security self-assessment

**Version:** 3.0.0  
**Purpose:** Internal project threat review, not an external security audit.  
**Scope:** Local demo, multi-school account separation, school records, deterministic financial tools, Copilot and optional web research.

## Summary

FinEdvise is a prototype used to demonstrate school cash-flow analysis and decision support. Core risks include unauthorized access to school records, inappropriate financial actions, misleading financial numbers, and exposure of children's or guardians' personal information. The design favors limiting tool capability and checking authorization server-side rather than relying on model instructions alone.

## Main assets and controls

| Asset / risk | Current control | Remaining limitation |
|---|---|---|
| School records across tenants | Membership and school IDs scope record reads/writes; tests verify a second school cannot update another school's record | Needs independent penetration testing and a production database/operations review |
| Passwords and sessions | PBKDF2 password hashes, random session tokens stored as hashes, expiration, HTTP-only/SameSite Strict cookie | HTTP-only cookie does not replace HTTPS; full production reset/verification and email workflows need review |
| Financial actions | Existing deterministic tool-policy gate; owner-controlled approval/commit flow; model does not get an autonomous payment tool | Human owners can still make bad decisions; UI records/planned event expenses are not a connected live accounting ledger |
| Invented numbers | Response number guardrail checks financial answers against tool output and can fall back to a deterministic response | Number checks do not guarantee the meaning or framing of a sentence is correct |
| Audit tampering | Hash-chained sandbox audit/ledger logs and verification tests | A privileged operator who can rewrite the entire storage and recompute the chain can defeat an on-machine chain unless an external anchor is retained |
| Browser injection / unsafe paths | Content Security Policy, text nodes for chat and notes, fixed static-file allow-list | Requires ongoing review as routes and UI features grow |
| Google/Gemini data transfer | Optional integration; topical search uses generic queries rather than the raw message; checks skip some sensitive-looking inputs | Heuristics cannot reliably identify every personal or sensitive detail; do not send real children's data without a reviewed legal/privacy basis |
| Shared judge login | Demo credentials shown in the login UI only when demo mode is enabled | Credentials are public by design; never leave the demo account enabled on an internet-facing service |
| Outbound fonts/search | External fonts are not loaded by the UI; optional Google Custom Search is off until configured | Configuring external AI or search still sends requests to the provider; provider terms and jurisdiction must be reviewed |

## Demo data and mode

`Golapgonj Ideal Public School` is a fictional showcase account and contains synthetic student/staff, income, expense, tuition, and inventory records. Its password is intentionally shared for presentation. Use `FINEDVISE_ENABLE_DEMO_ACCOUNT=0` to disable the demo seeding/login on local development; non-loopback hosts default to demo-disabled unless explicitly enabled. Never enable this shared account on a public deployment.

New registrations get a separate school ID and empty dataset. Do not confuse the demo's forecast with a newly registered school's actual financial position: editable school records are stored in SQLite and appear in record summaries, but they do not yet feed the deterministic projection engine.

## Role and action boundaries

- Owners manage their own school's team and settings; accountants have restricted record/finance access; agents have more limited access.
- Copilot action requests still pass through the deterministic policy gate. Unrecognized tool/action names should be rejected by default.
- Posted finance actions, approval content, and ledger changes should be verified from server-side state and audit outputs, not from the model's wording.
- The school activity planner saves proposals as `planned` expense records; it does not pay vendors, send messages, or approve expenditure.

## External search notes

Google Programmable Search only runs when both API key and search-engine ID are configured. Query construction uses generic topical phrases and refuses some prompts with contact information, student IDs or sensitive action language. These checks reduce disclosure but are not a complete data-loss prevention system. Search results are untrusted content and must be cited/verified before being relied upon for legal, safety, pricing or financing decisions.

## Required before a real-school pilot

1. Put the service behind HTTPS, set `FINEDVISE_COOKIE_SECURE=1` only after confirming the proxy and cookie behavior, and restrict network access.
2. Disable the public demo account, remove the demo seeding from production state, rotate any demo credentials used elsewhere, and validate admin recovery paths.
3. Independently assess authentication, authorization, CSRF, session expiry, account reset and school-level isolation.
4. Implement validated school-specific financial assumptions and connect persisted transactions to the forecast engine only through tested, reconciled rules; test unpaid obligations separately from received cash.
5. Decide a lawful basis and guardian-consent process for children's data, minimize stored fields, establish retention/deletion rules, and review data-sharing/provider terms with qualified counsel.
6. Configure backups, off-host audit anchoring, restore tests, monitoring, incident response and database access controls.
7. Test Gemini/search integrations with representative red-team prompts in the actual deployment configuration, and review sources used for financial, safety and legal guidance.

## Verification

Run `python -m unittest discover -s tests -t .`. The tests are automated project checks, not proof of full security or legal compliance. This report is a self-assessment only.
