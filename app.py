import sys
import os
import ctypes
from ctypes import wintypes
from typing import Optional, List, Tuple
import ctypes

try:
    # 윈도우 COM 스레딩 모델 충돌(RPC_E_CHANGED_MODE)을 방지하기 위한 초기화
    ctypes.windll.ole32.CoInitializeEx(None, 2) # COINIT_APARTMENTTHREADED = 2
except Exception:
    pass

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTextEdit, QGroupBox, QSplitter,
    QFontComboBox, QSpinBox, QRadioButton, QButtonGroup,
    QCheckBox, QColorDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor, QFont, QColor, QFontDatabase

from engine import SignalEmitter, VADWhisperEngine
from ui_components import MinimalOverlayWindow


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_open_windows() -> List[Tuple[str, int]]:
    user32 = ctypes.windll.user32
    windows_list: List[Tuple[str, int]] = []

    def enum_windows_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()
                if title and title not in ["Program Manager", "Settings", "Microsoft Text Input Application"]:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    windows_list.append((title, pid.value))
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(enum_windows_proc), 0)
    return windows_list


def load_custom_fonts():
    font_dir = os.path.join(ROOT_DIR, "fonts")
    if os.path.exists(font_dir):
        for f in os.listdir(font_dir):
            if f.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, f))


class MainAppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STTProject - LiveSubtitle")
        self.resize(1000, 780)

        self.text_color = "#00E5FF"
        self.active_mode = "mic"
        self.active_target_pid: Optional[int] = None

        load_custom_fonts()

        self.emitter = SignalEmitter()
        self.emitter.subtitle_received.connect(self.on_subtitle_received)
        self.emitter.log_received.connect(self.update_log)
        self.emitter.engine_stopped.connect(self._on_engine_stopped)

        self.engine_thread: Optional[VADWhisperEngine] = None
        self.is_running = False
        self.completed_lines: List[str] = []

        self.init_ui()
        self.overlay_window = None

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # 1. 입력 모드 & 창 선택
        mode_group = QGroupBox("1. 입력 모드 및 대상 창 선택")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)

        self.radio_mic = QRadioButton("마이크 (Microphone)")
        self.radio_audio = QRadioButton("오디오 (스피커/특정 창)")
        self.radio_mic.setChecked(True)

        self.btn_group_mode = QButtonGroup(self)
        self.btn_group_mode.addButton(self.radio_mic)
        self.btn_group_mode.addButton(self.radio_audio)
        self.radio_mic.toggled.connect(self.on_mode_toggled)

        mode_layout.addWidget(self.radio_mic)
        mode_layout.addWidget(self.radio_audio)

        mode_layout.addWidget(QLabel("창 선택:"))
        self.window_combo = QComboBox()
        self.window_combo.setEnabled(False)
        mode_layout.addWidget(self.window_combo, 1)

        self.btn_refresh_windows = QPushButton("🔄")
        self.btn_refresh_windows.setToolTip("열려 있는 창 목록 새로고침")
        self.btn_refresh_windows.setEnabled(False)
        self.btn_refresh_windows.clicked.connect(self.refresh_window_list)
        mode_layout.addWidget(self.btn_refresh_windows)

        self.btn_apply_mode = QPushButton("입력 설정 적용")
        self.btn_apply_mode.setStyleSheet("font-weight: bold; background-color: #2E7D32; color: white;")
        self.btn_apply_mode.clicked.connect(self.apply_audio_mode)
        mode_layout.addWidget(self.btn_apply_mode)

        main_layout.addWidget(mode_group)

        # 2. 폰트 & 스타일 설정
        config_group = QGroupBox("2. 폰트 및 스타일 설정")
        config_layout = QHBoxLayout()
        config_group.setLayout(config_layout)

        config_layout.addWidget(QLabel("폰트:"))
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(self.apply_font_settings)
        config_layout.addWidget(self.font_combo)

        config_layout.addWidget(QLabel("크기:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(10, 36)
        self.font_size_spin.setValue(15)
        self.font_size_spin.valueChanged.connect(self.apply_font_settings)
        config_layout.addWidget(self.font_size_spin)

        self.btn_color = QPushButton("자막 색상")
        self.btn_color.setStyleSheet(f"background-color: {self.text_color}; color: black; font-weight: bold;")
        self.btn_color.clicked.connect(self.choose_color)
        config_layout.addWidget(self.btn_color)

        self.chk_bold = QCheckBox("볼드")
        self.chk_bold.setChecked(True)
        self.chk_bold.stateChanged.connect(self.apply_font_settings)
        config_layout.addWidget(self.chk_bold)

        main_layout.addWidget(config_group)

        # 3. 제어 버튼 패널
        btn_group = QGroupBox("제어 (Controls)")
        btn_layout = QHBoxLayout()
        btn_group.setLayout(btn_layout)

        self.btn_toggle_start = QPushButton("자막 시작 (Start)")
        self.btn_toggle_start.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px;")
        self.btn_toggle_start.clicked.connect(self.toggle_start)
        btn_layout.addWidget(self.btn_toggle_start)

        self.btn_toggle_overlay = QPushButton("Show Overlay")
        self.btn_toggle_overlay.clicked.connect(self.toggle_overlay)
        btn_layout.addWidget(self.btn_toggle_overlay)

        self.btn_clear = QPushButton("자막 지우기")
        self.btn_clear.clicked.connect(self.clear_subtitles)
        btn_layout.addWidget(self.btn_clear)

        main_layout.addWidget(btn_group)

        # 4. 스플리터 텍스트 영역
        splitter = QSplitter(Qt.Orientation.Vertical)

        trans_group = QGroupBox("실시간 자막 (Transcription)")
        trans_layout = QVBoxLayout()
        trans_group.setLayout(trans_layout)
        self.trans_text = QTextEdit()
        self.trans_text.setReadOnly(True)
        trans_layout.addWidget(self.trans_text)
        splitter.addWidget(trans_group)

        log_group = QGroupBox("로그 (Logs)")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        splitter.addWidget(log_group)

        main_layout.addWidget(splitter)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.text_color), self, "자막 색상 선택")
        if color.isValid():
            self.text_color = color.name()
            self.btn_color.setStyleSheet(f"background-color: {self.text_color}; color: black; font-weight: bold;")
            self._render_view()

    def on_mode_toggled(self):
        is_audio = self.radio_audio.isChecked()
        self.window_combo.setEnabled(is_audio)
        self.btn_refresh_windows.setEnabled(is_audio)
        if is_audio:
            self.refresh_window_list()

    def refresh_window_list(self):
        current_data = self.window_combo.currentData()
        self.window_combo.clear()
        self.window_combo.addItem("[전체] 시스템 기본 스피커", None)
        windows = get_open_windows()
        selected_index = 0
        for idx, (title, pid) in enumerate(windows, start=1):
            display_title = title if len(title) <= 45 else title[:42] + "..."
            self.window_combo.addItem(f"{display_title} (PID: {pid})", pid)
            if current_data is not None and pid == current_data:
                selected_index = idx
        self.window_combo.setCurrentIndex(selected_index)

    def apply_audio_mode(self):
        self.active_mode = "mic" if self.radio_mic.isChecked() else "audio"
        self.active_target_pid = self.window_combo.currentData() if self.active_mode == "audio" else None
        target_str = "마이크" if self.active_mode == "mic" else f"오디오 루프백 [{self.window_combo.currentText()}]"
        self.emitter.log_received.emit(f"[설정 적용] 입력 소스: {target_str}")

    def apply_font_settings(self):
        selected_font = self.font_combo.currentFont()
        font_size = self.font_size_spin.value()
        selected_font.setPointSize(font_size)
        self.trans_text.setFont(selected_font)

        if self.overlay_window:
            overlay_font = QFont(selected_font)
            overlay_font.setPointSize(font_size + 3)
            self.overlay_window.update_font(overlay_font)
            self._render_view()

    def toggle_overlay(self):
        if not self.overlay_window:
            self.overlay_window = MinimalOverlayWindow(self)
            self.apply_font_settings()

        if self.overlay_window.isVisible():
            self.overlay_window.hide()
            self.btn_toggle_overlay.setText("Show Overlay")
        else:
            self.overlay_window.show()
            self.btn_toggle_overlay.setText("Hide Overlay")

    def clear_subtitles(self):
        self.completed_lines = []
        self.trans_text.clear()
        if self.overlay_window:
            self.overlay_window.update_overlay_text([])

    def _render_view(self):
        self.trans_text.setPlainText("\n".join(self.completed_lines))
        self.trans_text.moveCursor(QTextCursor.MoveOperation.End)
        if self.overlay_window and self.overlay_window.isVisible():
            self.overlay_window.update_overlay_text(self.completed_lines)

    def on_subtitle_received(self, text: str):
        if text.strip():
            self.completed_lines.append(text.strip())
            self._render_view()

    def update_log(self, text: str):
        self.log_text.append(text)

    def toggle_start(self):
        if not self.is_running:
            self.start_engine()
        else:
            self.stop_engine()

    def start_engine(self):
        if self.is_running:
            return

        self.engine_thread = VADWhisperEngine(
            mode=self.active_mode,
            target_pid=self.active_target_pid,
            emitter=self.emitter
        )
        self.engine_thread.start()
        self.is_running = True
        self.btn_toggle_start.setText("자막 정지 (Stop)")
        self.btn_toggle_start.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px; background-color: #C62828; color: white;")

    def stop_engine(self):
        if self.engine_thread:
            self.engine_thread.stop()
            self.engine_thread = None
        self.is_running = False
        self.btn_toggle_start.setText("자막 시작 (Start)")
        self.btn_toggle_start.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px;")

    def _on_engine_stopped(self):
        self.is_running = False
        self.btn_toggle_start.setText("자막 시작 (Start)")
        self.btn_toggle_start.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px;")

    def closeEvent(self, a0):
        if self.overlay_window:
            try:
                self.overlay_window.close()
            except:
                pass
        self.stop_engine()
        if a0:
            a0.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainAppWindow()
    window.show()
    sys.exit(app.exec_())