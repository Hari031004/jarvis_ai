"""Entry point for the JARVIS-style AI operating system."""

from __future__ import annotations

from assistant.brain import AIBrain, JarvisAssistant
from assistant.config import load_settings


def main() -> None:
    brain = AIBrain(load_settings())
    brain.run_forever()


if __name__ == "__main__":
    main()
