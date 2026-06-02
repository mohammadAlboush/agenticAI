"""Pytest-Setup: CrewAI/OTEL-Telemetrie abschalten, bevor crewai importiert wird.

conftest wird von pytest sehr frueh geladen - vor den Testmodulen, die ueber den
Flow crewai importieren. So entstehen im Test keine Telemetrie-Netzwerkaufrufe.
"""

import os

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
