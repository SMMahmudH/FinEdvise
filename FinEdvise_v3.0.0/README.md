# FinEdvise

**Smarter Financial Decisions for Education.**

FinEdvise is an AI-driven team and school finance copilot designed to help private educational institutions make better financial decisions, manage uncertainty, and grow sustainably. The prototype is built for the SME Finance Copilot theme: explainable cash-flow planning, financial stress tests, financing comparisons, school records, and warm bilingual school-operations guidance.

> **Demo safety notice:** Golapgonj Ideal Public School is a judge/presentation workspace filled with fictional sample records. Never enter real children, guardian, payroll, or financial data into the demo account.

## Run locally

Requirements: Python 3.9 or newer. The application uses the Python standard library and plain HTML/CSS/JavaScript.

```bash
python run.py
```

Open <http://127.0.0.1:8000>. By default, the local loopback server enables the presentation demo account and displays a button to open it on the login page.

**Judge demo login**

- School: **Golapgonj Ideal Public School**
- Email: `demo@golapgonj.edu.bd`
- Password: `ASDzxc123!@#`

The demo includes a structured synthetic roster, staff, monthly income and expense records, unpaid tuition examples, inventory, and the full illustrative admission-planning scenario. Its records are designed for presentation, not for operational use. The shared demo credential is public by design and is not suitable for a deployed production service.

## New schools start with their own blank workspace

Use **Create school account** to register an owner account. A newly registered school is assigned its own school ID, private workspace, and empty financial assumptions. It does not inherit Golapgonj's student list, transaction history, inventory, outstanding tuition, or plans. Add student and staff records, income, expenses, and inventory in **Records**; use **Activities & Events** to draft a proposed picnic, class party, school feast, sports day, decoration refresh, or playground repair budget.

The Records table has search and pagination. Month-by-month reports and tuition-owing information are collapsible on the populated demo workspace to keep larger lists easier to scan. The event planner uses the current date in Bangladesh time and offers a proposed allocation plus practical wellbeing/safety suggestions. Saving an event creates an **unpaid/planned expense record**, not an approval or payment.

## Current limitations: read before relying on numbers

The deterministic cash-flow, admission-plan, break-even, and financing engine still uses the separate synthetic scenario in `data/school.json`. Records entered into a school's SQLite workspace update its saved-record summaries, but **they are not yet inputs to that forecast engine**. A blank new school therefore sees setup guidance rather than a pretend forecast. Do not treat the demo forecast as a real school's financial advice or claim that manually entered transactions update the modelled cash forecast.

The activity planner's budget splits are editable planning guidance, not supplier quotes. Confirm current local prices, child safeguarding, permissions, accessibility, allergies, water, first aid, weather, and school policy before making commitments.

## Copilot and optional integrations

Without a model key, the app runs in deterministic rule-based mode. To enable Gemini, copy `.env.example` to `.env`, add a key from <https://aistudio.google.com/apikey> as `GEMINI_API_KEY`, and start the server again. The Copilot uses the existing policy gate and numeric guardrail. A language model's text is not itself an authorization to spend, post, delete, contact families, or apply for a loan.

Optional live web references use Google Programmable Search. Configure both `FINEDVISE_GOOGLE_CSE_API_KEY` and `FINEDVISE_GOOGLE_CSE_CX`. Search is off when these variables are not configured. The integration maps a question to a broad school/finance topic instead of forwarding the raw user message, and it skips prompts detected as private/contact data or sensitive action requests. External search can still return incomplete or inaccurate information; review sources and check official local guidance. Do not send personal school data to AI or web providers without an appropriate privacy/legal basis.

Time-sensitive UI labels use `Asia/Dhaka` and update at runtime. The current-date UI is dynamic; the finance demo dataset remains a static scenario, so its dated financial assumptions are separate from the live clock.

## Test

```bash
python -m unittest discover -s tests -t .
```

The suite covers the deterministic engine, numeric guardrail, agent fallback, policy/approval controls, authentication, school isolation, record CRUD/audit, blank workspace behavior, seeded demo data, and privacy-conscious search query generation.

## Deployment and security

This is a prototype and has **not** had an independent security audit. The built-in HTTP server should be used locally for evaluation. Before any shared deployment:

- Put the service behind a correctly configured HTTPS reverse proxy, and set `FINEDVISE_COOKIE_SECURE=1` only when HTTPS is actually enforced end to end.
- Set a strong secret/credential policy, disable the public demo account with `FINEDVISE_ENABLE_DEMO_ACCOUNT=0`, and ensure the demo seed is not exposed to the internet.
- Back up persistent state and test restore procedures; monitor logs and apply least-privilege host/database access.
- Review password reset/verification, email delivery, access-control rules, legal basis for children's data, provider data-use terms, and local data-protection obligations before real-school pilots.
- Keep `.env`, credentials, and data stores out of version control and public static paths.

To enable the demo on a local non-default setup set `FINEDVISE_ENABLE_DEMO_ACCOUNT=1`. Do not enable the shared public demo login on an internet-facing server. For Docker, explicitly choose the setting rather than assuming the demo is enabled:

```bash
docker build -t finedvise .
docker run --rm -p 8000:8000 --env-file .env -e FINEDVISE_ENABLE_DEMO_ACCOUNT=1 -v finedvise-var:/app/var finedvise
```

The Docker example is for a controlled local judging environment only; omit the demo flag for a real deployment.

## Environment variables

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Optional Gemini integration; never put the key in frontend code. |
| `FINEDVISE_GEMINI_MODEL` | Ordered list of Gemini models to try. |
| `FINEDVISE_THINKING_LEVEL` | Optional model thinking configuration. |
| `FINEDVISE_GOOGLE_CSE_API_KEY` | Optional Google Programmable Search API key. |
| `FINEDVISE_GOOGLE_CSE_CX` | Optional search-engine ID. |
| `FINEDVISE_ENABLE_DEMO_ACCOUNT` | `1` enables the pre-seeded demo; `0` disables it. Loopback defaults to enabled if unset; non-loopback hosts default to disabled. |
| `FINEDVISE_COOKIE_SECURE` | Set to `1` only behind correctly configured HTTPS. |
| `FINEDVISE_HOST`, `PORT` | Listener host and port; defaults to `127.0.0.1:8000`. |
| `FINEDVISE_VAR_DIR` | Persistent workspace, account database, and logs. |
| `FINEDVISE_QUIET` | Set to `1` to suppress routine request logs. |

The product, module namespace, runtime messages and deployment variables use **FinEdvise** throughout.

## Project structure

```text
run.py                      Start the server
web/                        Responsive English/Bengali interface
finedvise/accounts.py          SQLite users, school memberships, records and audit rows
finedvise/server.py            HTTP routes, sessions, tenant-specific workspaces
finedvise/engine.py             Existing deterministic forecast and admission calculations
finedvise/financing.py         Loan cash-flow costing and weakest-week checks
finedvise/agent.py             Copilot orchestration and numeric guardrail integration
finedvise/policy.py            Role/tier allow, approval-needed and deny rules
finedvise/research.py          Optional privacy-conscious Google Search integration
data/school.json             Clearly labelled synthetic demo scenario
docs/TECHNICAL.md           Architecture and data/forecast boundaries
docs/SECURITY_SELF_ASSESSMENT.md  Controls, limitations and deployment checks
tests/                      Automated regression and integration tests
evidence/                   Generated demo evidence
```

The Python import namespace `finedvise` remains unchanged to preserve compatibility with the existing calculation engine and tests; the product name is FinEdvise.

**Team identity:** FinEdvise — an AI-driven team helping private educational institutions make better financial decisions, manage uncertainty, and grow sustainably.
