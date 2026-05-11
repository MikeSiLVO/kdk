"""GUI entry point for the `kdk-gui` script and the windowed PyInstaller binary."""

from kdk.gui.app import run_gui


def main():
    run_gui()


if __name__ == "__main__":
    main()
