"""Windows desktop integration: applications, system control, and GUI."""

from assistant.desktop.application import ApplicationController
from assistant.desktop.gui import AssistantGUI
from assistant.desktop.system import SystemController

__all__ = [
    "ApplicationController",
    "AssistantGUI",
    "SystemController",
]
