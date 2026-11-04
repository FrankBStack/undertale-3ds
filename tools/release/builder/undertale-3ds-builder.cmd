@echo off
rem Starts the builder. With no arguments it opens the window. With arguments (--cli, --dry-run, --help) it runs in
rem this console, so its output shows here and the exit code is the builder's. A release zip carries python.org's
rem embeddable Python in runtime\; a source checkout uses the installed Python launcher.
setlocal
rem An ERRORLEVEL variable from the caller would hide the builder's exit code; clear it for this script.
set "ERRORLEVEL="
set "HERE=%~dp0"
if not "%~1"=="" goto console
if exist "%HERE%runtime\pythonw.exe" (
    start "" "%HERE%runtime\pythonw.exe" "%HERE%builder.py" --game undertale
) else (
    start "" pyw -3 "%HERE%builder.py" --game undertale
)
exit /b
:console
set PYTHON=py -3
if exist "%HERE%runtime\python.exe" set PYTHON="%HERE%runtime\python.exe"
%PYTHON% "%HERE%builder.py" --game undertale %*
exit /b %errorlevel%
