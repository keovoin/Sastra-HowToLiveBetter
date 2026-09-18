@echo off
rem One translator attempt: tries files, exits if Google still blocks.
cd /d "C:\Users\KEOVOIN-DESKTOP\Sastra-HowToLiveBetter"
set I18N_SNOOZES=2
set I18N_PACE=4.5
"C:\Users\KEOVOIN-DESKTOP\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" tools\i18n_all.py --langs=en,km
