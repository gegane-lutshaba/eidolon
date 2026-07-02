# EIDOLON

**Sovereign delegated agency for faithful digital twins.** Built on
[SAGE](https://github.com/l33tdawg/sage). Domain-agnostic core. Beachhead
profile: `general-continuity`.

EIDOLON lets a person delegate a cryptographically bounded, revocable, fully
attributable slice of their professional authority to a digital twin that
decides the way they would. It owns the **identity-fidelity and
delegated-authority** layer on top of SAGE's consensus-validated memory
substrate. See [`docs/EIDOLON_PRD_v1.md`](docs/EIDOLON_PRD_v1.md) for the full
contract.

Two invariants override everything and are property-tested in CI:

1. **Default-deny** — any authority not explicitly granted is denied.
2. **No unattested action** — no side effect runs without a successful `HORKOS`
   attestation (attest-then-act).

## Architecture

```
            Principal (human · root identity)
               │ defines            │ mints
               ▼                    ▼
        ETHOS (fidelity)      THEMIS (authority)
               └────────┬───────────┘
                        ▼
             KAIROS  (action gate)   ◀── BASANOS (autonomy ceiling)
             act · draft · escalate
                        ▼
             HORKOS (attestation)
                        ▼
        SAGE  (consensus memory + attestation ledger)
```

| Component | Module | Responsibility |
|-----------|--------|----------------|
| **SAGE adapter** | `eidolon.sage` | The only path to SAGE. `SagePort` interface; live `SageClientAdapter` + in-memory fake. |
| **ETHOS** | `eidolon.ethos` | Fidelity core. Hard-isolated **judgment** (auditable, LLM-free) and **style** (Claude) engines. |
| **THEMIS** | `eidolon.themis` | Authority. Ed25519-signed, chained, attenuable delegation credentials (biscuit/macaroon lineage). |
| **KAIROS** | `eidolon.kairos` | The single action gate. LOCKED resolution order; attest-then-act. |
| **HORKOS** | `eidolon.horkos` | Immutable attestation on SAGE's consensus ledger. |
| **BASANOS** | `eidolon.basanos` | Certification (fidelity face). Gates the autonomy ceiling. Integrity face stubbed (v2). |
| **Capture** | `eidolon.capture` | Consent-gated ingestion of traces into SAGE. |
| **Domain Profile** | `eidolon.profile` | Declarative pack specialising the fixed core. Ships `general-continuity`. |

### Notable design decisions (enhancements over the PRD, invariants preserved)

- **Ports & adapters around SAGE.** `SagePort` isolates the substrate; an
  in-memory fake runs the whole system green offline, while the live
  `SageClientAdapter` binds the real `sage_sdk` (verified against a Dockerized
  node). Attestations map to consensus-committed memories (SAGE has no dedicated
  attest API); a record's content hash is its ledger hash.
- **Style/judgment isolation** is enforced two ways: an import-graph test proves
  `ethos.judgment` never imports `ethos.style`, and a behavioral test proves
  removing the style engine changes zero decisions.
- **One canonical serializer** (`common.canonical`) is the single hashing source
  of truth for THEMIS signing, ETHOS versioning, and HORKOS attestation.

## Quick start

```bash
uv sync --all-extras            # install (needs Python 3.12+ and uv)

# Fast lane — no external services. In-memory SAGE port.
make test                       # unit + property tests

# Live lane — real SAGE consensus node via Docker.
make up                         # starts ghcr.io/l33tdawg/sage on :8080
make test-integration           # cross-principal isolation, attest→replay, full gate

# Run the API
cp .env.example .env            # set EIDOLON_ANTHROPIC_API_KEY for Claude voice
make run                        # uvicorn on :8000
```

The style engine (drafts/escalations) uses Claude (`claude-sonnet-4-6` by
default). Without an API key it falls back to deterministic templates — **no
judgment or authority decision ever depends on the LLM.**

## API surface

`POST /keypair` · `POST /delegations/{mint,attenuate,revoke}` · `POST /heartbeat`
· `POST /resolve` (the gate) · `GET /replay` · `POST /capture/ingest` ·
`GET /profiles/{id}`. See `eidolon.api.app`.

## Status

Phase 0 + Phase 1 of the PRD are implemented and tested (65 tests: unit +
Hypothesis property tests + live-SAGE integration). Deferred to v2 (seams
stubbed): BASANOS integrity face, the `offensive-security` profile, Hermes-style
self-generated skills, and the aspirational-self layer.

## License

Apache-2.0.
