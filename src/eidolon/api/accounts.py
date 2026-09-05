"""Accounts: users, sessions, and their agents (self-hosted multi-user).

A user signs up (optionally gated by an invite code), creates **agents**, and
gets a per-agent gateway key. The agent's id doubles as its ``gateway_id``, so
gateways/events resolve to an owner and each user sees only their own world;
the operator admin/auditor tokens keep their global view.

Security posture: passwords are stdlib-scrypt hashed; sessions are random DB
tokens (revocable, expiring); per-agent gateway keys are machine credentials
whose ingest use is pinned to the agent's own gateway_id (a leaked key cannot
report as anyone else's agent).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import secrets

SESSION_TTL = _dt.timedelta(days=7)

# Authority presets for the create-agent wizard — real classes/exclusions/
# ceilings underneath, one honest word on top. Rank names double as the
# gamified ladder (autonomy is earned, not assumed).
PRESETS: dict[str, dict] = {
    "reader": {
        "rank": "OBSERVER",
        "blurb": "Reads and answers. Everything else is held for you.",
        "max_autonomy": "draft",
        "permitted_classes": ["retrieve-context", "answer-status"],
    },
    "builder": {
        "rank": "DRAFTER",
        "blurb": "Reads, answers, drafts, posts status. Commits always escalate.",
        "max_autonomy": "notify",
        "permitted_classes": ["retrieve-context", "answer-status", "draft-comm", "post-status"],
    },
    "operative": {
        "rank": "OPERATIVE",
        "blurb": "Acts on routine work within scope. Exclusions and commits still bite.",
        "max_autonomy": "autonomous",
        "permitted_classes": ["retrieve-context", "answer-status", "draft-comm",
                              "post-status", "commit-action"],
    },
}


# -- passwords -----------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return secrets.compare_digest(digest.hex(), hash_hex)
    except Exception:  # noqa: BLE001 — malformed hash = no match
        return False


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _as_utc(dt: _dt.datetime | None) -> _dt.datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)


# -- users + sessions ----------------------------------------------------
def create_user(sf, email: str, password: str) -> dict:
    from eidolon.data.models import UserRow

    email = email.strip().lower()
    if "@" not in email or len(password) < 8:
        raise ValueError("valid email and a password of 8+ characters required")
    with sf() as s:
        if s.query(UserRow).filter(UserRow.email == email).first():
            raise ValueError("an account with this email already exists")
        user = UserRow(id=f"usr-{secrets.token_urlsafe(9)}", email=email,
                       password_hash=hash_password(password))
        s.add(user)
        s.commit()
        return {"id": user.id, "email": user.email}


def authenticate(sf, email: str, password: str) -> dict | None:
    from eidolon.data.models import UserRow

    with sf() as s:
        user = s.query(UserRow).filter(UserRow.email == email.strip().lower()).first()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return {"id": user.id, "email": user.email}


def open_session(sf, user_id: str) -> str:
    from eidolon.data.models import UserSessionRow

    token = secrets.token_urlsafe(32)
    with sf() as s:
        s.add(UserSessionRow(token=token, user_id=user_id, expires_at=_now() + SESSION_TTL))
        s.commit()
    return token


def close_session(sf, token: str | None) -> None:
    from eidolon.data.models import UserSessionRow

    if not token:
        return
    with sf() as s:
        row = s.get(UserSessionRow, token)
        if row:
            s.delete(row)
            s.commit()


def user_for_session(sf, token: str | None) -> dict | None:
    from eidolon.data.models import UserRow, UserSessionRow

    if not token:
        return None
    with sf() as s:
        sess = s.get(UserSessionRow, token)
        if sess is None:
            return None
        expires = _as_utc(sess.expires_at)
        if expires < _now():
            s.delete(sess)
            s.commit()
            return None
        user = s.get(UserRow, sess.user_id)
    return {"id": user.id, "email": user.email} if user else None


# -- agents ---------------------------------------------------------------
def create_agent(sf, user_id: str, name: str, preset: str) -> dict:
    from eidolon.common import crypto
    from eidolon.data.models import AgentKeyRow, AgentRow

    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r} (choose from {sorted(PRESETS)})")
    name = name.strip()[:60] or "unnamed-agent"
    agent = AgentRow(id=f"agt-{secrets.token_urlsafe(8)}", user_id=user_id,
                     name=name, preset=preset,
                     gateway_key=f"egk_{secrets.token_urlsafe(24)}")
    # Mint the agent's principal identity now so connect is paste-and-go
    # (custodial v1; self-custody = swap the key in the yaml, delete the row).
    kp = crypto.generate_keypair()
    with sf() as s:
        s.add(agent)
        s.add(AgentKeyRow(agent_id=agent.id, public_hex=kp.public_key_hex,
                          signing_hex=kp.signing_key_hex))
        s.commit()
        return _agent_dict(agent)


def agent_keypair(sf, agent_id: str) -> dict | None:
    from eidolon.data.models import AgentKeyRow

    with sf() as s:
        row = s.get(AgentKeyRow, agent_id)
    return {"public": row.public_hex, "signing": row.signing_hex} if row else None


def list_agents(sf, user_id: str) -> list[dict]:
    from sqlalchemy import func, select

    from eidolon.data.models import AgentRow, GatewayEventRow, GatewayRow

    with sf() as s:
        agents = s.execute(select(AgentRow).where(AgentRow.user_id == user_id)
                           .order_by(AgentRow.created_at.asc())).scalars().all()
        out = []
        for a in agents:
            gw = s.get(GatewayRow, a.id)
            blocks = s.execute(
                select(func.count()).select_from(GatewayEventRow)
                .where(GatewayEventRow.gateway_id == a.id,
                       GatewayEventRow.level.in_(["DENY", "KILLED"]))
            ).scalar() or 0
            d = _agent_dict(a)
            d.update({
                "connected": gw is not None,
                "killed": bool(gw.killed) if gw else False,
                "last_seen": gw.last_seen.isoformat() if gw and gw.last_seen else None,
                "events": gw.events if gw else 0,
                "blocks": int(blocks),
            })
            out.append(d)
        return out


def get_agent(sf, user_id: str, agent_id: str) -> dict | None:
    from eidolon.data.models import AgentRow

    with sf() as s:
        a = s.get(AgentRow, agent_id)
    return _agent_dict(a) if a and a.user_id == user_id else None


def delete_agent(sf, user_id: str, agent_id: str) -> bool:
    from eidolon.data.models import AgentRow

    with sf() as s:
        a = s.get(AgentRow, agent_id)
        if a is None or a.user_id != user_id:
            return False
        s.delete(a)  # key revoked; historical gateway/events remain for audit
        s.commit()
    return True


def owned_gateway_ids(sf, user_id: str) -> set[str]:
    from sqlalchemy import select

    from eidolon.data.models import AgentRow

    with sf() as s:
        rows = s.execute(select(AgentRow.id).where(AgentRow.user_id == user_id)).all()
    return {r[0] for r in rows}


def agent_for_gateway_key(sf, key: str | None) -> dict | None:
    """Resolve an ingest credential to its agent (pins gateway_id to the agent)."""
    from sqlalchemy import select

    from eidolon.data.models import AgentRow

    if not key or not key.startswith("egk_"):
        return None
    with sf() as s:
        a = s.execute(select(AgentRow).where(AgentRow.gateway_key == key)).scalars().first()
    return _agent_dict(a) if a else None


def _agent_dict(a) -> dict:
    return {"id": a.id, "user_id": a.user_id, "name": a.name, "preset": a.preset,
            "rank": PRESETS.get(a.preset, {}).get("rank", "OBSERVER"),
            "gateway_key": a.gateway_key,
            "created_at": a.created_at.isoformat() if a.created_at else None}


# -- paste-and-go gateway config ------------------------------------------
# Sensible day-one tool policies for the most common first downstream (the MCP
# filesystem server): reads flow at the preset's ceiling, writes are held —
# the live feed demonstrates the gate instead of stonewalling the user.
_FS_READ_TOOLS = ["read_file", "read_text_file", "read_multiple_files", "list_directory",
                  "list_directory_with_sizes", "directory_tree", "search_files",
                  "get_file_info", "list_allowed_directories"]
_FS_WRITE_TOOLS = ["write_file", "edit_file", "create_directory", "move_file"]

_SEEDS = [
    "the user will read file contents and list directory entries for the project routinely",
    "the user will search files and get file info in the project routinely",
    "the user will draft comms and post status updates for the project routinely",
]


def build_connect_config(agent: dict, keypair: dict, base_url: str) -> dict:
    """A complete GatewayConfig dict for this agent — parses and boots as-is."""
    preset = PRESETS[agent["preset"]]
    scope = {"project": ["workspace"]}
    policies = [
        {"tool": t, "action_class": "retrieve-context", "scope": {"selectors": scope}}
        for t in _FS_READ_TOOLS
    ] + [
        {"tool": t, "action_class": "commit-action", "scope": {"selectors": scope}}
        for t in _FS_WRITE_TOOLS
    ]
    return {
        "profile_id": "general-continuity",
        "principal_signing_key": keypair["signing"],
        "scope": scope,
        "permitted_classes": list(preset["permitted_classes"]),
        "max_autonomy": preset["max_autonomy"],
        "seed_memories": [s for s in _SEEDS for _ in range(6)],
        "tool_policies": policies,
        "report_url": base_url,
        "report_key": agent["gateway_key"],
        "gateway_id": agent["id"],
        "agent_name": agent["name"],
    }
