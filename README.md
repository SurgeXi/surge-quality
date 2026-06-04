# surge-quality

Surge quality rubric + auto-scoring + customer telemetry. Measures how good Surge's responses are so we can gate the Claude→Surge takeover (per [PulsePoint design decisions](https://github.com/SurgeXi/.../memory/project_pulsepoint_design_decisions.md), Phase 5 Phase A prep).

**Status:** scaffolding — see `docs/PLAN.md` for the buildable spec and component breakdown.

## What this is

Without this infrastructure, Phase 5 (Surge takes customer-facing replies) is unmeasurable; we can't tell if Surge is keeping up with Claude's quality bar. This service:

1. **Scores every Surge response** on a 10-axis rubric (correctness, tone, completeness, action-orientation, brevity, citation quality, identity awareness, memory usage, safety, confidence calibration). Scoring model: surge-ai Hermes 3; ground-truth trainer: Claude.
2. **Captures customer telemetry** from the PulsePoint widget (thumbs, reply-time, drop-off, re-asks, escalation requests).
3. **Combines** rubric + telemetry into a single per-response quality score.
4. **Closes the loop with Claude-as-teacher** — when Surge scores low, Claude is auto-invoked to generate a better response + a what-was-wrong diff, both logged as training data.
5. **Routes incoming customer turns** to Surge, Surge-with-Claude-review, or Claude-primary based on similarity to past low-scoring turns, topic complexity, urgency, and identity context.
6. **Surfaces a Grafana dashboard** for Todd: Surge share %, average score, topic breakdown, low-score replay, per-customer signal.

## Where it runs

- Service: **surgecore** (co-resident with Brain, SOL, Broker) — `surge-quality.service`, port **9310**
- DB: **shared with Brain Postgres** at `surge_brain` cluster, dedicated `surge_quality` schema
- Telemetry source: **PulsePoint widget** on surge-storage:8096 (extension PR ships separately)
- Dashboard: **Grafana** panels (preferred) — Jinja2 fallback included

## Architecture
See `docs/PLAN.md`.

## Branch protection
This repo follows the SurgeXi day-1 rule (locked 2026-06-03): `main` is protected — PR required, CI must pass before merge, no force-push, no deletion.
