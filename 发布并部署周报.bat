@echo off
setlocal
set "NEWSLETTER_PYTHON=D:\conda\env3.10\python.exe"
if exist "%NEWSLETTER_PYTHON%" (
  "%NEWSLETTER_PYTHON%" "%~dp0publish_weekly.py" %*
) else (
  py -3 "%~dp0publish_weekly.py" %*
)
