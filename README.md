# FinEdvise — Source Code & Project README

**Tagline:** *Smarter Financial Decisions for Education.*  
**Team identity:** An AI-driven team helping private educational institutions make better financial decisions, manage uncertainty, and grow sustainably.  
**Release:** `v3.0.0`  
**Competition track:** SME Finance Copilot (Topic E)

## 1. Project overview

FinEdvise is a bilingual (English/Bengali) finance copilot prototype for private educational institutions. It helps school owners reason about cash flow, test financial scenarios, compare financing options, manage school records, and plan school activities. Financial calculations are performed by deterministic Python code; the language model is an optional conversational interface and does not authorize payments or other prohibited actions.

**GitHub repository:** https://github.com/SMMahmudH/FinEdvise  
**Source-code snapshot:** `FinEdvise_v3.0.0.zip`  
**License:** MIT — see [`LICENSE`](LICENSE).

> **Important:** The source-code ZIP is the deliverable snapshot. Push the same files to the GitHub repository before submitting the repository link, so the public repository and attached snapshot refer to the same version.

## 2. Main capabilities

- Owner registration and sign-in, school-specific workspaces, session handling, and owner-managed team roles.
- Editable school records, including students, staff, income, expenses, and inventory, with search and pagination.
- Deterministic cash-flow forecasts, safe-to-spend calculations, stress tests, admission-plan comparisons, break-even analysis, and financing comparisons based on the included synthetic scenario.
- Copilot responses in English and Bengali, with a rule-based mode and optional Gemini integration.
- Policy checks, approval workflow, numeric guardrails, pseudonymisation, and hash-chained audit evidence.
- Activity-planning suggestions for events such as picnics, class parties, school feasts, sports days, decoration refreshes, and playground repairs.
- Optional privacy-conscious Google Programmable Search integration for general research references.
- Sample security evidence and red-team results in [`evidence/`](evidence/).

## 3. Quick start (local evaluation)

### Requirements

- Python 3.9 or newer.
- No third-party Python packages are required for the core application; it uses the Python standard library and plain HTML, CSS, and JavaScript.
- Internet access is only needed for optional external AI/search integrations.

### Run

1. Download and extract `FinEdvise_v3.0.0.zip`, or clone the repository after its files have been pushed to GitHub.
2. Open a terminal in the project root—the folder containing `run.py`.
3. Run:

   ```bash
   python run.py
   ```

   On Windows, `py run.py` can be used if `python` is not available as a command.
4. Open <http://127.0.0.1:8000> in a browser.
5. Press `Ctrl+C` in the terminal to stop the server.

To use another port:

```bash
python run.py --port 9000
```

Then open <http://127.0.0.1:9000>.

### Clone from GitHub

Run after the repository contains the committed source code:

```bash
git clone https://github.com/SMMahmudH/FinEdvise.git
cd FinEdvise
python run.py
```

### Judge demo account

For a controlled local presentation, the pre-seeded synthetic demo is:

- **School:** Golapgonj Ideal Public School
- **Email:** `demo@golapgonj.edu.bd`
- **Password:** `ASDzxc123!@#`

The local loopback configuration enables the demo account by default. The demo contains fictional student, staff, finance, tuition, inventory, and planning data. Do not enter real student, guardian, payroll, or school financial information into this shared account.

To disable the shared demo account explicitly:

```bash
FINEDVISE_ENABLE_DEMO_ACCOUNT=0 python run.py
```

PowerShell equivalent:

```powershell
$env:FINEDVISE_ENABLE_DEMO_ACCOUNT="0"
python run.py
```

A newly registered school receives a separate blank workspace and must add its own records and assumptions.

## 4. Configuration

The app reads environment variables and can load them from a local `.env` file next to `run.py`. Start from the safe template:

```bash
cp .env.example .env
```

On Windows, copy `.env.example` to `.env` manually or run `Copy-Item .env.example .env` in PowerShell. Keep `.env` private and never commit it.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Optional Gemini integration. Keep the key server-side; never place it in frontend code. |
| `FINEDVISE_GEMINI_MODEL` | Ordered comma-separated Gemini model IDs to try. |
| `FINEDVISE_THINKING_LEVEL` | Optional model thinking configuration. |
| `FINEDVISE_GOOGLE_CSE_API_KEY` | Optional Google Programmable Search API key. |
| `FINEDVISE_GOOGLE_CSE_CX` | Optional search-engine ID. |
| `FINEDVISE_ENABLE_DEMO_ACCOUNT` | `1` enables the shared synthetic demo; `0` disables it. If unset, it defaults on for loopback only. |
| `FINEDVISE_COOKIE_SECURE` | Set to `1` only when correctly configured HTTPS is enforced end-to-end. |
| `FINEDVISE_HOST` | Server bind address; defaults to `127.0.0.1`. |
| `PORT` | Server port; defaults to `8000`. |
| `FINEDVISE_VAR_DIR` | Location for the persistent workspace database and logs. |
| `FINEDVISE_QUIET` | Set to `1` to reduce routine request logs. |

### Optional Gemini mode

1. Create a key through Google AI Studio: <https://aistudio.google.com/apikey>.
2. Put the key in `.env` as `GEMINI_API_KEY=...`.
3. Restart the application.

Without a key, the app uses rule-based responses over the existing tools. Before enabling an external provider with real school data, review the provider's data-use terms and obtain the appropriate legal/privacy approvals.

### Optional web research

Set both `FINEDVISE_GOOGLE_CSE_API_KEY` and `FINEDVISE_GOOGLE_CSE_CX` to enable Google Programmable Search references. Leave them unset to keep web search disabled. Search results may be incomplete or inaccurate and must be checked against authoritative sources. Personal or sensitive school data should not be submitted to external search or AI services without an appropriate legal and privacy basis.

## 5. Docker deployment (controlled demo only)

Build the image from the project root:

```bash
docker build -t finedvise:3.0.0 .
```

For an isolated local judge demo only, explicitly enable the pre-seeded demo and persist the app's `var` directory in a volume:

```bash
docker run --rm -p 8000:8000 \
  -e FINEDVISE_ENABLE_DEMO_ACCOUNT=1 \
  -v finedvise-var:/app/var \
  finedvise:3.0.0
```

Then open <http://127.0.0.1:8000>.

The container listens on `0.0.0.0` internally. **Do not expose this demo configuration to the public internet.** For any shared deployment, disable the demo account, put the service behind a reviewed HTTPS reverse proxy, configure secure cookies and persistent storage, implement tested backup/restore, and complete an independent security and privacy review. This repository is a prototype, not a hardened production deployment recipe.

## 6. Automated tests

Run the complete standard-library test suite from the project root:

```bash
python -m unittest discover -s tests -t .
```

Expected result for this release: **123 tests pass**. Re-run the command in your own environment and include your actual test output in the final evidence; results can differ if code or configuration has changed.

`pytest` can also run the same `unittest` tests if it is installed:

```bash
pytest
```

### Test coverage by suite

| Test file | Main coverage |
|---|---|
| `tests/test_data.py` | Source data validation and internal data consistency. |
| `tests/test_engine.py` | Cash-flow engine, safe-to-spend, stress scenarios, plans, and break-even calculations. |
| `tests/test_financing.py` | APR calculations, financing eligibility, arrival timing, and weakest-week checks. |
| `tests/test_guardrail.py` | Numeric guardrails, including Bengali digits and amount formatting. |
| `tests/test_agent.py` | Copilot tool flow, model fallback, and policy interaction. |
| `tests/test_policy_audit.py` | Role permissions, approval integrity, and chained audit behavior. |
| `tests/test_import_memo_redteam.py` | CSV import checks, memo escaping, and adversarial-input scenarios. |
| `tests/test_server.py` | HTTP routes, authentication, school isolation, API roles, and security headers. |
| `tests/test_workspace_data.py` | Blank workspace initialization and school-specific saved records. |
| `tests/test_envfile.py` | `.env` parsing behavior. |
| `tests/test_sandbox_evidence.py` | Reproducible sandbox evidence generation. |

### Regenerate security/sandbox evidence

```bash
python -m finedvise.sandbox --rule-based
```

Review `evidence/README.md` for the evidence file descriptions. The included red-team result file reports the prototype's rule-based test suite; it is not a substitute for independent penetration testing.

## 7. Project structure

```text
FinEdvise_v3.0.0/
├── run.py                         Application entry point
├── README.md                      Setup, deployment, tests, and limitations
├── UPDATE_NOTES_v3.0.0.md         Release notes
├── Dockerfile                     Container build definition
├── .env.example                   Safe configuration template
├── web/                           Responsive English/Bengali interface
├── finedvise/
│   ├── accounts.py                Accounts, memberships, school records, record audit
│   ├── server.py                  HTTP API, sessions, roles, static-file allow-list
│   ├── engine.py                  Deterministic cash-flow and admission calculations
│   ├── financing.py               Financing cost and stress-flow analysis
│   ├── agent.py                   Copilot orchestration
│   ├── tools.py                   Tool definitions and financial tool access
│   ├── policy.py                  ALLOW / NEEDS_APPROVAL / DENY policy gate
│   ├── guardrail.py               Numeric-response validation
│   ├── pseudonym.py               Masking of recognised personal identifiers
│   ├── research.py                Optional web-search integration
│   ├── audit.py                   Hash-chained audit and ledger logs
│   └── store.py                   Sandbox state, proposals, approvals, and imports
├── data/
│   ├── school.json                Labelled synthetic finance scenario
│   ├── financing_catalogue.json   Illustrative financing catalogue and references
│   └── samples/                   Import-test sample file
├── docs/
│   ├── TECHNICAL.md               Architecture and algorithm documentation
│   └── SECURITY_SELF_ASSESSMENT.md Security controls and known risks
├── tests/                         Automated unit/integration tests
└── evidence/                      Sample sandbox logs and red-team evidence
```

## 8. Important limitations and risk notes

1. **Two data layers:** school-entered records are persisted in school-specific SQLite workspaces, while the deterministic cash-flow/admission forecast and financing model still use the separate synthetic scenario in `data/school.json`. Newly entered school records do **not** automatically update those forecast calculations. Do not present the synthetic forecast as a real school's live financial position.
2. **Synthetic demo records:** Golapgonj Ideal Public School and all associated people/financial records are fictional presentation data.
3. **Shared demo credential:** the demo username/password is intentionally included for judges. It is not a production credential; disable the demo account for deployments accessible beyond a controlled local presentation.
4. **Prototype security status:** the project has a self-assessment and automated tests, but no claim of independent audit or production compliance is made.
5. **External AI/search:** optional providers may return incorrect or outdated content. Review sources; do not send identifiable child/guardian records to external services without a reviewed privacy and legal basis.
6. **Activity budgets:** suggestions are planning estimates, not quotes or approvals. Confirm vendor pricing, child safeguarding, accessibility, allergies, water, first aid, weather, permission, and school policy before committing funds.

For the system architecture and calculation details, see [`docs/TECHNICAL.md`](docs/TECHNICAL.md). For access control, threats, controls, and known risks, see [`docs/SECURITY_SELF_ASSESSMENT.md`](docs/SECURITY_SELF_ASSESSMENT.md).

## 9. Team

**FinEdvise** — *Smarter Financial Decisions for Education.*

An AI-driven team helping private educational institutions make better financial decisions, manage uncertainty, and grow sustainably.
