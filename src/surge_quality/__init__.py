"""surge-quality — recommender service for the Surge quality loop.

Read-only by design: scores responses, captures telemetry, asks the LLM reviewer to
teach when Surge underperforms, and emits routing-decision advice.
Side-effects (model swaps in PulsePoint) route through SOL.
"""

__version__ = "0.1.0"
