@echo off
chcp 65001 >nul
title Indexacao de embeddings - Banco de Personagens CriaLab UEG
cd /d "%~dp0"
echo ============================================================
echo  INDEXACAO DE EMBEDDINGS (prepara a busca inteligente)
echo.
echo  - Primeira vez: baixa o modelo (~2,2 GB) e indexa ~13 mil
echo    documentos. Leva de 1,5 a 2 horas no total.
echo  - Pode fechar esta janela a qualquer momento: o progresso
echo    fica salvo e continua de onde parou na proxima vez.
echo  - Deixe o computador ligado (pode bloquear a tela, mas
echo    nao deixe hibernar/desligar).
echo ============================================================
echo.
.venv\Scripts\python.exe -m src.busca.indexar
echo.
echo ------------------------------------------------------------
echo  Concluido! Pode fechar esta janela.
echo ------------------------------------------------------------
pause
