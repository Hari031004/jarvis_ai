"""Unified UI-enabled entry point for the JARVIS assistant.

This launcher:
1. Adds the root directory to sys.path so the assistant package is importable.
2. Initializes the PySide6 QApplication and the JarvisWindow HUD interface.
3. Initializes the EventBus -> JarvisBridge -> PySideDispatcher -> PySideAdapter pipeline.
4. Spawns the original AIBrain backend loop on a daemon thread.
5. Begins the Qt event loop, allowing smooth, thread-safe HUD updates.
6. Cleans up event subscriptions and dispatches on shutdown.
"""

from __future__ import annotations

import sys
from pathlib import Path
import threading

# Ensure assistant package is importable
_here = Path(__file__).parent.resolve()
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# Add jarvis-ui/project folder to sys.path so PySide6 modules can import ui.*
_ui_path = _here / "jarvis-ui" / "project"
if str(_ui_path) not in sys.path:
    sys.path.insert(0, str(_ui_path))

from PySide6.QtWidgets import QApplication

import signal
from PySide6.QtCore import QTimer

from assistant.config import load_settings
from assistant.brain import AIBrain
from assistant.core.event_bus import get_event_bus
from assistant.core.system_monitor import SystemMonitorService
from assistant.ui.bridge import get_bridge
from assistant.ui.adapters.pyside_adapter import PySideAdapter, PySideDispatcher
from ui.main_window import JarvisWindow


def main() -> None:
    # 1. Initialize PySide6 Application
    app = QApplication(sys.argv)

    # Set up SIGINT (Ctrl+C) handler to exit QApplication cleanly
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # Set up a timer to periodically yield control to Python interpreter,
    # allowing Python to process signals (like SIGINT / Ctrl+C) while app.exec() blocks.
    sig_timer = QTimer()
    sig_timer.setInterval(200)
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start()
    
    # 2. Load Settings
    settings = load_settings()
    settings.enable_gui = False  # Disable original Tkinter GUI

    # 3. Create JarvisWindow
    window = JarvisWindow()

    # 4. Create PySideAdapter and connect the window
    adapter = PySideAdapter()
    adapter.connect_window(window)
    
    # 5. Create PySideDispatcher
    dispatcher = PySideDispatcher(adapter)
    
    # 6. Create JarvisBridge
    bridge = get_bridge()
    
    # 7. Attach dispatcher
    bridge.attach(dispatcher)
    
    # 8. Start bridge (registers EventBus subscriptions)
    bridge.start()
    
    # 9. Start dispatcher (starts the QTimer drain loop)
    dispatcher.start()

    # 10. Show Window
    window.show()

    # 11. Start system diagnostics monitor
    monitor_service = SystemMonitorService(interval_seconds=1.0)
    monitor_service.start()

    # 12. Start backend thread
    brain = AIBrain(settings)
    backend_thread = threading.Thread(
        target=brain.run_forever,
        name="jarvis-backend",
        daemon=True
    )
    backend_thread.start()

    # 13. Execute Qt GUI Main Loop and manage clean shutdown in finally block
    try:
        sys.exit(app.exec())
    finally:
        # Request backend stop
        brain.stop()
        
        # Stop system diagnostics monitor
        monitor_service.stop()
        
        # Stop bridge (unsubscribes from EventBus)
        bridge.stop()
        
        # Stop dispatcher (stops QTimer and flushes remaining events)
        dispatcher.stop()
        
        # Detach dispatcher
        bridge.detach()
        
        # Wait briefly for backend thread to finish if running
        backend_thread.join(timeout=2.0)




if __name__ == "__main__":
    main()
