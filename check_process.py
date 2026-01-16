import psutil
import time
import sys
process_name = r"C:\steam\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe"
check_interval = 1
def is_process_running(name):
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == name:
            return True
    return False
def check_process():
    while True:
        if is_process_running(process_name):
            sys.exit(0)
        
        time.sleep(check_interval)