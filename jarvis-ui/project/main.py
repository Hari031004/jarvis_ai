"""JARVIS Desktop - Entry point."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.main_window import JarvisWindow
from ui.theme import apply_theme
from ui.animations import shared_clock


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    app.setQuitOnLastWindowClosed(True)
    # Stop the shared animation clock when the app exits so no timer lingers.
    app.aboutToQuit.connect(shared_clock().stop)

    # Orbitron/Rajdhani are preferred if installed on the host; otherwise the
    # system falls back to a sans-serif automatically.
    fallback = QFont("Orbitron", 10)
    fallback.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(fallback)

    apply_theme(app)

    window = JarvisWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
