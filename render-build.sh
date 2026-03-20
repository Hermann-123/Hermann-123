#!/usr/bin/env bash
# Installation de Python et Playwright
pip install -r requirements.txt
playwright install chromium
playwright install-deps
