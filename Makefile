SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

.PHONY: help lint format format-check check test test-unit test-functional validate clean

help: ## Show available targets and their descriptions
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint: ## Run all linters (ruff, markdownlint, yamllint)
	@echo 'ERROR: lint target not yet configured (see E0-F1-S1-T2)' >&2 && exit 1

format: ## Auto-fix formatting issues (ruff format)
	@echo 'ERROR: format target not yet configured (see E0-F1-S1-T2)' >&2 && exit 1

format-check: ## Verify formatting without modifying files (CI-safe)
	@echo 'ERROR: format-check target not yet configured (see E0-F1-S1-T2)' >&2 && exit 1

check: lint format-check ## Run all checks: lint + format verification (read-only, CI-safe)

test: ## Run full test suite with coverage
	@echo 'ERROR: test target not yet configured (see E0-F1-S1-T3)' >&2 && exit 1

test-unit: ## Run unit tests only (pytest -m unit)
	@echo 'ERROR: test-unit target not yet configured (see E0-F1-S1-T3)' >&2 && exit 1

test-functional: ## Run functional tests only (pytest -m functional)
	@echo 'ERROR: test-functional target not yet configured (see E0-F1-S1-T3)' >&2 && exit 1

validate: check test ## Full CI equivalent: check + test

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -f .coverage
	rm -rf .tox
	rm -rf *.egg-info
	find . -type f -name '*.pyc' -delete
