# Standards interop

EIDOLON's authority model (THEMIS) is deliberately built on the
**biscuit/macaroon lineage** — signed, chained, offline-attenuable capability
tokens. This page maps THEMIS to the standards it interoperates with, so an
EIDOLON delegation travels through the wider agent ecosystem rather than living
in a bespoke format.

## THEMIS ⇄ biscuit (implemented)

`eidolon.themis.interop` exports a THEMIS `Delegation` as a real **biscuit**
token and enforces it with biscuit's Datalog:

```python
from eidolon.themis.interop import delegation_to_biscuit, attenuate_biscuit, authorize_biscuit

token, root_pub = delegation_to_biscuit(delegation)          # signed biscuit (base64)
authorize_biscuit(token, root_pub, "answer-status")          # (True, "authorized")
authorize_biscuit(token, root_pub, "commit-action")          # (False, ...) — not permitted
narrowed = attenuate_biscuit(token, root_pub, ["answer-status"])  # offline attenuation (no root key)
authorize_biscuit(narrowed, root_pub, "draft-comm")          # (False, ...) — narrowed away
```

Install: `uv sync --extra biscuit`.

| THEMIS `Delegation` field | biscuit encoding |
|---|---|
| `permitted_classes` | `permitted_class("…")` facts + a token check `check if operation($op), permitted_class($op)` |
| `scope` selectors | `scope("type","value")` facts |
| `exclusions` | `exclusion("…")` facts + authorizer `deny if action_touches($b), exclusion($b)` |
| `escalation_required` | `escalation_required("…")` facts |
| `max_autonomy` | `max_autonomy("…")` fact |
| attenuation (subset-only) | a biscuit **block** adding `check if operation($op), […].contains($op)` — narrows offline, never widens |
| signature / verification | biscuit Ed25519 root key; `Biscuit.from_base64(token, root_public_key)` |

The subset-only property THEMIS enforces (and property-tests) is exactly
biscuit's guarantee: an appended block can only *add* checks, so a token can only
ever be narrowed.

## IETF "Attenuating Authorization Tokens for Agentic Delegation Chains"

The [IETF draft](https://datatracker.ietf.org/doc/draft-niyikiza-oauth-attenuating-agent-tokens/)
(and Invocation-Bound Capability Tokens) standardize precisely what THEMIS does:
identity + attenuated authorization + provenance in an append-only chain, with a
biscuit wire format for multi-hop delegation. THEMIS maps directly: root
delegation → root token; `attenuate()` → an appended narrowing block; the
chain-to-root verification → biscuit's block verification. EIDOLON's biscuit
export is the on-ramp; the delegation semantics already match.

## MCP OAuth 2.1 and A2A signed Agent Cards

- **MCP** mandates OAuth 2.1 + PKCE for HTTP transports. The EIDOLON gateway sits
  *below* this as a governing proxy; a hosted deployment would validate the MCP
  Bearer token, then apply EIDOLON authority per tool call. The principal's
  OAuth identity maps to the THEMIS `principal_id`.
- **A2A** ships signed **Agent Cards** for verifiable agent identity. A twin's
  `issued_to` agent key corresponds to an Agent Card identity; a biscuit-exported
  delegation is the *authority* that Card is permitted to exercise — the piece
  A2A's identity layer does not itself carry.

## What this buys us

- **Adoption:** an EIDOLON delegation is a standard capability token, not a
  bespoke one — it can be consumed by any biscuit verifier.
- **Multi-agent delegation:** biscuit's offline attenuation lets a twin hand a
  sub-agent a strictly narrower token with no round-trip to the principal — the
  standardized version of THEMIS `attenuate` (twin → sub-agent).
- **Positioning:** answers "why not just use the emerging agent-token standard?"
  — EIDOLON *is* on that track, and adds the fidelity axis, runtime-certified
  autonomy, data-flow taint, and attest-then-act that the token standards do not.

See `docs/review-and-related-work.md` for the full landscape.
