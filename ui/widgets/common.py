"""Shared UI helpers: background worker, tables, badges and small charts."""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, QPointF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

SEVERITY_COLORS = {
    "CRITICAL": "#e5484d",
    "HIGH": "#f76b15",
    "MEDIUM": "#f5a524",
    "LOW": "#3b82f6",
    "INFO": "#8b8b9c",
}

RISK_COLORS = {
    "CRITICAL": "#e5484d",
    "HIGH": "#f76b15",
    "MODERATE": "#f5a524",
    "LOW": "#30a46c",
}


class Worker(QThread):
    """Runs a long callable off the GUI thread.

    The callable receives a ``progress(name, percent)`` function and returns a
    picklable-ish result (any Python object) which is delivered on the GUI thread.
    """

    succeeded = Signal(object)
    failed = Signal(str)
    progressed = Signal(str, int)

    def __init__(self, task: Callable[[Callable[[str, int], None]], object], parent=None):
        super().__init__(parent)
        self._task = task

    def run(self) -> None:  # pragma: no cover - exercised through the GUI
        try:
            result = self._task(lambda name, percent: self.progressed.emit(str(name), int(percent)))
            self.succeeded.emit(result)
        except Exception as error:  # noqa: BLE001 - reported to the user
            logger.exception("Background task failed")
            self.failed.emit(str(error))


def start_worker(
    owner: QObject,
    task: Callable[[Callable[[str, int], None]], object],
    on_success: Callable[[object], None],
    on_error: Callable[[str], None],
    on_progress: Optional[Callable[[str, int], None]] = None,
) -> Worker:
    """Starts ``task`` in a thread and keeps a reference on ``owner``."""
    worker = Worker(task)
    if on_progress is not None:
        worker.progressed.connect(on_progress)
    worker.succeeded.connect(on_success)
    worker.failed.connect(on_error)
    workers = getattr(owner, "_workers", None)
    if workers is None:
        workers = []
        owner._workers = workers  # type: ignore[attr-defined]
    workers.append(worker)
    worker.finished.connect(lambda: workers.remove(worker) if worker in workers else None)
    worker.start()
    return worker


def page_header(title: str, subtitle: str = "") -> QWidget:
    """Standard page header with an optional subtitle."""
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    heading = QLabel(title)
    heading.setObjectName("PageHeader")
    layout.addWidget(heading)
    if subtitle:
        caption = QLabel(subtitle)
        caption.setStyleSheet("color: #8b8b9c; font-size: 13px;")
        caption.setWordWrap(True)
        layout.addWidget(caption)
    return wrapper


def stat_card(label: str, value: str = "--") -> QFrame:
    """Small KPI card; returns the frame whose ``value`` label is accessible."""
    card = QFrame()
    card.setObjectName("StatCard")
    card.setStyleSheet(
        "QFrame#StatCard { background: #171a23; border: 1px solid #242835; border-radius: 10px; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 12, 16, 12)
    layout.setSpacing(4)
    title = QLabel(label.upper())
    title.setStyleSheet("color: #8b8b9c; font-size: 11px; letter-spacing: 1px;")
    value_label = QLabel(value)
    value_label.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 600;")
    layout.addWidget(title)
    layout.addWidget(value_label)
    card.value_label = value_label  # type: ignore[attr-defined]
    return card


def make_table(headers: Sequence[str], stretch: bool = True) -> QTableWidget:
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    if stretch:
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    return table


def set_row(table: QTableWidget, row: int, values: Sequence[str], colors: Optional[Sequence[Optional[str]]] = None) -> None:
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        if colors and column < len(colors) and colors[column]:
            item.setForeground(QColor(colors[column]))
            font = QFont()
            font.setBold(True)
            item.setFont(font)
        table.setItem(row, column, item)


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("PrimaryButton")
    button.setProperty("class", "PrimaryButton")
    button.setCursor(Qt.PointingHandCursor)
    return button


def secondary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("SecondaryButton")
    button.setProperty("class", "SecondaryButton")
    button.setCursor(Qt.PointingHandCursor)
    return button


class Sparkline(QWidget):
    """Minimal score trend chart drawn with QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: List[float] = []
        self.setMinimumHeight(120)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = [float(value) for value in values]
        self.update()

    def sizeHint(self) -> QSize:  # pragma: no cover - GUI only
        return QSize(400, 140)

    def paintEvent(self, event) -> None:  # pragma: no cover - GUI only
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#12141c"))
        painter.setPen(QPen(QColor("#242835"), 1))
        for fraction in (0.25, 0.5, 0.75):
            y = int(self.height() * fraction)
            painter.drawLine(0, y, self.width(), y)

        if len(self._values) < 2:
            painter.setPen(QColor("#8b8b9c"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Not enough reviews yet")
            return

        margin = 12
        width = max(self.width() - margin * 2, 1)
        height = max(self.height() - margin * 2, 1)
        step = width / (len(self._values) - 1)
        points = []
        for index, value in enumerate(self._values):
            x = margin + index * step
            y = margin + height - (max(0.0, min(100.0, value)) / 100.0) * height
            points.append(QPointF(x, y))

        painter.setPen(QPen(QColor("#7c5cff"), 2))
        painter.drawPolyline(QPolygonF(points))
        painter.setBrush(QColor("#7c5cff"))
        for point in points:
            painter.drawEllipse(point, 3, 3)


class StatCardsRow(QWidget):
    """Horizontal row of :func:`stat_card` widgets with a ``set_value`` helper."""

    def __init__(self, labels: Sequence[str], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.cards: Dict[str, QFrame] = {}
        for label in labels:
            card = stat_card(label)
            self.cards[label] = card
            layout.addWidget(card)

    def set_value(self, label: str, value: object) -> None:
        card = self.cards.get(label)
        if card is not None:
            card.value_label.setText(str(value))  # type: ignore[attr-defined]
