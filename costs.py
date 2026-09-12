"""Dated list-price estimates from observed SDK usage; never an invoice total."""

import math

PRICING_DATE = "2026-09-12"
SOURCES = [
    "https://developers.openai.com/api/docs/pricing",
    "https://ai.google.dev/gemini-api/docs/pricing#gemini-3.1-flash-live-preview",
]


def estimate_usage(snapshot: dict) -> dict:
    rows = []
    for usage in snapshot.get("model_usage", []):
        model = usage.get("model", "unknown")
        missing = []
        value = None
        required = {
            "gpt-live-1": ["session_duration"],
            "gpt-5.6-terra": [
                "input_tokens",
                "output_tokens",
                "input_cached_tokens",
                "input_cache_creation_tokens",
            ],
            "gemini-3.1-flash-live-preview": [
                "input_tokens",
                "output_tokens",
                "input_audio_tokens",
                "input_text_tokens",
                "output_audio_tokens",
                "output_text_tokens",
            ],
        }.get(model, [])
        invalid = [
            key
            for key in required
            if isinstance(usage.get(key), bool)
            or not isinstance(usage.get(key), (int, float))
            or not math.isfinite(usage[key])
            or usage[key] < 0
        ]
        if invalid:
            missing.append("missing or invalid usage fields: " + ", ".join(invalid))
        elif model == "gpt-live-1":
            value = usage.get("session_duration", 0) * 0.05 / 60
        elif model == "gpt-5.6-terra":
            cached = usage.get("input_cached_tokens", 0)
            writes = usage.get("input_cache_creation_tokens", 0)
            uncached = max(0, usage.get("input_tokens", 0) - cached - writes)
            if cached + writes > usage["input_tokens"]:
                missing.append("cache categories exceed total input tokens")
            else:
                value = (
                    uncached * 2 + cached * 0.2 + writes * 2.5 + usage["output_tokens"] * 12
                ) / 1e6
        elif model == "gemini-3.1-flash-live-preview":
            audio_in = usage.get("input_audio_tokens", 0)
            text_in = usage.get("input_text_tokens", 0)
            audio_out = usage.get("output_audio_tokens", 0)
            text_out = usage.get("output_text_tokens", 0)
            value = (audio_in * 3 + text_in * 0.75 + audio_out * 12 + text_out * 4.5) / 1e6
            remainder = usage.get("input_tokens", 0) - audio_in - text_in
            if remainder:
                missing.append(f"{remainder} input tokens have no captured modality")
            output_remainder = usage.get("output_tokens", 0) - audio_out - text_out
            if output_remainder:
                missing.append(f"{output_remainder} output tokens have no captured modality")
            if usage.get("input_cached_tokens", 0):
                missing.append("cached Gemini tokens need separate price reconciliation")
            if remainder < 0 or output_remainder < 0:
                value = None
                missing.append("modality categories exceed token totals")
        else:
            missing.append("model has no verified price in this dated table")
        rows.append({"model": model, "known_component_estimate_usd": value, "unresolved": missing})
    known = [
        row["known_component_estimate_usd"]
        for row in rows
        if row["known_component_estimate_usd"] is not None
    ]
    return {
        "pricing_date": PRICING_DATE,
        "sources": SOURCES,
        "models": rows,
        "known_component_estimate_usd": sum(known) if known else None,
        "invoice_total_usd": None,
        "captured_rows_complete": bool(rows) and all(not row["unresolved"] for row in rows),
        "usage_complete": False,
        "coverage": "SDK snapshot only; raw final usage and invoice reconciliation pending",
        "status": "estimate_from_observed_usage_not_final_billing",
    }
