import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("TracoFirme")
    app.setApplicationName("Traço Firme")
    # Botões padrão do Qt (Fechar, Sim, Não, Salvar…) em português.
    translator = QTranslator(app)
    if translator.load(QLocale("pt_BR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    w = MainWindow()
    w.showMaximized()
    args = [a for a in sys.argv[1:] if a.lower().endswith(".traco")]
    if args:
        w.open_project(args[0])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
