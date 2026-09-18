$cmd = '"C:\Users\KEOVOIN-DESKTOP\Sastra-HowToLiveBetter\tools\i18n_attempt.cmd"'
schtasks /create /tn SastraI18nTranslate /tr $cmd /sc minute /mo 15 /f
schtasks /query /tn SastraI18nTranslate /fo LIST
