import logging
import os

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QGuiApplication, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

class DevSyntaxHighlighter(QSyntaxHighlighter):
    """Subclass of QSyntaxHighlighter to format keywords, comments, and strings in the viewer."""
    def __init__(self, parent: QTextDocument, language: str = "Python"):
        super().__init__(parent)
        self.highlighting_rules = []
        self.language = language

        # Format styles
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#3b82f6"))  # Accent Blue
        keyword_format.setFontWeight(QFont.Bold)

        class_format = QTextCharFormat()
        class_format.setForeground(QColor("#10b981"))    # Emerald Green
        class_format.setFontWeight(QFont.Bold)

        function_format = QTextCharFormat()
        function_format.setForeground(QColor("#f59e0b")) # Amber Gold

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#a855f7"))   # Purple

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6b7280"))  # Cool Gray
        comment_format.setFontItalic(True)

        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#ef4444"))   # Red

        # Language Keywords Lists
        python_keywords = [
            "False", "None", "True", "and", "as", "assert", "async", "await",
            "break", "class", "continue", "def", "del", "elif", "else", "except",
            "finally", "for", "from", "global", "if", "import", "in", "is",
            "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
            "while", "with", "yield", "self"
        ]

        js_ts_keywords = [
            "break", "case", "catch", "class", "const", "continue", "debugger",
            "default", "delete", "do", "else", "export", "extends", "finally",
            "for", "function", "if", "import", "in", "instanceof", "new", "return",
            "super", "switch", "this", "throw", "try", "typeof", "var", "void",
            "while", "with", "yield", "let", "package", "private", "protected",
            "public", "static", "interface", "type", "from", "async", "await"
        ]

        c_style_keywords = [
            "alignas", "alignof", "and", "and_eq", "asm", "atomic_cancel",
            "atomic_commit", "atomic_noexcept", "auto", "bitand", "bitor",
            "bool", "break", "case", "catch", "char", "char8_t", "char16_t",
            "char32_t", "class", "compl", "concept", "const", "consteval",
            "constexpr", "constinit", "const_cast", "continue", "co_await",
            "co_return", "co_yield", "decltype", "default", "delete", "do",
            "double", "dynamic_cast", "else", "enum", "explicit", "export",
            "extern", "false", "float", "for", "friend", "goto", "if", "inline",
            "int", "long", "mutable", "namespace", "new", "noexcept", "not",
            "not_eq", "nullptr", "operator", "or", "or_eq", "private", "protected",
            "public", "reflexpr", "register", "reinterpret_cast", "requires",
            "return", "short", "signed", "sizeof", "static", "static_assert",
            "static_cast", "struct", "switch", "template", "this", "thread_local",
            "throw", "true", "try", "typedef", "typeid", "typename", "union",
            "unsigned", "using", "virtual", "void", "volatile", "wchar_t", "while",
            "xor", "xor_eq"
        ]

        # Select keywords
        lang_lower = language.lower()
        keywords = python_keywords
        if "javascript" in lang_lower or "typescript" in lang_lower:
            keywords = js_ts_keywords
        elif "c" in lang_lower or "c++" in lang_lower or "java" in lang_lower or "c#" in lang_lower:
            keywords = c_style_keywords

        # Build Rules
        for word in keywords:
            pattern = QRegularExpression(r'\b' + word + r'\b')
            self.highlighting_rules.append((pattern, keyword_format))

        # Class names rule
        self.highlighting_rules.append((QRegularExpression(r'\b[A-Z_][a-zA-Z0-9_]*\b'), class_format))

        # Numeric literals rule
        self.highlighting_rules.append((QRegularExpression(r'\b[0-9]+(?:\.[0-9]+)?\b'), number_format))

        # String literals rule
        self.highlighting_rules.append((QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), string_format))
        self.highlighting_rules.append((QRegularExpression(r"'[^'\\]*(?:\\.[^'\\]*)*'"), string_format))

        # Comment rules
        if "python" in lang_lower or "ruby" in lang_lower:
            self.highlighting_rules.append((QRegularExpression(r'#[^\n]*'), comment_format))
        else:
            self.highlighting_rules.append((QRegularExpression(r'//[^\n]*'), comment_format))
            # Multiline comment bounds (simplified for single line parsing)
            self.highlighting_rules.append((QRegularExpression(r'/\*.*?\*/'), comment_format))

    def highlightBlock(self, text: str):
        """Highlights matching regex formats line-by-line."""
        for pattern, fmt in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class CodeViewerWidget(QWidget):
    """Monospace code editor display showing syntax rules and copy options."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_content = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Header Info Bar
        info_layout = QHBoxLayout()
        self.lbl_path = QLabel("Select a file from the explorer tree to view")
        self.lbl_path.setStyleSheet("font-size: 13px; font-weight: bold; color: #3b82f6;")

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet("color: #8b8b9c;")

        info_layout.addWidget(self.lbl_path)
        info_layout.addStretch()
        info_layout.addWidget(self.lbl_stats)
        layout.addLayout(info_layout)

        # Toolbar controls: Search field + Copy button
        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search keyword in code...")
        self.search_input.setMaximumWidth(250)
        self.search_input.textChanged.connect(self.search_text)

        btn_copy = QPushButton("Copy Code")
        btn_copy.setObjectName("SecondaryButton")
        btn_copy.clicked.connect(self.copy_to_clipboard)

        toolbar.addWidget(self.search_input)
        toolbar.addStretch()
        toolbar.addWidget(btn_copy)
        layout.addLayout(toolbar)

        # Monospace Text Box
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QTextEdit.NoWrap)

        # Configure Monospace Font
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)

        self.editor.setFont(font)
        layout.addWidget(self.editor)

        self.highlighter = None

    def load_file(self, file_path: str, relative_path: str, language: str):
        """Loads and formats file content into the text widget."""
        if not os.path.exists(file_path):
            QMessageBox.critical(self, "Error", f"File '{file_path}' no longer exists.")
            return

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            self.current_content = content
            self.editor.setPlainText(content)

            # Update labels
            self.lbl_path.setText(relative_path)
            lines = len(content.splitlines())
            size_kb = len(content) / 1024
            self.lbl_stats.setText(f"{language} | {lines} lines | {size_kb:.1f} KB")

            # Apply syntax highlighting
            self.highlighter = DevSyntaxHighlighter(self.editor.document(), language)

        except Exception as e:
            logger.error(f"Failed to read file for viewer {file_path}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load file contents: {e}")

    def search_text(self, text: str):
        """Finds and highlights search matches in editor."""
        if not text:
            # Clear search selections by re-setting editor content
            self.editor.setPlainText(self.current_content)
            return

        # Simple text highlight search
        self.editor.setPlainText(self.current_content)
        cursor = self.editor.document().find(text)
        if not cursor.isNull():
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def copy_to_clipboard(self):
        if not self.current_content:
            return
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.current_content)
        QMessageBox.information(self, "Clipboard", "Code copied to clipboard successfully.")
