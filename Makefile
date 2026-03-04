# git-repo Makefile — task runner for development workflow
# All targets dispatch to standard tools; no business logic in recipes.

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

.DEFAULT_GOAL := help

.PHONY: lint format format-check check test test-unit test-functional validate clean help

help: ## Show this help message
	@echo "Available make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint: ## Run all linters (ruff, markdownlint, yamllint)
	@echo "lint: placeholder — will be implemented in E0-F1-S1-T2"

format: ## Auto-fix formatting issues (ruff format)
	@echo "format: placeholder — will be implemented in E0-F1-S1-T2"

format-check: ## Verify formatting without modifying files (CI-safe)
	@echo "format-check: placeholder — will be implemented in E0-F1-S1-T2"

check: lint format-check ## Run all checks: lint + format verification (read-only, CI-safe)

test: ## Run pytest with coverage
	@echo "test: placeholder — will be implemented in E0-F1-S1-T3"

test-unit: ## Run unit tests only (-m unit)
	@echo "test-unit: placeholder — will be implemented in E0-F1-S1-T3"

test-functional: ## Run functional tests only (-m functional)
	@echo "test-functional: placeholder — will be implemented in E0-F1-S1-T3"

validate: check test ## Full CI equivalent: check + test

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -f .coverage
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .tox
	rm -rf *.egg-info
	@echo "clean: all build artifacts removed"
