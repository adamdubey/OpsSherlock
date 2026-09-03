SHELL := /bin/bash
MODEL ?= qwen3:8b
SCENARIO ?= checkout_latency

.PHONY: up down model smoke telemetry chaos-setup chaos-list chaos-status inject investigate incident auto-incident capture-evidence publish site demo reset ps logs test

up:
	docker compose up -d --build gateway catalog checkout payments orders postgres redis toxiproxy prometheus loki tempo alloy grafana ollama
	python3 chaos/chaosctl.py setup
	@echo "Baker Street: http://localhost:8080"
	@echo "Grafana:      http://localhost:3000"
	@echo "Prometheus:   http://localhost:9090"
	@echo "Loki:         http://localhost:3100"
	@echo "Tempo:        http://localhost:3200"
	@echo "Alloy:        http://localhost:12345"
	@echo "Toxiproxy:    http://localhost:8474"
	@echo "Checkout:     http://localhost:8001"

model:
	docker compose exec ollama ollama pull $(MODEL)

smoke:
	./scripts/smoke.sh

telemetry:
	python3 scripts/verify_observability.py

chaos-setup:
	python3 chaos/chaosctl.py setup

chaos-list:
	python3 chaos/chaosctl.py list

chaos-status:
	python3 chaos/chaosctl.py status

inject:
	./scripts/inject.sh $(SCENARIO)

investigate:
	docker compose --profile tools build agent
	docker compose --profile tools run --rm agent python investigator.py --scenario $(SCENARIO)

incident: inject
	@sleep 8
	@$(MAKE) investigate SCENARIO=$(SCENARIO)

auto-incident: inject
	python3 automation/incidentctl.py --scenario $(SCENARIO)

capture-evidence:
	docker compose --profile tools build publisher
	docker compose --profile tools run --rm publisher --incident $(INCIDENT) --phase $(PHASE)

publish: site
	@echo "Publishing bundle built in site/dist"

site:
	python3 site/build.py
	@echo "Open site/dist/index.html"

test:
	python3 -m unittest discover -s tests -v

demo: up
	@echo "Run 'make smoke', 'make telemetry', 'make chaos-list', pull a model with 'make model MODEL=$(MODEL)', then 'make auto-incident SCENARIO=$(SCENARIO)'"

reset:
	python3 chaos/chaosctl.py reset

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

down:
	docker compose down -v
