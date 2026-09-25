# Known issues (backlog)

Issues found while integrating EIDOLON into 1337 Factory
as its governance layer. They are recorded here to be fixed in a dedicated pass,
not piecemeal. Each entry names the code, the failure, and a suggested direction.

Severity: **High** means authority or audit integrity can be bypassed in a reachable
configuration. **Medium** means a real gap with a mitigation or narrow reach.
**Low** covers hygiene and developer experience.

| # | Severity | Area | Summary |
|---|---|---|---|
| 1 | High | API | `/resolve` trusts caller-supplied BASANOS certificates |
| 2 | High | API | Server runs fully open when no auth token is set |
| 3 | Medium | API | Private keys cross HTTP (`/keypair`, signing keys in request bodies) |
| 4 | Medium | Hook | Claude Code hook fails open by default |
| 5 | Medium | THEMIS | Revocations and heartbeats are in-memory unless on Postgres |
| 6 | Medium | KAIROS | `BudgetLedger` has no window and no persistence |
| 7 | Medium | THEMIS | Scopes are exact-value sets; no hierarchical path prefixes |
| 8 | Medium | Taint | Plain long-token pattern taints ordinary long words |
| 9 | Low | HORKOS | `Attestation` has no field to correlate with a caller's session |
| 10 | Low | Gateway | Destructive-shell classifier is private to `eidolon.api` |
| 11 | Low | Config | ~~`Settings()` silently reads `.env` from the current directory~~ (fixed) |
| 12 | Low | ETHOS | Embedders must seed precedent or routine actions escalate (undocumented) |
| 13 | Low | Packaging | ~~The gate pulls the whole web/DB/LLM stack~~ (fixed) |
| 14 | Low | API | `api/app.py` is a 1,500-line module with global singletons |
| 15 | Low | Hygiene | Stale docstring, untracked TLC traces, no mypy in CI |
| 16 | Medium | Gateway | `GovernanceEngine` has no approval path for escalated calls |
| 17 | Medium | ETHOS | Fidelity depends on argument wording: verbose calls drop to DRAFT |

Fixed while integrating (kept for the record):
- **Delegation chains were not anchored** (`fix/themis-trust-anchor`). `Themis.verify` accepted
  any self-signed root, and KAIROS attributed actions to `context.principal_id` without binding
  the chain to it. `verify` now takes the expected principal, KAIROS passes it, and
  `Themis(trusted_principals=…)` / `EIDOLON_TRUSTED_PRINCIPALS` pin roots.
- **Taint missed delimited API keys** (`fix/taint-underscore-secrets`). Secrets containing `_`
  (Stripe `sk_live_…`, GitHub `ghp_…`) never matched `\b[A-Za-z0-9]{12,}\b`. A second,
  letters-and-digits pattern now captures them.
- **#11, `.env` read from the current directory** (`fix/library-settings-and-extras`). `Settings`
  reads the process environment only. The platform server opts in to `.env` when `eidolon.api`
  is imported (`use_env_file()`), and anyone can name a file with `EIDOLON_ENV_FILE`.
- **#13, the gate pulled the whole stack** (`fix/library-settings-and-extras`). The core install
  is what an embedded gate needs (pydantic, cryptography, PyNaCl, PyYAML, httpx). FastAPI,
  uvicorn and SQLAlchemy moved to `[server]`; SQLAlchemy, pgvector and psycopg to `[postgres]`;
  anthropic to `[style]`; `[platform]` installs all three. The Docker image and CI install
  `[platform]`. A core-only install imports every module 1337 Factory uses.

---

## 1. `/resolve` trusts caller-supplied certificates (High)
`api/app.py` `resolve()` takes `certificates: list[Certificate]` from the request body and
passes them to `Kairos.resolve`. BASANOS ceilings derive from those certificates, so a caller
can claim `agreement=1.0` on any class and lift its autonomy ceiling. The endpoint is admin-gated,
but see #2. **Direction:** look certificates up server-side by principal/twin (they are already
produced by `/certify`) and ignore or reject caller-supplied ones.

## 2. Server runs fully open without tokens (High)
`api/auth.py` `current_role()` returns `"admin"` for every request when neither
`EIDOLON_ADMIN_TOKEN` nor `EIDOLON_AUDIT_TOKEN` is set. It logs a warning once. Combined with
#1 and #3, anyone who can reach the port can mint, resolve and approve. **Direction:** refuse to
bind a non-loopback address in open mode, or require an explicit `EIDOLON_OPEN_MODE=1`.

## 3. Private keys cross HTTP (Medium)
`POST /keypair` returns a signing key. `/delegations/mint`, `/delegations/attenuate` and
`/escalations/{id}/approve` accept `signing_key` in the body. Keys end up in proxies, logs and
browser history. **Direction:** keep principal keys client-side and accept pre-signed
delegations and approvals, or hold keys server-side behind a KMS reference.

## 4. Claude Code hook fails open (Medium)
`integrations/claude_code/eidolon_hook.py` allows the tool call when the gate is unreachable
unless `EIDOLON_HOOK_STRICT=1`. A stopped or unreachable gateway silently disables governance.
**Direction:** default to strict. Allow opt-out for demos only.

## 5. Revocations and heartbeats are process-local by default (Medium)
`RevocationStore` is in-memory. Only `PostgresRevocationStore` survives restarts or is visible
to other processes, so a revocation issued in one process does not reach an agent governed in
another. 1337 Factory ships a file-backed store (`factory/governance/revocations.py`: an
append-only file re-read on change). **Direction:** upstream a file/SQLite store for
single-box, non-Postgres deployments.

## 6. `BudgetLedger` has no window and no persistence (Medium)
`kairos/types.py` `BudgetLedger` is a flat in-process counter. `egress_per_window` never
resets, and every process starts from zero. **Direction:** windowed counters in the same
durable store as revocations.

## 7. Exact-value scopes; no path prefixes (Medium)
THEMIS scope selectors are sets matched by exact value (`_authorize_action`, `_assert_subset`).
A grant of `path: ["src"]` cannot authorise `src/a.py`, and attenuation cannot narrow `src` to
`src/billing` (not a subset). Consumers map concrete paths onto granted prefixes themselves
(1337 Factory: `factory/governance/tools.py::scope_path`). **Direction:** typed selectors,
e.g. `path` with prefix-containment semantics for both authorisation and subset checks,
normalised and symlink-safe.

## 8. Taint false positives on long words (Medium)
`gateway/taint.py` `\b[A-Za-z0-9]{12,}\b` taints any 12+ letter word in a sensitive read
(`configuration`, `Authorization`). A later egress call containing that word is denied as
exfiltration. **Direction:** require character-class mixing or an entropy threshold, as the
delimited-token pattern now does.

## 9. Attestations can't be correlated to a caller session (Low)
`sage/port.py` `Attestation` carries principal, class and chain, but no caller-provided
correlation (session/task id). 1337 Factory binds this out of band with a context variable
inside its SAGE port. **Direction:** an optional `correlation: dict[str, str]` field passed
through `Context`.

## 10. Destructive-shell classifier is private (Low)
`api/coding_agent.py` `_DESTRUCTIVE_PATTERNS` / `classify()` split `Bash` into
`destructive-command`. Importing it pulls the web stack (`eidolon.api.live`, `hosted`), so
consumers copy the list. **Direction:** move it to `eidolon.gateway` (e.g.
`gateway/coding.py`) with the native tool map.

## 11. `Settings()` reads `.env` from the CWD (Low) — fixed
`config.py` sets `env_file=".env"`. An application embedding EIDOLON inherits whatever `.env`
sits in its working directory. **Direction:** only read `.env` in the server entrypoints.
Library construction should take explicit settings (consumers currently pass `_env_file=None`).

## 12. ETHOS needs seeded precedent (Low)
With an empty SAGE partition, ETHOS confidence falls below threshold and routine actions
escalate. Embedders must seed short tool-echoing memories, as `api/coding_agent.py::_SEEDS`
does, but this is undocumented. **Direction:** document it, or let a profile declare baseline
precedent per class.

## 13. Packaging: the gate pulls the whole stack (Low) — fixed
Core dependencies include `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg`, `pgvector`
and `anthropic`, although THEMIS/KAIROS/HORKOS and the gateway engine need none of them.
**Direction:** an `eidolon-core` distribution (or `[server]`, `[postgres]`, `[style]` extras).

## 14. `api/app.py` monolith (Low)
Around 1,500 lines mixing the gate API, SaaS accounts, SSO, dashboards and demos, with
module-level singletons (`_runtime`, `_escalations`), so it is single-process only.
**Direction:** split routers by surface and inject the runtime.

## 15. Hygiene (Low)
- `basanos/__init__.py` docstring says the integrity face raises `NotImplementedError`; it is implemented.
- ~150 untracked `formal/*TTrace*` files from TLC runs: add them to `.gitignore`.
- mypy is configured (`strict = false`) but not run in CI.

## 16. `GovernanceEngine` has no approval path (Medium)
`gateway/engine.py` `GovernanceEngine.decide` returns `ESCALATE` but offers no way to re-resolve
the same call under a signed approval. `Kairos.resolve_with_approval` needs the exact `Action` and
`Context` that `decide` built internally, and those include the dynamic exclusions from taint,
purpose and org policy. 1337 Factory rebuilds them by mirroring `decide`'s private logic
(`factory/governance/approvals.py`), reading `_policies`, `_taint`, `_purpose`, `_org_policy`,
`_kairos` and `_chain`. Any change to `decide` silently desynchronises that copy, and a stale
copy could drop a taint exclusion from an approved call. **Direction:**
`GovernanceEngine.decide_with_approval(tool, arguments, approval)`, or have `decide` return the
built `Action` so callers can sign and resolve it without reimplementing the construction.

## 17. Fidelity depends on argument wording (Medium)
ETHOS evidence strength (`ethos/judgment/engine.py` `_evidence_strength`) is a sum of lexical
Dice scores between the call's query (`call tool X with <argument summary>`) and recalled
memories, with fixed thresholds (`_STRONG_EVIDENCE = 1.5`, `_SOME_EVIDENCE = 0.6`). Dice shrinks
as the query gains distinct tokens, so the *same* in-grant tool can act or drop to DRAFT (which
doesn't act) depending on how wordy its arguments are. Measured from 1337 Factory:
`Read`/`Write`/`Edit`/`Bash` with realistic arguments stay strong, but an Agent SDK
`StructuredOutput` call carrying a full multi-field answer lands on DRAFT, so the agent's final
answer is silently refused. The factory works around it by seeding field-aware precedent
(`FactoryAuthority.seed_structured_output`). **Direction:** for capability-governed profiles
(e.g. coding-agent), ground fidelity in the action class and target rather than the free-text
argument summary, or normalise Dice by the memory side only, so argument verbosity can't flip a
decision.

