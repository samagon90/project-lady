SHELL := /bin/bash
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: install migrate run test lint voice models

install:            ## установить зависимости (нужен Python 3.12+)
	python3 -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

migrate:            ## применить миграции базы данных
	$(PYTHON) -m alembic upgrade head

run:                ## запустить бота
	$(PYTHON) -m src.main

test:               ## прогнать тесты
	$(PYTHON) -m pytest

lint:               ## линтер ruff + проверка типов mypy
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m mypy src

voice:              ## скачать русский голос Piper (бесплатно, HuggingFace)
	mkdir -p models/piper
	curl -L -o models/piper/ru_RU-irina-medium.onnx \
	  "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
	curl -L -o models/piper/ru_RU-irina-medium.onnx.json \
	  "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json"

models:             ## скачать LLM и embedding-модель в Ollama
	ollama pull $(or $(LLM_MODEL),qwen2.5:7b)
	ollama pull $(or $(EMBEDDING_MODEL),nomic-embed-text)
