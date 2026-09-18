@echo off
rem One token-safe translator attempt (v3: batched lines + circuit breakers).
cd /d "C:\Users\KEOVOIN-DESKTOP\Sastra-HowToLiveBetter"
set I18N_GAP_POLL=8
set I18N_GAP_MM=2
set I18N_GAP_GTX=1
set I18N_SNOOZES=10
"C:\Users\KEOVOIN-DESKTOP\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" tools\i18n_all2.py --langs=en,km