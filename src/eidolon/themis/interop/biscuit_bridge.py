"""THEMIS ⇄ biscuit bridge.

Exports a THEMIS :class:`~eidolon.themis.types.Delegation` as a signed **biscuit**
token that carries the same authority — permitted capability classes, scope
selectors, exclusions, and max autonomy — as Datalog facts, plus a self-enforcing
least-privilege check. Supports biscuit's native **offline attenuation** (narrow
the permitted classes without the root key) and **authorization** (allow/deny an
action via biscuit's Datalog), so an EIDOLON credential interoperates with the
capability-token standard.

Requires the optional ``biscuit`` extra (``uv sync --extra biscuit``).
"""

from __future__ import annotations

from eidolon.themis.types import Delegation


def _lazy():
    try:
        import biscuit_auth as ba
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("biscuit not installed. `uv sync --extra biscuit`") from exc
    return ba


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def delegation_to_biscuit(delegation: Delegation, private_key_hex: str | None = None) -> tuple[str, str]:
    """Export a delegation as a signed biscuit token.

    Returns ``(token_base64, root_public_key_hex)``. The public key is needed to
    parse/verify the token (and to attenuate/authorize it).
    """
    ba = _lazy()
    kp = (
        ba.KeyPair.from_private_key(
            ba.PrivateKey.from_bytes(bytes.fromhex(private_key_hex), ba.Algorithm.Ed25519)
        )
        if private_key_hex
        else ba.KeyPair()
    )
    b = delegation.body
    lines: list[str] = [
        f'principal("{_esc(b.principal_id)}");',
        f'issued_to("{_esc(b.issued_to)}");',
        f'max_autonomy("{_esc(b.max_autonomy)}");',
    ]
    for cls in b.permitted_classes:
        lines.append(f'permitted_class("{_esc(cls)}");')
    for boundary in b.exclusions:
        lines.append(f'exclusion("{_esc(boundary)}");')
    for cls in b.escalation_required:
        lines.append(f'escalation_required("{_esc(cls)}");')
    for stype, values in b.scope.items():
        for v in values:
            lines.append(f'scope("{_esc(stype)}", "{_esc(str(v))}");')
    # Self-enforcing least-privilege: the token is only valid for a permitted class.
    lines.append("check if operation($op), permitted_class($op);")

    builder = ba.BiscuitBuilder("\n".join(lines))
    token = builder.build(kp.private_key)
    return token.to_base64(), kp.public_key.to_bytes().hex()


def attenuate_biscuit(token_b64: str, root_public_key_hex: str, keep_classes: list[str]) -> str:
    """Offline attenuation: narrow the token to a subset of its classes.

    Adds a biscuit block (no root key needed) that restricts permitted operations
    to ``keep_classes`` — mirroring THEMIS's subset-only attenuation in the
    standard format. Attenuation can only ever *narrow*.
    """
    ba = _lazy()
    pk = ba.PublicKey.from_bytes(bytes.fromhex(root_public_key_hex), ba.Algorithm.Ed25519)
    token = ba.Biscuit.from_base64(token_b64, pk)
    allowed = ", ".join(f'"{_esc(c)}"' for c in keep_classes)
    block = ba.BlockBuilder(f"check if operation($op), [{allowed}].contains($op);")
    return token.append(block).to_base64()


def authorize_biscuit(
    token_b64: str,
    root_public_key_hex: str,
    action_class: str,
    *,
    scope: dict[str, list[str]] | None = None,
    touches_exclusions: list[str] | None = None,
) -> tuple[bool, str]:
    """Authorize an action against the token via biscuit's Datalog.

    Allows a permitted, non-excluded class; denies otherwise. Returns
    ``(allowed, reason)``.
    """
    ba = _lazy()
    pk = ba.PublicKey.from_bytes(bytes.fromhex(root_public_key_hex), ba.Algorithm.Ed25519)
    token = ba.Biscuit.from_base64(token_b64, pk)

    facts = [f'operation("{_esc(action_class)}");']
    for stype, values in (scope or {}).items():
        for v in values:
            facts.append(f'target("{_esc(stype)}", "{_esc(str(v))}");')
    for boundary in touches_exclusions or []:
        facts.append(f'action_touches("{_esc(boundary)}");')

    policies = [
        # An excluded boundary is a hard stop.
        "deny if action_touches($b), exclusion($b);",
        # Otherwise a permitted class is allowed (token/attenuation checks also apply).
        "allow if operation($op), permitted_class($op);",
        # Default deny.
        "deny if true;",
    ]
    ab = ba.AuthorizerBuilder("\n".join(facts + policies))
    authorizer = ab.build(token)
    try:
        authorizer.authorize()
        return True, "authorized"
    except ba.AuthorizationError as exc:
        return False, str(exc).splitlines()[0]
