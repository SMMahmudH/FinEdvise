# FinEdvise technical documentation

**Product tagline:** Smarter Financial Decisions for Education.  
**Team identity:** An AI-driven team helping private educational institutions make better financial decisions, manage uncertainty, and grow sustainably.  
**Status:** Prototype; generated figures are synthetic unless explicitly sourced and marked otherwise.

## Architecture

```text
Browser (web/; English and Bengali)
  | JSON/HTTP; finedvise_sid cookie; X-FinEdvise header on POST
  v
server.py -- sessions, role checks, security headers, school-scoped API
  |-- accounts.py -- SQLite users, memberships, records, session hashes, record audit
  |-- workspace_data.py -- blank school data vs pre-seeded demo scenario
  |-- agent.py -- rule-based routing or Gemini function calling
  |    |-- tools.py -- forecast, scenarios, proposals, financing and supporting tools
  |    |-- policy.py -- ALLOW / NEEDS_APPROVAL / DENY
  |    |-- guardrail.py -- response-number validation against tool outputs
  |    `-- research.py -- optional generic-topic Google Programmable Search
  `-- store.py / engine.py / financing.py / audit.py -- deterministic calculation and sandbox state
```

The website uses plain HTML/CSS/JavaScript and the Python application uses the standard library. Gemini and Google Search are optional outbound integrations, not runtime requirements for the deterministic interface.

## Two distinct data layers

1. **School workspace records.** SQLite tables hold users, memberships and editable school-specific records, associated with a school ID. The workspace supports students, staff, income, expenses and inventory, as well as audit entries. These records drive the transaction-summary widgets.
2. **Financial planning scenario.** `data/school.json` is the synthetic deterministic engine input for weekly cash forecasts, reserve checks, admission plans, break-even and financing matching. The Golapgonj judge account uses this scenario. A fresh registration gets a schema-valid `EMPTY_WORKSPACE` and no seeded roster/plans/cash assumptions.

**Important boundary:** newly entered SQLite records do not yet feed into `data/school.json` or the forecast engine. The cash-flow and admission projections are not live calculations of newly registered schools' transactions. Blank accounts should not rely on those estimates until proper financial-assumption entry and record-to-engine integration are implemented.

## Demo account and tenancy

The local loopback server seeds a synthetic presentation account on first initialization, unless `FINEDVISE_ENABLE_DEMO_ACCOUNT=0` is set. The login endpoint displays its public credentials when the feature is enabled. This credential is deliberately shared and unsafe for production. Non-loopback listeners default to demo-disabled when the flag is unset; Docker/local deployments should set the flag explicitly for judging.

Every signup creates a distinct school and owner membership. Authenticated requests are resolved to a school ID; record reads and mutations are scoped to that ID. Sessions are stored as hashes with expiry. Passwords use PBKDF2-HMAC-SHA256, with a random salt. Accountant and agent accounts are created within an owner's workspace and use a one-time temporary password that must be changed.

## Clock and school-activity planner

The UI displays live current time in `Asia/Dhaka` and defaults activity dates using Bangladesh time. The activity planner offers editable budget envelopes and illustrative category allocations for picnic, class party, school feast/food day, sports day, decorations and playground repair. Advice emphasizes safety, inclusiveness, re-use, getting quotes and checking actual cash headroom. Saving an activity adds an expense in `planned` status; this neither authorizes spend nor changes the forecast.

## Copilot and web references

The Copilot has English and Bengali rule-based fallbacks and optional Gemini function calling. Financial operations go through the existing deterministic tool and policy path. The model is not trusted as an authorization system. Responses are checked against tool-returned numbers and can fall back to a tool-based answer.

Google web research is disabled unless `FINEDVISE_GOOGLE_CSE_API_KEY` and `FINEDVISE_GOOGLE_CSE_CX` are configured. The server uses broad pre-written school/finance topical queries rather than forwarding the raw chat message. Prompts detected as containing contact details, student identifiers or sensitive action requests are not searched. Search snippets are untrusted references; the Copilot must not treat them as system instructions. Search availability and quality depend on the account, configuration and provider.

## Security controls and boundaries

- POST requests require the `X-FinEdvise: 1` header; session cookies are HTTP-only and SameSite Strict.
- Content Security Policy and static-file allow-listing reduce the surface for script injection and path traversal.
- Role checks are enforced on server routes; agents have restricted access, and owner-only commit/approval flow is retained.
- Audit records and the deterministic sandbox ledger use hash-chained logs, with verification tools/tests.
- Private student/guardian contact information should not be submitted to third-party services. Pseudonymisation is best-effort and not a guarantee that all user-entered content is anonymous.

This prototype's web server speaks plain HTTP. Configure HTTPS and the Secure cookie flag correctly before any shared deployment. It has not been independently audited; see `SECURITY_SELF_ASSESSMENT.md` for remaining risks.

## Running tests

```bash
python -m unittest discover -s tests -t .
```

Tests exercise deterministic calculation invariants, finance/approval controls, numeric validation, auth/session and workspace isolation, record persistence and audit, blank-workspace construction, demo seeding, and topical search query privacy.
