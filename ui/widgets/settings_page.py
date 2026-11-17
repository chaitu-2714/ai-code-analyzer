"""Settings page: read-only view of the effective configuration and provider health."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from llm.factory import create_provider
from repair.engine import RepairEngine
from ui.widgets.common import page_header, secondary_button

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    """Displays configuration, LLM provider status and repair coverage."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        layout.addWidget(
            page_header("Settings", "Effective configuration. Edit .env and restart to change these.")
        )

        panel = QFrame()
        panel.setStyleSheet("QFrame { background: #171a23; border: 1px solid #242835; border-radius: 10px; }")
        form = QFormLayout(panel)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)

        for label, value in self._rows():
            key = QLabel(label)
            key.setStyleSheet("color: #8b8b9c;")
            val = QLabel(str(value))
            val.setStyleSheet("color: #ffffff;")
            val.setWordWrap(True)
            form.addRow(key, val)
        layout.addWidget(panel)

        provider_row = QHBoxLayout()
        self.provider_status = QLabel("Provider status: unknown")
        self.provider_status.setStyleSheet("color: #b9b9c9;")
        provider_row.addWidget(self.provider_status)
        check_button = secondary_button("Check LLM provider")
        check_button.clicked.connect(self.check_provider)
        provider_row.addWidget(check_button)
        provider_row.addStretch()
        layout.addLayout(provider_row)

        self.repair_label = QLabel(
            "Automatic repair templates: " + ", ".join(RepairEngine.supported_rules())
        )
        self.repair_label.setWordWrap(True)
        self.repair_label.setStyleSheet("color: #626270; font-size: 12px;")
        layout.addWidget(self.repair_label)
        layout.addStretch()

    def _rows(self):
        config = self.config
        if config is None:
            return [("Configuration", "not loaded")]
        return [
            ("Application", f"{config.app_name} v{config.app_version}"),
            ("Database", config.database_url),
            ("Log file", f"{config.log_file} (level {config.log_level})"),
            ("LLM provider mode", config.llm_provider),
            ("Gemini model", config.gemini_model if config.gemini_api_key else "not configured"),
            ("Agents enabled", config.agents_enabled),
            ("Complexity threshold", config.complexity_threshold),
            ("Long function threshold", config.long_function_threshold),
            ("Duplicate window (lines)", config.duplicate_window_lines),
            ("Verification timeout", f"{config.verify_timeout_seconds}s"),
        ]

    def check_provider(self) -> None:
        try:
            provider = create_provider(self.config)
            info = provider.describe()
        except Exception as error:  # pragma: no cover - defensive
            self.provider_status.setText(f"Provider error: {error}")
            return
        self.provider_status.setText(
            f"Provider: {info['provider']} (model {info['model']}) - "
            + ("ready" if info["available"] else "unavailable, offline insights will be used")
        )
