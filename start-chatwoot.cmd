@echo off
rem Allows starting Chatwoot with one command:  start-chatwoot
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-chatwoot.ps1" %*
