# surge-quality buildable plan

**Authority:** PulsePoint design decisions memo (Todd, 2026-06-03) §4 (Quality bar) + §5 (Identity-aware routing) + Phase A sequencing.

**Scope of THIS repo:** Components 1-6 below. **Out of scope:** changes to PulsePoint hub itself live in `SurgeXi/pulsepoint` (separate PR).

---

## Components

### 1. Rubric definition + scoring service (this repo)
10 axes scored 0-10 by surge-ai Hermes 3 (cost-efficient), with Claude as ground-truth trainer (sampled).

| Axis | Definition |
|---|---|
| correctness | facts cited match reality (cross-check against named knowledge sources when claims are made) |
| tone_match | appropriate to identity context (customer / operator / technical) |
| completeness | addresses the actual question, not deflection |
| action_orientation | when action needed, proposes concrete action |
| brevity | length appropriate to question |
| citation_quality | when facts cited, source is named/fetched |
| identity_awareness | references user by name/context appropriately |
| memory_usage | refers back to earlier conversation context when relevant |
| safety | no dangerous/destructive recommendations |
| confidence_calibration | admits uncertainty when uncertain |

### 2. Customer telemetry capture (PulsePoint widget extension)
5 signals POSTed to `surge-quality`:
- thumbs (up/down already in widget)
- reply_time_seconds (proxy for "was the answer helpful")
- dropoff (customer ends conversation right after — bad signal)
- reask (customer rephrases same question — Surge missed intent)
- escalation_request (explicit "let me talk to a human")

### 3. Combined quality score
`combined = 0.7 * (rubric_mean / 10.0) + 0.3 * telemetry_score` where
- `telemetry_score` = weighted sum (thumb_up +1, thumb_down -1, dropoff -0.5, reask -0.5, escalation_request -1, reply_time_seconds_inverse +0.3)
- normalized to 0.0-1.0

### 4. Claude-as-teacher feedback loop
When combined < 0.6: async worker calls Claude with (Surge response + customer context + scoring breakdown). Claude returns:
- `better_response: str`
- `diagnosis: str` (what was wrong + how to fix)
Both logged as `claude_reviews` rows; serve as training corpus for Surge next iteration.
When combined < 0.4 AND topic recurs: queue for **Claude takeover** next time same context recurs (the `recurring_low_score` flag).

### 5. A/B routing decision logic
Input: customer message + conversation history + identity context.
Output: `surge` | `surge_with_claude_review` | `claude_primary`.
Decision factors:
- similarity to past low-scoring turns (vector lookup on `responses.embedding`, threshold tuned)
- topic complexity (Hermes classifies; tier 1-3)
- customer urgency (heuristic: "urgent" / "ASAP" / repeated re-asks in last 5 turns)
- identity context — customer-facing high-stakes (tax, money, deadline) → bias to `claude_primary`
- existing `recurring_low_score` flag on similar context → `claude_primary`

### 6. Dashboard
Operator view (Todd):
- Per-day Surge share (% turns Surge handled vs Claude)
- Per-day average combined quality score
- Topic-area breakdown
- Low-score turn replay (drill from chart to turn+response+Claude-better-response)
- Per-customer signal (Sheilia thumbs-down rate by topic)

Preferred: Grafana panels (existing SurgeComm Prometheus on surgecore). Fallback: FastAPI + Jinja2 `/dashboard/{view}` page.

---

## Repo layout (proposed)

```
surge-quality/
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── alembic.ini
├── alembic/versions/
│   ├── 0001_responses.py
│   ├── 0002_rubric_scores.py
│   ├── 0003_telemetry_signals.py
│   ├── 0004_claude_reviews.py
│   └── 0005_routing_decisions.py
├── src/surge_quality/
│   ├── main.py
│   ├── settings.py
│   ├── db.py
│   ├── models/{response,rubric_score,telemetry_signal,claude_review,routing_decision}.py
│   ├── schemas/...
│   ├── api/
│   │   ├── score.py         # POST /v1/quality/score-response
│   │   ├── telemetry.py     # POST /v1/quality/telemetry
│   │   ├── route.py         # POST /v1/quality/route-decision
│   │   ├── dashboard.py     # GET /v1/quality/dashboard/{view}
│   │   └── health.py        # /healthz /readyz /metrics
│   ├── scoring/
│   │   ├── hermes_client.py # surge-ai Hermes 3
│   │   ├── rubric.py        # 10-axis prompt + parser
│   │   └── combined.py      # combined score formula
│   ├── teacher/
│   │   ├── claude_client.py # /etc/surge-quality/claude.env, 600 perm
│   │   ├── worker.py        # async low-score reviewer
│   │   └── prompts.py
│   ├── routing/
│   │   ├── decision.py      # surge|surge_with_claude_review|claude_primary
│   │   ├── similarity.py    # vector lookup against past low-score
│   │   └── classify.py      # Hermes topic + urgency
│   └── observability/
│       ├── metrics.py       # prometheus_client
│       └── logging.py       # structlog
├── tests/
│   ├── unit/
│   ├── integration/
│   └── smoke/
├── deploy/
│   ├── surge-quality.service
│   └── nginx-tailscale.conf
└── docs/
    ├── PLAN.md  (this file)
    ├── API.md   (endpoint signatures + curl examples)
    ├── DEPLOY.md (deploy + rollback)
    └── RUBRIC.md (the 10 axes, scoring prompt, sample scored response)
```

---

## API surface

Base: `/v1/quality`. JSON bodies. Service tokens via `X-Surge-Quality-Token` header (Phase A) → JWT later (Phase B).

| Endpoint | Purpose |
|---|---|
| `POST /v1/quality/score-response` | Submit a Surge response; returns `score_id`. Scoring is async (background task), result fetched later. |
| `GET /v1/quality/score-response/{score_id}` | Fetch scoring result + per-axis breakdown + combined score. |
| `POST /v1/quality/telemetry` | PulsePoint widget posts one signal `{response_id, signal_type, value, timestamp}`. |
| `POST /v1/quality/route-decision` | Incoming customer message + context → routing decision + reason. |
| `GET /v1/quality/dashboard/{view}` | Dashboard views: `share`, `score-trend`, `topic-breakdown`, `low-score-replay`, `customer-signal`. |
| `GET /healthz`, `GET /readyz`, `GET /metrics` | Standard ops surfaces. |

## Postgres schema (5 tables, `surge_quality` schema in shared Brain Postgres)

| Table | Purpose |
|---|---|
| `responses` | one row per Surge response (text, conv_id, turn_index, identity context, embedding, timestamp) |
| `rubric_scores` | one row per (response_id, axis); 10 axes × N responses |
| `telemetry_signals` | one row per signal (response_id, signal_type, value, timestamp) |
| `claude_reviews` | one row per Claude review (response_id, diagnosis, better_response, when triggered) |
| `routing_decisions` | one row per inbound message routing (conv_id, decision, reason, score_inputs) |

DDL ships in alembic 0001-0005.

## Deployment (surgecore)
- systemd unit `surge-quality.service`
- `/opt/surge-quality/` install root; uv venv at `/opt/surge-quality/.venv` (`uv pip install --no-cache-dir`)
- port 9310 (9300/9301 in use)
- Postgres user `surge_quality` with privs on `surge_quality` schema
- secrets in `/etc/surge-quality/`: `claude.env` (600 perms), `db.env`, `surge_quality.env`

## Coordination with SOL (`surge-orchestrator`)
The routing decision (`route-decision`) is a side-effect-free read. Scoring writes only into `surge_quality` schema. **No direct execution.** When Phase 5b ships and `route-decision=claude_primary` triggers a swap of the live model in PulsePoint, that swap goes through **SOL** dispatch (capability `pulsepoint_set_model`) — not directly from surge-quality. surge-quality is a recommendation engine; SOL is the enforcer. This keeps the "chief governor" property intact (per [[surge-enterprise-plan]] §2).

## Phasing inside this repo
- **PR-1 (this commit)** — scaffold: README, PLAN, branch protection, CI shell
- **PR-2** — pyproject + Dockerfile + settings + db + alembic migrations 0001-0005 + tests
- **PR-3** — scoring service (Hermes client, rubric prompt, combined formula) + `/score-response` endpoints + tests
- **PR-4** — telemetry endpoint + smoke
- **PR-5** — Claude-as-teacher worker + `claude_reviews` writes + `/etc/surge-quality/claude.env` provisioning
- **PR-6** — routing decision endpoint + similarity lookup + classifier
- **PR-7** — dashboard (Grafana JSON + Jinja2 fallback)
- **PR-8** — PulsePoint widget extension (in `SurgeXi/pulsepoint` repo; separate PR)
- **PR-9** — surgecore deploy: systemd unit + reverse-proxy + smoke
- **PR-10** — visual smoke of dashboard (headless browser screenshot) + rollback recipe

Each PR is independently deployable + has its own rollback. **No PR ships without test coverage** (per the SurgeXi Testing Standard).
