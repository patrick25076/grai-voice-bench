"""voicelab — four bare Gemini Live runtimes behind one carrier bridge.

Sub-packages: ``audio`` (the only PCM code), ``carrier`` (Twilio/Telnyx frame
serializers), ``bridge`` (runtime contract, session pump, FastAPI app),
``lanes`` (one module per runtime under test), ``harness`` (scorecard, watchdog).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
