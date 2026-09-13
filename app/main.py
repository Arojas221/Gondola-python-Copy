"""
Punto de entrada. Ejecutar con:  python -m app.main
"""
import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme
from app.utils.settings import AppSettings


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Scapder Vision")
    app.setOrganizationName("Scapder")

    # El tema y el tamaño de letra son del usuario y persisten entre
    # sesiones: se aplican antes de construir la ventana para que no haya
    # un parpadeo del tema por defecto en el arranque.
    apply_theme(app, AppSettings.theme(), AppSettings.font_scale())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
