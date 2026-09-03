SHELL := /bin/bash
MODEL ?= qwen3:8b
SCENARIO ?= checkout_latency

.PHONY: up down model smoke telemetry inject investigate incident site demo reset ps logs

up:
	docker compose up -d --build gateway catalog checkout payments orders postgres redis prometheus loki tempo alloy grafana ollama
	@echo "Baker Street: http://localhost:8080"
	@echo "Grafana:      http://localhost:3000"
	@echo "Prometheus:   http://localhost:9090"
	@echo "Loki:         http://localhost:3100"
	@echo "Tempo:        http://localhost:3200"
	@echo "Alloy:        http://localhost:12345"
	@echo "Checkout:     http://localhost:8001"

model:
	docker compose exec ollama ollama pull $(MODEL)

smoke:
	./scripts/smoke.sh

telemetry:
	python3 scripts/verify_observability.py

inject:
	./scripts/inject.sh $(SCENARIO)

investigate:
	docker compose --profile tools run --rm agent python investigator.py --scenario $(SCENARIO)

incident: inject
	@sleep 8
	@$(MAKE) investigate SCENARIO=$(SCENARIO)

site:
	python3 site/build.py
	@echo "Open site/dist/index.html"

demo: up
	@echo "Run 'make smoke', 'make telemetry', pull a model with 'make model MODEL=$(MODEL)', then 'make incident SCENARIO=$(SCENARIO)'"

reset:
	curl -fsS -X POST http://localhost:8001/admin/fault/reset >/dev/null || true
	@echo "faults reset"

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

down:
	docker compose down -v
