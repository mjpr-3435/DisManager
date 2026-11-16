@echo off
setlocal
for /d /r "%~dp0dismanager" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)
echo Done.
