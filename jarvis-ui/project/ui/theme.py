"""Neon-blue JARVIS theme constants and QSS stylesheet."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class Colors:
    BG_DEEP = "#020610"
    BG_GLASS = "rgba(8, 16, 32, 180)"
    BG_PANEL = "rgba(10, 22, 40, 200)"
    BG_HOVER = "rgba(20, 40, 70, 220)"

    NEON = "#00E5FF"
    NEON_DIM = "#0099B8"
    NEON_GLOW = "#33E6FF"
    NEON_SOFT = "rgba(0, 229, 255, 40)"

    ACCENT = "#7DF9FF"
    WARNING = "#FFB546"
    DANGER = "#FF4D5E"
    SUCCESS = "#3DD68C"

    TEXT_PRIMARY = "#E6FBFF"
    TEXT_SECONDARY = "#7FB8C8"
    TEXT_MUTED = "#4A6B7B"

    BORDER = "rgba(0, 229, 255, 60)"
    BORDER_SOFT = "rgba(0, 229, 255, 30)"


class Fonts:
    DISPLAY = "Orbitron"
    UI = "Rajdhani"
    MONO = "JetBrains Mono"

    H1 = 26
    H2 = 18
    BODY = 13
    SMALL = 11
    MICRO = 9


QSS = f"""
* {{
    font-family: "Rajdhani", "Segoe UI", sans-serif;
    color: {Colors.TEXT_PRIMARY};
    outline: none;
}}

QWidget#GlassRoot {{
    background: transparent;
}}

QFrame#SideBar {{
    background: {Colors.BG_GLASS};
    border-right: 1px solid {Colors.BORDER};
}}

QFrame#TopBar {{
    background: {Colors.BG_GLASS};
    border-bottom: 1px solid {Colors.BORDER_SOFT};
}}

QPushButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 8px 14px;
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.BODY}px;
}}
QPushButton:hover {{
    color: {Colors.NEON};
    background: {Colors.NEON_SOFT};
    border: 1px solid {Colors.BORDER_SOFT};
}}
QPushButton:pressed {{
    background: {Colors.NEON_DIM};
    color: {Colors.BG_DEEP};
}}

QPushButton#NavButton {{
    text-align: left;
    padding: 12px 18px;
    font-size: {Fonts.BODY}px;
    font-weight: 600;
    letter-spacing: 1px;
    border-radius: 12px;
}}
QPushButton#NavButton:hover {{
    background: {Colors.NEON_SOFT};
    border: 1px solid {Colors.BORDER_SOFT};
}}
QPushButton#NavButton:checked {{
    color: {Colors.NEON};
    background: {Colors.NEON_SOFT};
    border: 1px solid {Colors.BORDER};
}}

QPushButton#IconButton {{
    padding: 6px;
    border-radius: 8px;
}}

QLabel#Title {{
    font-family: "Orbitron", sans-serif;
    font-size: {Fonts.H2}px;
    font-weight: 700;
    color: {Colors.NEON};
    letter-spacing: 3px;
}}
QLabel#Subtitle {{
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.SMALL}px;
    letter-spacing: 2px;
}}
QLabel#Brand {{
    font-family: "Orbitron", sans-serif;
    font-size: 22px;
    font-weight: 800;
    color: {Colors.NEON};
    letter-spacing: 6px;
}}
QLabel#StatValue {{
    font-family: "Orbitron", sans-serif;
    font-size: 22px;
    font-weight: 700;
    color: {Colors.NEON};
}}
QLabel#StatLabel {{
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.MICRO}px;
    letter-spacing: 2px;
}}
QLabel#ClockTime {{
    font-family: "Orbitron", sans-serif;
    font-size: 48px;
    font-weight: 700;
    color: {Colors.NEON};
    letter-spacing: 4px;
}}
QLabel#ClockDate {{
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.SMALL}px;
    letter-spacing: 3px;
}}

/* Glass cards: layered translucent base + soft neon edge highlight + inner
   top sheen for depth. Border-radius stays at 16px (design unchanged). */
QFrame#Card {{
    background: {Colors.BG_PANEL};
    border: 1px solid {Colors.BORDER_SOFT};
    border-radius: 16px;
}}
QFrame#CardRaised {{
    background: {Colors.BG_PANEL};
    border: 1px solid {Colors.BORDER};
    border-radius: 16px;
}}

QTextEdit#ChatView, QLineEdit#ChatInput {{
    background: rgba(2, 8, 18, 180);
    border: 1px solid {Colors.BORDER_SOFT};
    border-radius: 12px;
    padding: 10px;
    color: {Colors.TEXT_PRIMARY};
    selection-background-color: {Colors.NEON_DIM};
}}
QTextEdit#ChatView {{
    font-size: {Fonts.BODY}px;
    border: none;
}}
QLineEdit#ChatInput {{
    font-size: {Fonts.BODY}px;
}}
QLineEdit#ChatInput:focus {{
    border: 1px solid {Colors.NEON};
}}

QListWidget#HistoryList {{
    background: transparent;
    border: 1px solid {Colors.BORDER_SOFT};
    border-radius: 12px;
    padding: 6px;
    outline: 0;
}}
QListWidget#HistoryList::item {{
    color: {Colors.TEXT_PRIMARY};
    padding: 10px 12px;
    border-bottom: 1px solid {Colors.BORDER_SOFT};
}}
QListWidget#HistoryList::item:hover {{
    background: {Colors.NEON_SOFT};
}}
QListWidget#HistoryList::item:selected {{
    color: {Colors.NEON};
    background: {Colors.NEON_SOFT};
    border-left: 2px solid {Colors.NEON};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {Colors.NEON_DIM};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.NEON};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QProgressBar {{
    background: rgba(2, 8, 18, 200);
    border: 1px solid {Colors.BORDER_SOFT};
    border-radius: 6px;
    text-align: center;
    color: {Colors.NEON};
    font-size: {Fonts.MICRO}px;
    height: 10px;
}}
QProgressBar::chunk {{
    background: {Colors.NEON};
    border-radius: 5px;
}}

QPushButton#SendButton {{
    background: {Colors.NEON};
    color: {Colors.BG_DEEP};
    border-radius: 12px;
    font-weight: 700;
    padding: 10px 20px;
    letter-spacing: 1px;
}}
QPushButton#SendButton:hover {{
    background: {Colors.ACCENT};
}}
QPushButton#SendButton:pressed {{
    background: {Colors.NEON_DIM};
}}
QPushButton#SendButton:disabled {{
    background: {Colors.NEON_DIM};
    color: {Colors.TEXT_MUTED};
}}

QPushButton#WindowBtn {{
    padding: 4px 10px;
    border-radius: 6px;
    color: {Colors.TEXT_SECONDARY};
    font-size: 14px;
}}
QPushButton#WindowBtn:hover {{
    color: {Colors.NEON};
    background: {Colors.NEON_SOFT};
}}
QPushButton#WindowBtn#CloseBtn:hover {{
    color: {Colors.DANGER};
    background: rgba(255,77,94,40);
}}

/* Typing indicator dots shown in the chat panel footer. */
QLabel#TypingDot {{
    color: {Colors.NEON};
    background: {Colors.NEON};
    border-radius: 4px;
}}
"""


def apply_theme(app: QApplication) -> None:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(Colors.BG_DEEP))
    pal.setColor(QPalette.ColorRole.Base, QColor(Colors.BG_DEEP))
    pal.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT_PRIMARY))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(Colors.TEXT_PRIMARY))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.TEXT_SECONDARY))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(Colors.NEON_DIM))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(Colors.BG_DEEP))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
