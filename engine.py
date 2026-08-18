import os
import threading
from typing import Optional
import numpy as np
from scipy import signal

# 안전한 백엔드 구성을 위한 예외 처리형 임포트
try:
    import pyaudio
except Exception as e:
    pyaudio = None

try:
    import soundcard as sc
except Exception as e:
    sc = None

from faster_whisper import WhisperModel
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
        self.emitter.log_received.emit("[엔진] Whisper 모델 로딩 중 (안전 CPU 모드)...")

        try:
            # 안전하게 CPU int8로 먼저 구동 테스트
            self.model = WhisperModel(
                "medium", 
                device="cpu", 
                compute_type="int8"
            )
            self.emitter.log_received.emit("[엔진] 모델 로드 성공. 오디오 스트림 연결 시도...")
        except Exception as e:
            self.emitter.log_received.emit(f"[에러] 모델 로드 실패: {str(e)}")
            self.emitter.engine_stopped.emit()
            return

        try:
            if self.mode == "audio":
                self._process_speaker_loopback()
            else:
                self._process_microphone()
        except Exception as e:
            self.emitter.log_received.emit(f"[오디오 스트림 치명적 에러]: {str(e)}")
            self.emitter.engine_stopped.emit()

    def _transcribe_chunk(self, audio_data: np.ndarray):
        try:
            segments, _ = self.model.transcribe(
                audio_data, 
                language="ko", 
                vad_filter=True, 
                beam_size=1
            )
            for s in segments:
                text = s.text.strip()
                if text:
                    self.emitter.subtitle_received.emit(text)
        except Exception as e:
            self.emitter.log_received.emit(f"[추론 에러] {str(e)}")

    def _process_microphone(self):
        if pyaudio is None:
            self.emitter.log_received.emit("[에러] PyAudio 모듈을 불러올 수 없습니다.")
            return

        p = pyaudio.PyAudio()
        CHUNK = 1024
        stream = None
        try:
            self.emitter.log_received.emit("[오디오] 마이크 스트림 오픈 중...")
            stream = p.open(
                format=pyaudio.paInt16, 
                channels=1, 
                rate=self.SAMPLE_RATE, 
                input=True, 
                frames_per_buffer=CHUNK
            )
            self.emitter.log_received.emit("[오디오] 마이크 캡처 정상 시작!")

            buffer = []
            silence_frames = 0

            while self.is_running:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                rms = np.sqrt(np.mean(audio_np**2))

                if rms > 0.01:
                    buffer.append(audio_np)
                    silence_frames = 0
                elif buffer:
                    silence_frames += 1
                    if silence_frames > 12:
                        full_audio = np.concatenate(buffer)
                        if len(full_audio) >= self.SAMPLE_RATE * 0.3:
                            self._transcribe_chunk(full_audio)
                        buffer = []
                        silence_frames = 0

        except Exception as e:
            self.emitter.log_received.emit(f"[마이크 캡처 예외 발생]: {str(e)}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass
            try:
                p.terminate()
            except:
                pass
            self.emitter.engine_stopped.emit()

    def _process_speaker_loopback(self):
        if sc is None:
            self.emitter.log_received.emit("[에러] 'soundcard' 모듈이 없습니다.")
            self.emitter.engine_stopped.emit()
            return

        try:
            default_spk = sc.default_speaker()
            loopback_dev = sc.get_microphone(default_spk.name, include_loopback=True)
            
            if loopback_dev is None:
                self.emitter.log_received.emit("[에러] 시스템 루프백 장치를 찾을 수 없습니다.")
                self.emitter.engine_stopped.emit()
                return

            self.emitter.log_received.emit(f"[오디오] 루프백 시작: {loopback_dev.name}")
            NATIVE_SR = 48000
            FRAMES = 1024
            buffer = []
            silence_frames = 0

            with loopback_dev.recorder(samplerate=NATIVE_SR, channels=2) as recorder:
                while self.is_running:
                    data_float = recorder.record(numframes=FRAMES)
                    if len(data_float) == 0:
                        continue

                    mono = np.mean(data_float, axis=1) if data_float.ndim > 1 else data_float
                    resampled = signal.resample_poly(mono, self.SAMPLE_RATE, NATIVE_SR).astype(np.float32)
                    rms = np.sqrt(np.mean(resampled**2))

                    if rms > 0.008:
                        buffer.append(resampled)
                        silence_frames = 0
                    elif buffer:
                        silence_frames += 1
                        if silence_frames > 12:
                            full_audio = np.concatenate(buffer)
                            if len(full_audio) >= self.SAMPLE_RATE * 0.3:
                                self._transcribe_chunk(full_audio)
                            buffer = []
                            silence_frames = 0

        except Exception as e:
            self.emitter.log_received.emit(f"[루프백 예외 발생]: {str(e)}")
            self.emitter.engine_stopped.emit()

    def stop(self):
        self.is_running = False
        self.emitter.engine_stopped.emit()