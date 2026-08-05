@echo off
setlocal EnableDelayedExpansion
title BD Filmes UEG - Instalacao
cd /d "%~dp0"

echo ============================================================
echo   Banco de Personagens CriaLab^|UEG - Instalacao
echo ============================================================
echo.

REM --- 1. Docker (PATH ou instalacao padrao do Docker Desktop) ---
set "DOCKER=docker"
where docker >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\Docker\Docker\resources\bin\docker.exe" (
        set "DOCKER=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    ) else (
        echo [ERRO] Docker Desktop nao encontrado.
        echo Instale gratis em: https://www.docker.com/products/docker-desktop/
        start https://www.docker.com/products/docker-desktop/
        pause
        exit /b 1
    )
)
echo [OK] Docker encontrado.

REM --- 2. Python 3.12+ ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    echo Instale em: https://www.python.org/downloads/
    echo IMPORTANTE: marque a caixa "Add python.exe to PATH" na instalacao.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python encontrado.

REM --- 3. Ambiente virtual e dependencias ---
if not exist .venv (
    echo Criando ambiente virtual...
    python -m venv .venv
    if errorlevel 1 ( echo [ERRO] Falha ao criar ambiente virtual. & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
echo Instalando dependencias (na primeira vez pode demorar alguns minutos)...
python -m pip install --upgrade pip >nul
pip install -e .
if errorlevel 1 ( echo [ERRO] Falha ao instalar dependencias. & pause & exit /b 1 )
echo [OK] Dependencias instaladas.

REM --- 4. Banco de dados (com espera caso o Docker Desktop ainda esteja iniciando) ---
echo Subindo o banco de dados (PostgreSQL + pgvector)...
set /a TENTATIVA=0
:SOBE_BANCO
%DOCKER% compose up -d >nul 2>nul
if errorlevel 1 (
    set /a TENTATIVA+=1
    if !TENTATIVA! GEQ 6 (
        echo [ERRO] Nao foi possivel subir o banco. Verifique se o Docker Desktop esta aberto.
        pause
        exit /b 1
    )
    echo Aguardando o Docker Desktop iniciar... tentativa !TENTATIVA!/6
    timeout /t 10 /nobreak >nul
    goto SOBE_BANCO
)
echo [OK] Banco de dados no ar.

echo.
echo ============================================================
echo   Instalacao concluida! Para usar, execute: iniciar.bat
echo ============================================================
pause
