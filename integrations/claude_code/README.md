# EIDOLON for Claude Code — govern every native tool

An MCP gateway governs the tool *servers* an agent connects to. But Claude
Code's built-in **Bash / Edit / Write / Read / WebFetch** never flow through
MCP — so a plain gateway can't see them. That's the gap this closes.

Claude Code **hooks** fire on *every* tool call, built-ins included. This adapter
wires a `PreToolUse` hook that asks EIDOLON to rule on each call
(**allow / ask / deny**, attested on the ledger) and a `PostToolUse` hook that
feeds outputs into the taint tracker. Every action lands in the same
[mission-control feed](https://eidolon.onyxcreator.com/live) as your MCP calls,
and the operator **kill switch** stops it mid-session.

```
Claude Code ──PreToolUse hook──▶ /gate/evaluate ──KAIROS──▶ allow | ask | deny
   (Bash/Edit/Read/WebFetch…)         │ attest + live feed        (+ kill switch)
                └──PostToolUse hook──▶ /gate/observe  (taint: catch later exfil)
```

## What gets governed

| Native tool | Class | Default verdict |
|---|---|---|
| `Read` `Grep` `Glob` `LS` | read-code | ✅ allow (reads taint their output) |
| `Edit` `Write` `MultiEdit` `NotebookEdit` | edit-code | ✅ allow (in scope) |
| `Bash` (normal) | run-command | ✅ allow (notify) |
| `Bash` (`rm -rf`, force-push, `curl … \| sh`, `DROP TABLE`…) | destructive-command | 🟡 **ask** (escalates to you) |
| `WebFetch` `WebSearch` | web-egress | ✅ allow — 🔴 **deny** if it carries a value read earlier (exfil) |
| unknown / unmapped tool | (fail-closed) | 🟡 ask |

The exfil rule is the point: read a secret with `Read`, then try to `curl` it to
an external host or paste it into a `WebFetch` URL, and EIDOLON denies the
egress — structurally, not by asking the model nicely.

## Setup

1. **Get your agent key.** In the app, create an agent; copy its `egk_…` gateway
   key. (Same key the managed `/mcp` endpoint uses.)

2. **Point the hook at the key.** Add to `~/.claude/settings.json` (all projects)
   or `.claude/settings.json` (one project). Replace the key and the path to
   `eidolon_hook.py`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [
        { "type": "command",
          "command": "EIDOLON_AGENT_KEY=egk_YOURKEY python3 /ABS/PATH/integrations/claude_code/eidolon_hook.py" }
      ]}
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [
        { "type": "command",
          "command": "EIDOLON_AGENT_KEY=egk_YOURKEY python3 /ABS/PATH/integrations/claude_code/eidolon_hook.py" }
      ]}
    ]
  }
}
```

   (Prefer not to inline the key? Export `EIDOLON_AGENT_KEY` in your shell
   profile and drop it from the command.)

3. **Restart Claude Code.** From now on every tool call is governed and attested.
   Watch it live at `EIDOLON_URL/live`.

## Options (environment)

| Var | Default | Meaning |
|---|---|---|
| `EIDOLON_URL` | `https://eidolon.onyxcreator.com` | your deployment (use the on-prem host for org rollouts) |
| `EIDOLON_AGENT_KEY` | — | the agent's `egk_` key (required) |
| `EIDOLON_HOOK_STRICT` | unset | `1` = fail **closed** (block) when the gate is unreachable |
| `EIDOLON_HOOK_TIMEOUT` | `5` | seconds to wait for a verdict |

By default the hook **fails open** on a network error (an EIDOLON outage never
freezes a developer). For a hard compliance posture where nothing runs
un-governed, set `EIDOLON_HOOK_STRICT=1` — and remember the airtight guarantee
also needs the workstation locked so agents can only reach tools through
EIDOLON.

## On-prem

Point `EIDOLON_URL` at the central server IT runs (see the deploy docs). Every
developer's Claude Code then routes through one governed endpoint, on one
tamper-evident ledger, with per-agent kill switches and org-scoped compliance
packs — the same hook, no per-workstation policy to maintain.

## Cursor / Codex

Cursor and Codex don't yet expose an equivalent universal pre-tool hook. Until
they do, govern their **MCP** tools with `python -m eidolon.wrap` (see
`../../docs/integrations/README.md`), and restrict them to EIDOLON-provided tools
at the workstation for their built-ins.
