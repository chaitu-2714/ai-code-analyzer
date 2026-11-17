import os


def load_stylesheet() -> str:
    """Loads the dark developer QSS stylesheet."""
    qss_path = os.path.join(os.path.dirname(__file__), "dark_theme.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""
