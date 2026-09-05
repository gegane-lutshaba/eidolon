.PHONY: versus install up down deploy deploy-tls deploy-down deploy-logs deploy-verify deploy-backup test test-integration lint fmt typecheck run demo dashboard transcript gateway-demo hermes-case adversarial escalation subagent formal whitepaper-pdf clean

install:
	uv sync --all-extras

up:
	docker compose up -d
	@echo "Waiting for SAGE + Postgres to become healthy..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' eidolon-sage 2>/dev/null)" = "healthy" ]; do sleep 2; done
	@echo "SAGE is healthy at http://localhost:8080"

down:
	docker compose down

# --- single-VPS deployment (app + Postgres-backed SAGE ledger) ---
DEPLOY = docker compose -f docker-compose.deploy.yml

deploy:
	$(DEPLOY) up -d --build
	@echo "EIDOLON is starting at http://localhost:$${EIDOLON_PORT:-8000}"

# Production: also start Caddy (auto-HTTPS). Requires EIDOLON_DOMAIN in .env.
deploy-tls:
	$(DEPLOY) --profile tls up -d --build
	@echo "EIDOLON + Caddy up for domain $${EIDOLON_DOMAIN:-localhost}"

deploy-down:
	$(DEPLOY) --profile tls down

deploy-logs:
	$(DEPLOY) logs -f eidolon

# Verify the persisted attestation ledger is intact (hash chain unbroken).
deploy-verify:
	$(DEPLOY) exec eidolon python -m eidolon.sage.verify

# Back up the Postgres database (memory + attestation ledger).
deploy-backup:
	./deploy/backup.sh

# Fast lane: unit + property tests on the in-memory SAGE port. No node needed.
test:
	uv run pytest -m "not integration"

# Live lane: acceptance criteria against the Dockerized SAGE node.
test-integration:
	EIDOLON_SAGE_BACKEND=sage uv run pytest -m integration

lint:
	uv run ruff check src tests

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck:
	uv run mypy src

run:
	uv run uvicorn eidolon.api.app:app --host $${EIDOLON_API_HOST:-127.0.0.1} --port $${EIDOLON_API_PORT:-8000} --reload

# Narrated CLI showcase (in-memory SAGE; no node needed).
demo:
	uv run python examples/continuity_demo.py

# Web dashboard — open http://localhost:8000 after it starts.
dashboard:
	uv run uvicorn eidolon.api.app:app --host 127.0.0.1 --port 8000

# VERSUS: the same attack, your agent without EIDOLON vs the real gate with it.
versus:
	@echo "→ open http://localhost:8000/versus"
	uv run uvicorn eidolon.api.app:app --host 127.0.0.1 --port 8000

# Regenerate the committed transcript (deterministic voice).
transcript:
	EIDOLON_ANTHROPIC_API_KEY= NO_COLOR=1 uv run python examples/continuity_demo.py > docs/demo-transcript.txt

# Governing MCP gateway showcase — the authority layer for MCP agents.
gateway-demo:
	uv run python examples/mcp_gateway_demo.py

# Hermes before/after case study — why a personal-assistant needs EIDOLON.
hermes-case:
	uv run python examples/hermes_case_study.py

# Automated adversarial certification — the twin earns autonomy by surviving attacks.
adversarial:
	uv run python examples/adversarial_cert.py

# Escalation -> approval loop (sign to release an escalation).
escalation:
	uv run python examples/escalation_flow.py

# Twin -> sub-agent delegation (cryptographic subset-only).
subagent:
	uv run python examples/subagent_delegation.py

# Render the whitepaper to a print-quality PDF (needs: uv sync --extra docs && uv run playwright install chromium).
whitepaper-pdf:
	uv run python docs/build_whitepaper_pdf.py

# Machine-check the TLA+ model of the gate with TLC (downloads tools on demand).
formal:
	@test -f formal/tla2tools.jar || curl -sL -o formal/tla2tools.jar \
		https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar
	cd formal && java -cp tla2tools.jar tlc2.TLC -config EidolonGate.cfg EidolonGate.tla

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
