"""MIGZ AI Orchestra release identity."""

ORCHESTRA_NAME = "MIGZ AI ORCHESTRA"
ORCHESTRA_VERSION = "4.0.0"
ORCHESTRA_CODENAME = "OPEN ORCHESTRA"


def display_name() -> str:
    return f"{ORCHESTRA_NAME} V{ORCHESTRA_VERSION.split('.', 1)[0]}"
