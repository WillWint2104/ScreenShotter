import sys
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ScrollCapture")
    app.setApplicationVersion("0.1.0")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
