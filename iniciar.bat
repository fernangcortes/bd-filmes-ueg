@echo off
setlocal EnableDelayedExpansion
title BD Filmes UEG
cd /d "%~dp0"

REM --- Docker (PATH ou instalacao padrao do Docker Desktop) ---
set "DOCKER=docker"
where docker >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\Docker\Docker\resources\bin\docker.exe" (
        set "DOCKER=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    ) else (
        echo [ERRO] Docker Desktop nao encontrado. Execute instalar.bat primeiro.
        pause
        exit /b 1
    )
)

REM --- Garante o banco no ar (com espera se o Docker ainda estiver iniciando) ---
set /a TENTATIVA=0
:SOBE_BANCO
%DOCKER% compose up -d >nul 2>nul
if errorlevel 1 (
    set /a TENTATIVA+=1
    if !TENTATIVA! GEQ 6 (
        echo [ERRO] Banco indisponivel. Abra o Docker Desktop e tente novamente.
        pause
        exit /b 1
    )
    echo Aguardando o Docker Desktop iniciar... tentativa !TENTATIVA!/6
    timeout /t 10 /nobreak >nul
    goto SOBE_BANCO
)

REM --- Abre o aplicativo ---
if not exist .venv (
    echo [ERRO] Ambiente nao instalado. Execute instalar.bat primeiro.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo Abrindo o Banco de Personagens... (para encerrar, feche esta janela)
streamlit run src/app/main.py --server.headless false
pause
