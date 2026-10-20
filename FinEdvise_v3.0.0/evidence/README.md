# Evidence

Everything in this folder was written by one run of `python -m finedvise.sandbox` (rule-based mode). Run it again to regenerate; with `GEMINI_API_KEY` set it runs in AI mode instead.

| File | Contents |
|---|---|
| `sandbox_execution_log.json` | Every step of the run: the forecast and alerts; each chat turn with the tools called, the policy decision and result hash for each call, the number check and the reply (Bengali replies also as shown on screen); the three approval attempts (accountant DENY, agent NEEDS_APPROVAL, owner ALLOW) and the ledger posting; the fee register import; the red-team summary; and the final hash of both logs |
| `audit_log.jsonl` | The hash-chained audit log written during the run (server time in UTC) |
| `sandbox_ledger.jsonl` | The hash-chained sandbox ledger with the approved posting |
| `decision_memo_P-0001_en.html`, `decision_memo_P-0001_bn.html` | The decision memo for the approved proposal, in English and Bengali |
| `parent_reminder_drafts.txt` | Five polite reminder drafts. Nothing was sent |
| `redteam_results.json` | 23 attacks, the state checks used for each, the verdicts, and the comparison with the version 1 keyword filter |

To check a log chain yourself:

```python
from finedvise.audit import ChainedLog
print(ChainedLog("evidence/audit_log.jsonl").verify())
```
