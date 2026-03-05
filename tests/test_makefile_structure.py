"""Tests for Makefile structure and targets.

Validates that the git-repo Makefile follows the required conventions:
- Bash shell with strict error handling
- All required targets declared as .PHONY
- help target prints target descriptions
- Correct dependency chain between targets
"""

import os
import re
import subprocess

import pytest

REPO_ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
MAKEFILE_PATH = os.path.join(REPO_ROOT, "Makefile")

REQUIRED_PHONY_TARGETS = frozenset(
    [
        "lint",
        "format",
        "check",
        "test",
        "test-unit",
        "test-functional",
        "validate",
        "clean",
        "help",
    ]
)


@pytest.fixture
def makefile_content():
    """Read the Makefile content."""
    with open(MAKEFILE_PATH) as f:
        return f.read()


@pytest.mark.unit
def test_makefile_syntax_valid():
    """Validate that the Makefile is parsable by GNU Make.

    Given: The Makefile exists at repo root
    When: GNU Make parses it with --dry-run on the help target
    Then: It exits with code 0 (no syntax errors)
    Spec: Plan: Makefile
    """
    result = subprocess.run(
        ["make", "-n", "-f", MAKEFILE_PATH, "help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Makefile syntax error: {result.stderr}"


@pytest.mark.unit
def test_makefile_has_bash_shell(makefile_content):
    """Validate that the Makefile uses bash with strict error handling.

    Given: The Makefile exists
    When: We inspect its SHELL and .SHELLFLAGS declarations
    Then: SHELL is /bin/bash and .SHELLFLAGS includes -euo pipefail -c
    Spec: Plan: Per-Repo Tooling
    """
    assert "SHELL := /bin/bash" in makefile_content
    assert ".SHELLFLAGS := -euo pipefail -c" in makefile_content


@pytest.mark.unit
def test_makefile_has_all_phony_targets(makefile_content):
    """Validate that all required targets are declared as .PHONY.

    Given: The Makefile exists
    When: We extract all .PHONY declarations
    Then: All required targets are declared
    Spec: Plan: Makefile
    """
    phony_targets = set()
    for match in re.finditer(r"\.PHONY:\s*(.+)", makefile_content):
        targets = match.group(1).split()
        phony_targets.update(targets)
    missing = REQUIRED_PHONY_TARGETS - phony_targets
    assert not missing, f"Missing .PHONY declarations: {missing}"


@pytest.mark.unit
def test_make_help_prints_output():
    """Validate that make help prints target descriptions.

    Given: The Makefile exists with a help target
    When: make help is run
    Then: Output contains target names and descriptions
    Spec: Plan: Makefile
    """
    result = subprocess.run(
        ["make", "-C", REPO_ROOT, "help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make help failed: {result.stderr}"
    output = result.stdout
    for target in REQUIRED_PHONY_TARGETS:
        assert target in output, f"Target '{target}' not in help output"


@pytest.mark.unit
def test_validate_depends_on_check_and_test(makefile_content):
    """Validate that the validate target depends on check and test.

    Given: The Makefile exists
    When: We inspect the validate target
    Then: It lists check and test as prerequisites
    Spec: Plan: Makefile
    """
    match = re.search(r"^validate:\s*(.+)", makefile_content, re.MULTILINE)
    assert match, "validate target not found"
    deps = match.group(1).split("##")[0].split()
    assert "check" in deps, "validate must depend on check"
    assert "test" in deps, "validate must depend on test"


@pytest.mark.unit
def test_check_depends_on_lint(makefile_content):
    """Validate that the check target depends on lint.

    Given: The Makefile exists
    When: We inspect the check target
    Then: It lists lint as a prerequisite
    Spec: Plan: Makefile
    """
    match = re.search(r"^check:\s*(.+)", makefile_content, re.MULTILINE)
    assert match, "check target not found"
    deps = match.group(1).split("##")[0].split()
    assert "lint" in deps, "check must depend on lint"


@pytest.mark.unit
def test_clean_removes_caches():
    """Validate that make clean removes expected cache directories.

    Given: Cache directories exist
    When: make clean --dry-run is inspected
    Then: Commands to remove __pycache__, .pytest_cache, .ruff_cache, htmlcov, .coverage are present
    Spec: Plan: Makefile
    """
    result = subprocess.run(
        ["make", "-n", "-C", REPO_ROOT, "clean"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"make clean --dry-run failed: {result.stderr}"
    dry_output = result.stdout
    for cache in [
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "htmlcov",
        ".coverage",
    ]:
        assert cache in dry_output, f"clean should remove {cache}"


@pytest.mark.unit
def test_each_target_has_help_comment(makefile_content):
    """Validate that each Makefile target has a help comment.

    Given: The Makefile exists
    When: We inspect each target definition
    Then: Each required target has a ## comment describing its purpose
    Spec: Plan: Makefile (AC-DOC-1)
    """
    for target in REQUIRED_PHONY_TARGETS:
        pattern = rf"^{re.escape(target)}:.*##\s+\S+"
        assert re.search(
            pattern, makefile_content, re.MULTILINE
        ), f"Target '{target}' missing ## help comment"


@pytest.mark.unit
def test_placeholder_targets_fail_fast():
    """Validate that unconfigured placeholder targets exit non-zero.

    Given: Placeholder targets are not yet implemented
    When: A placeholder target is invoked
    Then: It exits with non-zero code and prints an error to stderr
    Spec: Plan: Fail-fast principle
    """
    placeholder_targets = ["lint", "format", "format-check", "test", "test-unit", "test-functional"]
    for target in placeholder_targets:
        result = subprocess.run(
            ["make", "-C", REPO_ROOT, target],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, f"Placeholder target '{target}' should exit non-zero"
        assert "ERROR" in result.stderr, f"Placeholder target '{target}' should print error to stderr"


@pytest.mark.unit
def test_clean_target_no_error_suppression(makefile_content):
    """Validate that the clean target does not suppress errors.

    Given: The Makefile has a clean target
    When: We inspect its recipe
    Then: No || true or 2>/dev/null patterns are present
    Spec: Plan: Fail-fast principle
    """
    in_clean = False
    for line in makefile_content.splitlines():
        if line.startswith("clean:"):
            in_clean = True
            continue
        if in_clean:
            if line and not line[0].isspace() and not line.startswith("\t"):
                break
            assert "|| true" not in line, "clean target must not use || true"
            assert "2>/dev/null" not in line, "clean target must not suppress stderr"
