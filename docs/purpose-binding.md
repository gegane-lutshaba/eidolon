# Purpose-binding (privacy limitation)

Beyond *"is this data sensitive?"* (the [taint layer](eval-agentdojo.md)) lies
*"may this data be used **for this purpose**?"* — the GDPR-style
purpose-limitation principle that
**[ToolPrivacyBench](https://arxiv.org/pdf/2606.28061)** (Purpose-Bound Privacy in
Tool-Using LLM Agents) measures.

`eidolon.gateway.purpose.PurposeTracker` adds a **purpose dimension** to the
data-flow layer:

- A read tool declares the **purpose its data is collected for** (`ToolPolicy.purpose`,
  e.g. `get_medical_records → "treatment"`).
- When a value returned by that read flows into a tool serving a **different,
  incompatible purpose** (e.g. `send_marketing → "marketing"`), that is a purpose
  violation — even though the class/authority permits the call.
- The tracker derives a dynamic `purpose-limitation` exclusion, and the existing
  KAIROS gate **denies and attests** it. Purpose and authority compose through
  one mechanism, exactly like taint.

Compatibility is exact-match by default (strict limitation); a compatibility
function can permit declared secondary uses (e.g. `treatment → billing`).

```python
# get_medical_records (purpose="treatment") returns record R …
engine.govern("send_care_update", {"body": R})  # DRAFT   — same purpose, allowed
engine.govern("send_marketing",   {"body": R})  # DENY    — treatment data → marketing
engine.govern("send_marketing",   {"body": "generic promo"})  # DRAFT — no PHI, no violation
```

## Relation to ToolPrivacyBench

ToolPrivacyBench evaluates whether a tool-using agent leaks private data across
purpose boundaries. EIDOLON's purpose-binding is the *enforcement* mechanism for
exactly that: data carries the purpose it was collected for, and a
purpose-incompatible use is denied structurally (not by the model's judgment).
The benchmark is not pip-installable at time of writing; the mechanism is
demonstrated and tested in `tests/unit/test_purpose.py`. Wiring it as a live eval
(like [AgentDojo](eval-agentdojo.md)) is a drop-in once the benchmark is
available.

Enabled by default for any profile that declares `purpose-limitation` as an
excludable boundary (as `general-continuity` now does); toggle with
`GatewayConfig.enable_purpose`.
