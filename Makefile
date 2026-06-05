PYTHON ?= python3

.PHONY: test lint build

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m compileall -q src tests

build:
	$(PYTHON) scripts/build_package.py
