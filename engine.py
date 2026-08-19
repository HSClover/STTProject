import os
import threading
from typing import Optional
import numpy as np
import whisper
from PyQt5.QtCore import pyqtSignal, QObject


class SignalEmitter(QObject):
    subtitle_received = pyqtSignal(str)
    log_received = pyqtSignal(str)
    engine_stopped = pyqtSignal()


class VADWhisperEngine(threading.Thread):
    def __init__(self, mode: str, target_pid: Optional[int], emitter: SignalEmitter):
        super().__init__()
        self.daemon = True
        self.mode = mode
        self.target_pid = target_pid
        self.emitter = emitter
        self.is_running = False
        self.SAMPLE_RATE = 16000

    def run(self):
        self.is_running = True
        self.emitter.log_received.emit("[엔진] OpenAI Whisper (tiny 모델) 로딩 중...")

        try:
            self.model = whisper.load_model("tiny")
            self.emitter.log_received.emit("[엔진] 모델 로드 완료! 테스트 모드 실행...")
        except Exception as e:
            self.emitter.log_received.emit(f"[에러] 모델 로드 실패: {str(e)}")
            self.emitter.engine_stopped.emit()
            return

        # 가상 테스트 루프
        try:
            import time
            while self.is_running:
                time.sleep(2.0)
                dummy_audio = np.zeros(self.SAMPLE_RATE * 2, dtype=np.float32)
                
                # OpenAI Whisper 추론 결과 타입 안정화 처리
                result = self.model.transcribe(dummy_audio, language="ko", fp16=False)
                raw_text = result.get("text", "")
                
                # 타입 에러 방지를 위한 안전한 문자열 변환 및 strip 처리
                text = str(raw_text).strip() if isinstance(raw_text, str) else ""
                
                if text:
                    self.emitter.subtitle_received.emit(text)
                else:
                    self.emitter.log_received.emit("[테스트] 정상 동작 중 (무음 감지)")
        except Exception as e:
            self.emitter.log_received.emit(f"[추론 에러]: {str(e)}")
        finally:
            self.emitter.engine_stopped.emit()

    def stop(self):
        self.is_running = False
        self.emitter.engine_stopped.emit()