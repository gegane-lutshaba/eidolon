"""THEMIS engine (PRD §6.3).

    mint(issuer_priv, params) -> Delegation
    verify(action, chain)     -> CredResult{valid, reason, effective}   # walks to root
    attenuate(parent, subset, issuer_priv) -> Delegation                # subset-only
    revoke(delegation_id)     -> None                                   # immediate
    heartbeat(principal_id)   -> None                                   # resets dead-man

Fail-closed everywhere: any broken signature, broken linkage, expired window,
revocation, or dead-man lapse yields ``valid=False``. Authority never widens —
:meth:`attenuate` rejects any child that broadens scope, classes, window,
autonomy, exclusions, or budget on any dimension.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

from eidolon.common import crypto
from eidolon.common.canonical import canonical_bytes
from eidolon.common.errors import AttenuationError
from eidolon.profile.schema import autonomy_rank
from eidolon.themis.revocation_store import RevocationStore
from eidolon.themis.types import (
    CredResult,
    Delegation,
    DelegationBody,
    EffectiveAuthority,
    MintParams,
)
from eidolon.types import Action


def _default_clock() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class Themis:
    def __init__(
        self,
        store: RevocationStore | None = None,
        *,
        heartbeat_ttl_seconds: int = 3600,
        clock: Callable[[], _dt.datetime] = _default_clock,
    ) -> None:
        self._clock = clock
        self._store = store or RevocationStore(heartbeat_ttl_seconds, clock)

    # -- mint -------------------------------------------------------------
    def mint(self, issuer_priv_hex: str, params: MintParams) -> Delegation:
        """Mint a root delegation signed by the principal's key.

        The issuer of a root MUST be the principal (issuer pubkey == principal_id).
        """
        issuer_pub = crypto.public_key_from_private(issuer_priv_hex)
        if issuer_pub != params.principal_id:
            raise AttenuationError("root delegation must be signed by the principal key")
        body = DelegationBody(
            principal_id=params.principal_id,
            issuer_id=params.principal_id,
            issued_to=params.issued_to,
            parent=None,
            scope=params.scope,
            exclusions=params.exclusions,
            permitted_classes=params.permitted_classes,
            escalation_required=params.escalation_required,
            window=params.window,
            blast_radius_budget=params.blast_radius_budget,
            max_autonomy=params.max_autonomy,
            revocation=params.revocation,
            nonce=params.nonce,
        )
        # Arm the dead-man's switch at issuance.
        self._store.heartbeat(params.principal_id)
        return self._sign(body, issuer_priv_hex)

    # -- attenuate --------------------------------------------------------
    def attenuate(
        self, parent: Delegation, subset: MintParams, issuer_priv_hex: str
    ) -> Delegation:
        """Produce a child delegation, enforcing subset-only authority.

        The child is issued by the parent's ``issued_to`` (signed with its key).
        Any widening on any dimension raises :class:`AttenuationError`.
        """
        pb = parent.body
        self._assert_subset(pb, subset)

        issuer_id = pb.issued_to
        issuer_pub = crypto.public_key_from_private(issuer_priv_hex)
        if issuer_pub != issuer_id:
            raise AttenuationError("child must be signed by the parent's issued_to key")

        body = DelegationBody(
            principal_id=pb.principal_id,
            issuer_id=issuer_id,
            issued_to=subset.issued_to,
            parent=parent.id,
            scope=subset.scope,
            exclusions=subset.exclusions,
            permitted_classes=subset.permitted_classes,
            escalation_required=subset.escalation_required,
            window=subset.window,
            blast_radius_budget=subset.blast_radius_budget,
            max_autonomy=subset.max_autonomy,
            revocation=subset.revocation,
            nonce=subset.nonce,
        )
        return self._sign(body, issuer_priv_hex)

    def _assert_subset(self, parent: DelegationBody, child: MintParams) -> None:
        # scope: every (selector, value) in child must exist in parent.
        for stype, vals in child.scope.items():
            pvals = set(parent.scope.get(stype, []))
            if not set(vals).issubset(pvals):
                raise AttenuationError(f"scope widens on selector {stype!r}")
        # permitted_classes: child ⊆ parent.
        if not set(child.permitted_classes).issubset(parent.permitted_classes):
            raise AttenuationError("permitted_classes widen")
        # exclusions: child must exclude at least as much (parent ⊆ child).
        if not set(parent.exclusions).issubset(child.exclusions):
            raise AttenuationError("exclusions narrow (removes a boundary)")
        # escalation_required: child must require at least as much (parent ⊆ child).
        if not set(parent.escalation_required).issubset(child.escalation_required):
            raise AttenuationError("escalation_required narrows")
        # window: child within parent.
        if not child.window.within(parent.window):
            raise AttenuationError("window widens")
        # autonomy: child ≤ parent.
        if autonomy_rank(child.max_autonomy) > autonomy_rank(parent.max_autonomy):
            raise AttenuationError("max_autonomy widens")
        # budget: every child dim must exist in parent with a ≤ limit.
        for dim, limit in child.blast_radius_budget.items():
            if dim not in parent.blast_radius_budget:
                raise AttenuationError(f"budget adds new dimension {dim!r}")
            if limit > parent.blast_radius_budget[dim]:
                raise AttenuationError(f"budget widens on dimension {dim!r}")
        # scope_expansion is always 0 (Principle 2).
        if child.blast_radius_budget.get("scope_expansion", 0) != 0:
            raise AttenuationError("scope_expansion budget must be 0")

    # -- verify -----------------------------------------------------------
    def verify(self, action: Action | None, chain: list[Delegation]) -> CredResult:
        """Walk the chain to root and check authority. Fails closed."""
        if not chain:
            return CredResult(valid=False, reason="empty chain")

        # Order leaf..root by following parent pointers, then reverse to root..leaf.
        ordered = self._order_chain(chain)
        if ordered is None:
            return CredResult(valid=False, reason="broken chain linkage")

        now = self._clock()
        for i, deleg in enumerate(ordered):
            body = deleg.body
            # signature
            if not crypto.verify(body.issuer_id, canonical_bytes(body), deleg.signature):
                return CredResult(valid=False, reason=f"bad signature at depth {i}")
            # root vs child structural rules
            if i == 0:
                if body.parent is not None or body.issuer_id != body.principal_id:
                    return CredResult(valid=False, reason="malformed root")
            else:
                parent = ordered[i - 1]
                if body.parent != parent.id:
                    return CredResult(valid=False, reason=f"parent hash mismatch at depth {i}")
                if body.issuer_id != parent.body.issued_to:
                    return CredResult(valid=False, reason=f"issuer!=parent.issued_to at depth {i}")
                # defense-in-depth: re-check subset on every link.
                try:
                    self._assert_subset(parent.body, _as_mint(body))
                except AttenuationError as exc:
                    return CredResult(valid=False, reason=f"link widens: {exc}")
            # window
            if not body.window.contains(now):
                return CredResult(valid=False, reason=f"outside window at depth {i}")
            # revocation
            if self._store.is_revoked(deleg.id):
                return CredResult(valid=False, reason=f"revoked at depth {i}")
            # dead-man's-switch (on any link that arms it)
            if body.revocation.dead_mans_switch and self._store.is_dead_mans_expired(
                body.principal_id
            ):
                return CredResult(valid=False, reason="dead-man's-switch expired")

        effective = self._effective(ordered)

        # If an action was supplied, check it against the effective authority.
        if action is not None:
            reason = self._authorize_action(action, effective)
            if reason is not None:
                return CredResult(valid=False, reason=reason, effective=effective)

        return CredResult(valid=True, reason="ok", effective=effective)

    def _authorize_action(self, action: Action, eff: EffectiveAuthority) -> str | None:
        if action.action_class not in eff.permitted_classes:
            return f"class {action.action_class!r} not permitted"
        # action scope must be within effective scope
        for stype, vals in action.scope.selectors.items():
            allowed = set(eff.scope.get(stype, []))
            if not set(vals).issubset(allowed):
                return f"action scope outside grant on selector {stype!r}"
        # action must not touch an effective exclusion
        hit = set(action.touches_exclusions) & set(eff.exclusions)
        if hit:
            return f"action touches excluded boundary {sorted(hit)}"
        return None

    # -- revocation / heartbeat ------------------------------------------
    def revoke(self, delegation_id: str) -> None:
        self._store.revoke(delegation_id)

    def heartbeat(self, principal_id: str) -> None:
        self._store.heartbeat(principal_id)

    @property
    def store(self) -> RevocationStore:
        return self._store

    # -- helpers ----------------------------------------------------------
    def _sign(self, body: DelegationBody, issuer_priv_hex: str) -> Delegation:
        signature = crypto.sign(issuer_priv_hex, canonical_bytes(body))
        return Delegation(body=body, signature=signature)

    def _order_chain(self, chain: list[Delegation]) -> list[Delegation] | None:
        roots = [d for d in chain if d.body.parent is None]
        if len(roots) != 1:
            return None
        ordered = [roots[0]]
        # children map: parent hash -> delegation
        children: dict[str | None, list[Delegation]] = {}
        for d in chain:
            children.setdefault(d.body.parent, []).append(d)
        cur = roots[0]
        seen = {cur.id}
        while True:
            nxt = children.get(cur.id, [])
            if not nxt:
                break
            if len(nxt) != 1:
                return None  # ambiguous / forked chain
            child = nxt[0]
            if child.id in seen:
                return None  # cycle
            ordered.append(child)
            seen.add(child.id)
            cur = child
        if len(ordered) != len(chain):
            return None  # dangling links not connected to root
        return ordered

    def _effective(self, ordered: list[Delegation]) -> EffectiveAuthority:
        """Intersect the chain to the least authority (most restrictive)."""
        root = ordered[0].body
        scope = {k: set(v) for k, v in root.scope.items()}
        exclusions = set(root.exclusions)
        classes = set(root.permitted_classes)
        escalation = set(root.escalation_required)
        autonomy = root.max_autonomy
        budget = dict(root.blast_radius_budget)

        for d in ordered[1:]:
            b = d.body
            scope = {k: scope.get(k, set()) & set(b.scope.get(k, [])) for k in scope.keys() & b.scope.keys()}
            classes &= set(b.permitted_classes)
            exclusions |= set(b.exclusions)  # union: most restrictive
            escalation |= set(b.escalation_required)
            if autonomy_rank(b.max_autonomy) < autonomy_rank(autonomy):
                autonomy = b.max_autonomy
            budget = {
                dim: min(budget.get(dim, lim), lim)
                for dim, lim in b.blast_radius_budget.items()
                if dim in budget
            }

        return EffectiveAuthority(
            scope={k: sorted(v) for k, v in scope.items()},
            exclusions=sorted(exclusions),
            permitted_classes=sorted(classes),
            escalation_required=sorted(escalation),
            max_autonomy=autonomy,
            blast_radius_budget=budget,
        )


def _as_mint(body: DelegationBody) -> MintParams:
    return MintParams(
        principal_id=body.principal_id,
        issued_to=body.issued_to,
        scope=body.scope,
        exclusions=body.exclusions,
        permitted_classes=body.permitted_classes,
        escalation_required=body.escalation_required,
        window=body.window,
        blast_radius_budget=body.blast_radius_budget,
        max_autonomy=body.max_autonomy,
        revocation=body.revocation,
        nonce=body.nonce,
    )
