PYTHON ?= python
HOST ?= 0.0.0.0
PORT ?= 5000

.PHONY: help run dev test check routes printer-help
.DEFAULT_GOAL := help

help:
	@echo "run          Start Flask"
	@echo "dev          Start Flask with reload and debug"
	@echo "test         Run tests without a physical printer"
	@echo "check        Check Python syntax"
	@echo "routes       List HTTP routes"
	@echo "printer-help Show bundled printer CLI help"
	@echo "Override interpreter: make test PYTHON=python3.11"

run:
	$(PYTHON) -m flask --app app run --host $(HOST) --port $(PORT)

dev:
	$(PYTHON) -m flask --app app run --debug --host $(HOST) --port $(PORT)

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m compileall -q app.py warehouse tests

routes:
	$(PYTHON) -m flask --app app routes

printer-help:
	$(PYTHON) -m warehouse.vendor.niimprintx.cli --help
