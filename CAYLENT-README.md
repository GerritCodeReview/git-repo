# Caylent Repo Tool

This is Caylent's fork of the Android repo tool with custom enhancements.

## Table of Contents

- [Installation](#installation)
  - [Quick Start](#quick-start-recommended)
  - [Production (Pinned Version)](#production-pinned-version)
  - [Override Repository URL or Version](#override-repository-url-or-version)
- [Usage](#usage)
  - [Important: GPG Verification](#important-gpg-verification)
- [New Features](#new-features)
  - [Environment Variable Substitution (envsubst)](#environment-variable-substitution-envsubst)
- [Development](#development)
  - [Setup](#setup)
  - [Running Tests](#running-tests)
  - [Creating a Release](#creating-a-release)
- [Upstream Sync](#upstream-sync)

## Installation

### Quick Start (Recommended)

```bash
# Install repo from latest tag (automatically fetches latest version)
pip install git+https://github.com/caylent-solutions/git-repo@$(curl -s https://api.github.com/repos/caylent-solutions/git-repo/tags | grep -o '"name": "caylent-[^"]*' | head -1 | cut -d'"' -f4)

# Initialize repo - automatically uses latest caylent-* tag
repo init -u <YOUR_MANIFEST_URL> --no-repo-verify
```

During `repo init`, it will automatically fetch and use the latest `caylent-*` tag from GitHub.

**To uninstall:**
```bash
pip uninstall -y repo
```

### Production (Pinned Version)

For production environments, pin to a specific tag to ensure consistency:

```bash
# Install specific tag
pip install git+https://github.com/caylent-solutions/git-repo@caylent-0.1.2

# Initialize with the same pinned tag
repo init -u <YOUR_MANIFEST_URL> --repo-rev=caylent-0.1.2 --no-repo-verify
```

Replace `caylent-0.1.2` with your desired version.

### Override Repository URL or Version

To use a specific version or branch instead of the latest tag:

```bash
# Install specific version
pip install git+https://github.com/caylent-solutions/git-repo@<ref>

# Initialize with specific version
repo init -u <YOUR_MANIFEST_URL> --repo-rev=<ref> --no-repo-verify
```

To use a different fork entirely:

```bash
# Initialize with custom repo URL and version
repo init -u <YOUR_MANIFEST_URL> \
  --repo-url=<CUSTOM_REPO_URL> \
  --repo-rev=<ref> \
  --no-repo-verify
```

Replace `<ref>` with a tag (e.g., `caylent-0.1.2`), branch (e.g., `main`), or commit hash.

## Usage

### Important: GPG Verification

Currently, Caylent tags are not GPG-signed. You **must** use the `--no-repo-verify` flag when running `repo init`:

```sh
repo init -u <manifest-url> --no-repo-verify
```

**Note:** GPG signing support will be added in a future release. Track progress in the `.amazonq/prompts/add-gpg-signing.md` file.

### Example

```sh
# Initialize a repo workspace
repo init -u https://github.com/your-org/manifest.git --no-repo-verify

# Sync all projects
repo sync
```

## New Features

### Environment Variable Substitution (envsubst)

Replace environment variable placeholders in manifest XML files:

```xml
<!-- manifest.xml -->
<manifest>
  <remote name="origin" 
          fetch="${GITBASE}" 
          revision="${GITREV}"/>
  <project name="my-project" 
           path="projects/my-project" 
           remote="origin"/>
</manifest>
```

```bash
# Set environment variables
export GITBASE=https://github.com/myorg
export GITREV=main

# Run envsubst to replace variables
repo envsubst
```

**Result:**
```xml
<manifest>
  <remote name="origin" 
          fetch="https://github.com/myorg" 
          revision="main"/>
  <project name="my-project" 
           path="projects/my-project" 
           remote="origin"/>
</manifest>
```

The command replaces all `${VARIABLE}` placeholders in:
- Attribute values
- Text content
- Any XML element in manifest files under `.repo/manifests/`

## Caylent Enhancements

- Automatic detection of latest `caylent-*` tag during initialization
- Improved trace file handling for non-writable directories
- Environment variable substitution in manifest files
- Custom bug tracking: https://github.com/caylent-solutions/git-repo/issues

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/caylent-solutions/git-repo
cd git-repo

# Install development dependencies
pip install -r requirements-dev.txt
```

### Makefile Targets

All development tasks are available via `make`:

```bash
make help            # Show available targets
make lint            # Run all linters
make format          # Auto-fix formatting issues
make check           # Lint + format verification (read-only, CI-safe)
make test            # Run full test suite with coverage
make test-unit       # Run unit tests only
make test-functional # Run functional tests only
make validate        # Full CI equivalent: check + test
make clean           # Remove build artifacts and caches
```

### Running Tests

```bash
# Run full CI validation
make validate

# Run specific tests
pytest tests/test_subcmds_envsubst.py
```

### Creating a Release

1. Update version and create a semver tag:
   ```bash
   git tag -a caylent-0.1.3 -m "Release caylent-0.1.3"
   git push origin caylent-0.1.3
   ```

2. Users can then install using the tag as shown in the installation section above.

## Upstream Sync

To sync with upstream Google repo:

```bash
git remote add upstream https://gerrit.googlesource.com/git-repo
git fetch upstream
git merge upstream/main
```

## Releases

Latest release: `caylent-0.1.2`

View all releases: https://github.com/caylent-solutions/git-repo/tags
