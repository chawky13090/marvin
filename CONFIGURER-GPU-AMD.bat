@echo off
chcp 65001 >nul
title Marvin - Activer le GPU AMD pour Ollama
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0configurer-gpu-amd.ps1"
