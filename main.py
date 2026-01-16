from scipy.signal import correlate, find_peaks
import numpy as np
import pyaudio
import psutil
import json
import subprocess
import os
import time
import threading
from collections import deque
import sys
import winreg
from time import sleep
from check_process import check_process
from config import DOTA_EXECUTABLE, STEAM_PATH, DOTA_PROCESS_NAME, SAMPLE_RATE, CHUNK_SIZE, THRESHOLD, ETALON_FILE
import config


class MicrophonePCMCapture:
    def __init__(self, sample_rate=44100, chunk_size=1024, channels=1):
        """
        Инициализация захвата аудио с микрофона в PCM
        
        sample_rate: частота дискретизации (44100, 48000 Hz)
        chunk_size: размер буфера в сэмплах
        channels: количество каналов (1 - моно, 2 - стерео)
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.is_recording = False
        self.audio_queue = deque(maxlen=100)  # буфер последних 100 чанков
        
        self.p = pyaudio.PyAudio()
        
        # Используем int16 для PCM (16-бит подписанное целое число)
        self.format = pyaudio.paInt16
        
    def start_recording(self):
        """Запустить запись с микрофона"""
        if self.is_recording:
            print("[ERROR] Запись уже идёт!")
            return
        
        self.is_recording = True
        self.stream = self.p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            input_device_index=None  # Используем устройство по умолчанию
        )
        
        print("[OK] Запись начата. Слушаем микрофон...")
        
        # Запустить в отдельном потоке
        self.thread = threading.Thread(target=self._record_thread, daemon=True)
        self.thread.start()
    
    def _record_thread(self):
        """Поток для чтения данных с микрофона"""
        while self.is_recording:
            try:
                # Читаем чанк PCM данных
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                
                # Преобразуем в numpy массив
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                
                # Добавляем в очередь
                self.audio_queue.append(audio_chunk)
                
            except Exception as e:
                print(f"[ERROR] Ошибка при чтении: {e}")
                break
    
    def stop_recording(self):
        """Остановить запись"""
        self.is_recording = False
        if hasattr(self, 'thread'):
            self.thread.join()
        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()
        print("[OK] Запись остановлена")
    
    def get_pcm_data(self):
        """Получить все накопленные PCM данные"""
        if not self.audio_queue:
            return np.array([], dtype=np.int16)
        
        return np.concatenate(list(self.audio_queue))
    
    def cleanup(self):
        """Очистка ресурсов"""
        self.p.terminate()


class FastSoundDetector:
    def __init__(self, etalon, rate=44100, chunk_size=2048, threshold=0.8):
        self.etalon = np.array(etalon, dtype=np.float32)
        self.rate = rate
        self.chunk_size = chunk_size
        self.threshold = threshold
        self.buffer = np.array([])
        
        # Создаём объект захвата звука
        self.mic_capture = MicrophonePCMCapture(sample_rate=rate, chunk_size=chunk_size, channels=1)
    
    def process_audio_chunk(self, chunk):
        """Обработать чанк аудио из микрофона"""
        # Преобразуем int16 в float32 для обработки
        chunk_float = chunk.astype(np.float32) / 32768.0
        self.buffer = np.append(self.buffer, chunk_float)

        # Держим буфер 2 секунды
        max_buffer = self.rate * 2
        if len(self.buffer) > max_buffer:
            self.buffer = self.buffer[-max_buffer:]
        
        if len(self.buffer) >= len(self.etalon):
            self.fast_check()
    
    def fast_check(self):
        """Быстрая проверка на совпадение"""
        # Cross-correlation 
        correlation = correlate(self.buffer, self.etalon, mode='valid')
        # Нормализация 
        norm = np.sqrt(np.sum(self.etalon**2))
        correlation = correlation / (norm + 1e-10)
        # Найти пики 
        max_corr = np.max(correlation)
        if max_corr > self.threshold:
            print(f"НАЙДЕНО! Корреляция: {max_corr:.3f}")
            # Чек процесса и запуск дотки если не запущена
            if not self.is_process_running(DOTA_PROCESS_NAME):
                self.launch_dota()

            # Очищаем буфер 
            self.buffer = np.array([])
    
    def is_process_running(self, process_name):
        """Проверяет, запущен ли процесс"""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] == process_name:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
    
    def launch_dota(self):
        """Запускает Dota 2"""
        try:
            # Попытка запустить через конфиг
            if os.path.exists(DOTA_EXECUTABLE):
                subprocess.Popen(DOTA_EXECUTABLE)
                print("Dota 2 запущена!")
                time.sleep(2)
                sys.exit(0)
            
            # Если нет - пробуем через реестр
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    steam_path_reg, _ = winreg.QueryValueEx(key, "SteamPath")
                    dota_exe = os.path.join(steam_path_reg, "steamapps", "common", "dota 2 beta", "game", "bin", "win64", "dota2.exe")
                    if os.path.exists(dota_exe):
                        subprocess.Popen(dota_exe)
                        print("Dota 2 запущена!")
                        time.sleep(2)
                        sys.exit(0)
            except:
                pass
            
            print("Dota 2 не найдена. Укажите правильный путь в config.py")
        except Exception as e:
            print(f"Ошибка запуска Dota 2: {e}")
    
    def main(self):
        """Запустить детектор"""
        try:
            print("\n" + "="*60)
            print("Детектор звука Dota 2 (PyAudio)")
            print("="*60)
            print(f"Частота дискретизации: {self.rate} Hz")
            print(f"Размер чанка: {self.chunk_size} сэмплов")
            print(f"Порог корреляции: {self.threshold}")
            print("="*60 + "\n")
            
            # Проверяем, не запущена ли Dota 2 уже
            if self.is_process_running("Dota 2.exe"):
                print("[INFO] Dota 2 уже запущена! Завершаю детектор...")
                sys.exit(0)
            
            # Запускаем захват
            self.mic_capture.start_recording()
            
            print("Слушаем микрофон...")
            print("Нажмите Ctrl+C для остановки\n")
            
            # Основной цикл - обработка чанков
            try:
                while self.mic_capture.is_recording:
                    if self.mic_capture.audio_queue:
                        chunk = self.mic_capture.audio_queue.popleft()
                        self.process_audio_chunk(chunk)
                    else:
                        time.sleep(0.01)
            except KeyboardInterrupt:
                print("\n\nОстановка детектора...")
            
            # Останавливаем захват
            self.mic_capture.stop_recording()
            self.mic_capture.cleanup()
            print("Детектор остановлен.")
            
        except Exception as e:
            print(f"Ошибка в main: {e}")
            self.mic_capture.cleanup()

# Загрузка эталона из JSON и запуск
if __name__ == "__main__":
    try:
        with open(ETALON_FILE, 'r') as f:
            etalon_data = json.load(f)
        
        detector = FastSoundDetector(etalon_data, rate=SAMPLE_RATE, chunk_size=CHUNK_SIZE, threshold=THRESHOLD)
        detector.main()
    except FileNotFoundError:
        print(f"Файл {ETALON_FILE} не найден!")
    except Exception as e:
        print(f"Ошибка: {e}")
    