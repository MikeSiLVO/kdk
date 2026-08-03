"""GUI entry point for the `kdk-gui` script and the windowed PyInstaller binary."""


def main():
    # Qt is an optional extra, so a plain `pip install kdk` lands here
    try:
        from kdk.gui.app import run_gui
    except ImportError as e:
        raise SystemExit(f"kdk-gui needs PySide6 - install it with: pip install kdk[gui]\n({e})")
    run_gui()


if __name__ == "__main__":
    main()
