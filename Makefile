SHELL := /bin/bash
MODEL ?= qwen3:8b
SCENARIO ?= checkout_latency
INCIDENT ?= latest

.PHONY: up down model smoke inject investigate incident site demo reset

up:
	docker compose up -d --build checkout inventory prometheus grafana ollama
	@echo "Grafana:    http://localhost:3000"
	@echo "Prometheus: http://localhost:9090"
	@echo "Checkout:   http://localhost:8001"

model:
	docker compose exec ollama ollama pull $(MODEL)

smoke:
	curl -fsS http://localhost:8001/checkout >/dev/null
	curl -fsS http://localhost:8002/items >/dev/null
	@echo "smoke test passed"

inject:
	./scripts/inject.sh $(SCENARIO)

investigate:
	docker compose --profile tools run --rm agent python investigator.py --scenario $(SCENARIO)

incident: inject
	@sleep 6
	@$(MAKE) investigate SCENARIO=$(SCENARIO)

site:
	python3 site/build.py
	@echo "Open site/dist/index.html"

demo: up
	@echo "Pull a model once with: make model MODEL=$(MODEL)"
	@echo "Then run: make incident SCENARIO=$(SCENARIO)"

reset:
	curl -fsS -X POST http://localhost:8001/admin/fault/reset >/dev/null || true
	@echo "faults reset"

down:
	docker compose down -v
