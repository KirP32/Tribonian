import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from tribonian.gui import Window, main

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        app = QApplication([])
        window = Window()
        window.show()
        QTimer.singleShot(500, app.quit)
        sys.exit(app.exec())
    main()
