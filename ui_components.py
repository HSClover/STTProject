from typing import Any, List
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QGraphicsDropShadowEffect
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QColor


class MinimalOverlayWindow(QWidget):
    def __init__(self, main_app):
        super().__init__(parent=None)
        self.main_app = main_app
        self.drag_position = QPoint()

        self.setWindowTitle("자막 오버레이")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(750, 150)

        self.init_ui()

    def init_ui(self):
        # 1. 메인 윈도우의 기본 레이아웃 생성 및 적용
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)

        # 2. 투명 유리알 감성 프레임 (부모 인자를 넣지 않고 생성 후 레이아웃에 추가)
        self.glass_frame = QWidget()
        self.glass_frame.setStyleSheet("""
            QWidget {
                background-color: rgba(16, 18, 24, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }
        """)

        # 3. 그림자 효과
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self.glass_frame.setGraphicsEffect(shadow)

        # 4. 프레임 내부 레이아웃 설정 (여기가 핵심: glass_frame을 부모로 하는 레이아웃 생성)
        panel_layout = QVBoxLayout(self.glass_frame)
        panel_layout.setContentsMargins(16, 10, 16, 10)

        # 5. 자막 표시용 텍스트 에디터
        self.sub_text = QTextEdit()
        self.sub_text.setReadOnly(True)
        self.sub_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sub_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sub_text.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                line-height: 1.4;
            }
        """)
        panel_layout.addWidget(self.sub_text)

        # 루트 레이아웃에 완성된 프레임 장착
        root_layout.addWidget(self.glass_frame)

    def update_font(self, font: QFont):
        self.sub_text.setFont(font)

    def update_overlay_text(self, lines: List[str]):
        color = self.main_app.text_color
        weight = "bold" if self.main_app.chk_bold.isChecked() else "normal"

        html_parts = ["<div style='margin: 0; padding: 0;'>"]
        for line in lines[-2:]:
            if line:
                html_parts.append(
                    f"<p style='color: {color}; font-weight: {weight}; margin: 0 0 4px 0;'>{line}</p>"
                )
        html_parts.append("</div>")

        self.sub_text.setHtml("".join(html_parts))
        self.sub_text.moveCursor(self.sub_text.textCursor().MoveOperation.End)

    def mousePressEvent(self, a0: Any):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.drag_position = a0.globalPos() - self.frameGeometry().topLeft()
            a0.accept()

    def mouseMoveEvent(self, a0: Any):
        if a0 and a0.buttons() == Qt.MouseButton.LeftButton:
            self.move(a0.globalPos() - self.drag_position)
            a0.accept()