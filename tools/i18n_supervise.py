# Supervisor: restart the resumable translator until the whole book is done.
import subprocess, sys, time, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
for i in range(400):
    r = subprocess.run([sys.executable, "tools/i18n_translate.py", "--langs=en,km"], capture_output=True, text=True)
    done = r.returncode == 0
    open("tools/i18n_supervisor.log", "a", encoding="utf-8").write(f"[{time.strftime('%H:%M:%S')}] run {i} rc={r.returncode}\n" + (r.stdout or "")[-600:] + (r.stderr or "")[-600:] + "\n")
    if done:
        print("ALL DONE", flush=True)
        break
    time.sleep(45)
