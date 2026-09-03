# 🔎 OpsSherlock

**A fully local AI SRE laboratory that injects reproducible failures, investigates real telemetry with Ollama, scores the AI against known ground truth, and publishes incident postmortems to GitHub Pages.**

> Status: v0.1 scaffold — intentionally small, reproducible, and designed to grow.

## What makes this different

OpsSherlock is not a chatbot over logs. The model is treated as an incident investigator whose conclusions must be backed by observability evidence and evaluated against deterministic fault scenarios.

The lab deliberately keeps **ground truth separate from the model prompt**, which lets the evaluator detect when the AI is wrong instead of rewarding confident prose.

## Architecture

```text
                     ┌───────────────────┐
                     │      Ollama       │
                     └─────────▲─────────┘
                               │
                        evidence + RCA
                               │
┌───────────┐          ┌───────┴────────┐
│ inventory │◄─────────│    checkout    │
└─────┬─────┘          └───────┬────────┘
      │ metrics                  │ metrics
      └────────────┬─────────────┘
                   ▼
             ┌────────────┐
             │ Prometheus │
             └─────┬──────┘
                   ▼
              ┌─────────┐
              │ Grafana │
              └─────────┘

        fault scenario → investigator
                       → evaluation
                       → postmortem
                       → GitHub Pages
```

## Run it

Requirements: Docker + Docker Compose.

```bash
cp .env.example .env
make up
make model MODEL=qwen3:8b
make incident SCENARIO=checkout_latency
make site
```

Then visit:

- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
- Checkout API: http://localhost:8001/checkout
- Static portal: `site/dist/index.html`

Reset the injected fault with:

```bash
make reset
```

## What an incident produces

```text
artifacts/incidents/INC-.../
├── incident.json
└── postmortem.md
```

The JSON contains captured Prometheus evidence, selected container logs, the model's diagnosis, the scenario ground truth, and an automated evaluation.


