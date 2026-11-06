@echo off
setlocal
set "KORDOC_CLI=%~dp0..\node_modules\kordoc\dist\cli.js"
if not exist "%KORDOC_CLI%" (
  echo kordoc CLI not found: "%KORDOC_CLI%" 1>&2
  exit /b 1
)
node "%KORDOC_CLI%" %*
