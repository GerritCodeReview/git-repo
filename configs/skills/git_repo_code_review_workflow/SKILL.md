---
name: git-repo-code-review-workflow
description: Provides guidance and best practices on Gerrit submission labeling, CI builder execution, Python code formatting/linting, commit metadata standardization, and testing strategy in git-repo.
---

# Code Review Workflow Engineering Guide

## Executive Summary

Welcome to the authoritative engineering guide for the Code Review Workflow.
This living repository exists to capture critical tribal knowledge, prevent the
recurrence of historical failure modes, and enforce strict architectural and
procedural boundaries across our integration pipeline. By standardizing these
protocols, we ensure high development velocity while maintaining rock-solid
codebase stability and traceability.

This guide covers the complete lifecycle of a change list (CL) from local
development to automated submission. It defines the strict Gerrit labeling
mechanisms required to trigger the Commit-Queue, mandates comprehensive CI
builder environment checks, and enforces centralized Python static analysis.
Furthermore, it outlines uncompromising standards for atomic commit metadata and
pragmatic testing state isolation to guarantee that every integration is fully
bisectable and verifiable.

For incoming engineers, adherence to these mandates eliminates the friction of
stalled pipelines, unreviewable monolithic changes, and silent CI regressions.
Treat this guide as your primary roadmap for navigating the repository's strict
submission requirements, enabling seamless transitions from peer approval to
successfully integrated code.

## Summary

| Chapter Theme / Title            | Scope & Objective                         |
| :------------------------------- | :---------------------------------------- |
| **Gerrit Submission and Labeling | Dictates strict access controls, review   |
: Workflow**                       : enforcement protocols, and Gerrit         :
:                                  : labeling mechanisms required to advance   :
:                                  : changes through the CI pipeline, ensuring :
:                                  : seamless transitions to automated         :
:                                  : integration via the Commit-Queue.         :
| **CI Builder Environment and     | Defines guidelines for ensuring build     |
: Execution Integrity**            : script resilience against missing         :
:                                  : dependencies and managing process         :
:                                  : execution contexts within LUCI and local  :
:                                  : testing environments to prevent silent    :
:                                  : builder failures.                         :
| **Python Code Formatting and     | Governs the automated enforcement of      |
: Linting**                        : Python style guidelines, mandating strict :
:                                  : PEP-8 compliance, import sorting, and     :
:                                  : consistent string quoting to ensure       :
:                                  : codebase uniformity and prevent CI        :
:                                  : regressions.                              :
| **Commit Metadata and History    | Establishes the structural composition    |
: Standardization**                : and metadata formatting of change lists   :
:                                  : (CLs) to ensure precise issue tracker     :
:                                  : integration, reliable CI/CD parsing, and  :
:                                  : an atomic, bisectable repository history. :
| **Testing Strategy and State     | Outlines test implementation boundaries,  |
: Isolation**                      : emphasizing pragmatic mocking limits to   :
:                                  : prevent false positives and detailing     :
:                                  : acceptable workflows for deferred test    :
:                                  : coverage while maintaining verification   :
:                                  : integrity.                                :

--------------------------------------------------------------------------------
--------------------------------------------------------------------------------

## Chapter: Gerrit Submission and Labeling Workflow

**Context:** This domain dictates the strict access controls, review enforcement
protocols, and specific Gerrit labeling mechanisms required to advance changes
through the CI pipeline. Adherence ensures seamless transitions from peer
approval to automated integration via the Commit-Queue.

### Summary

| Rule ID   | Principle / Constraint          | Priority | Primary Symptom /  |
:           :                                 :          : Trap               :
| :-------- | :------------------------------ | :------- | :----------------- |
| **T1-01** | Explicit Labeling for Gerrit    | High     | Leaving a change   |
:           : Automated Submission            :          : idle after         :
:           :                                 :          : addressing         :
:           :                                 :          : comments or        :
:           :                                 :          : receiving a        :
:           :                                 :          : reviewer's LGTM,   :
:           :                                 :          : expecting the      :
:           :                                 :          : reviewer to merge  :
:           :                                 :          : it.                :
| **T1-02** | Automated Submission via        | Medium   | Requesting a       |
:           : Commit-Queue (CQ)               :          : manual push or     :
:           :                                 :          : direct submit from :
:           :                                 :          : repository         :
:           :                                 :          : maintainers after  :
:           :                                 :          : receiving code     :
:           :                                 :          : review approval.   :
| **T1-03** | Gerrit Trusted Contributor      | Medium   | Relying on a       |
:           : Review Enforcement Verification :          : standard +2 vote   :
:           :                                 :          : from a non-trusted :
:           :                                 :          : contributor to     :
:           :                                 :          : fulfill strict     :
:           :                                 :          : Review-Enforcement :
:           :                                 :          : requirements.      :
| **T1-04** | Mandatory Gerrit Labels for     | High     | Acknowledging an   |
:           : Automated Submission            :          : approval but       :
:           :                                 :          : failing to apply   :
:           :                                 :          : the appropriate    :
:           :                                 :          : Gerrit labels to   :
:           :                                 :          : initiate the merge :
:           :                                 :          : pipeline.          :
| **T1-05** | Gerrit Automated Submission     | Medium   | Leaving an         |
:           : Triggers                        :          : approved patchset  :
:           :                                 :          : idle and waiting   :
:           :                                 :          : for maintainers to :
:           :                                 :          : manually merge it. :
| **T1-06** | Active Reviewer Rerouting for   | Medium   | Waiting weeks or   |
:           : Stalled Changes                 :          : months for an      :
:           :                                 :          : inactive or OOO    :
:           :                                 :          : reviewer to        :
:           :                                 :          : respond to a       :
:           :                                 :          : patchset update.   :

--------------------------------------------------------------------------------

### Rules

#### T1-01: Explicit Labeling for Gerrit Automated Submission

> **Rule:** Always apply `Verified+1` and `Commit-Queue+2` explicitly to trigger
> the final submission phase. Never assume a code approval automatically
> initiates the pipeline.
>
> **What:** Changes are not merged automatically upon receiving approval;
> contributors must explicitly set the `Verified+1` and `Commit-Queue+2` labels
> to trigger the final submission phase.
>
> **Applies To:** Gerrit review UI and change submission pipeline as defined in
> `CONTRIBUTING.md`.
>
> **Why:** Contributors often mistakenly assume an LGTM implies an immediate
> merge, leading to stalled changes. The project relies on explicitly triggering
> the Commit-Queue to finalize CI checks and perform the merge. Failing to
> adhere to this typically results in **Stalled Submission Pipeline**.

**Trap 1: Leaving a change idle after addressing comments or receiving a
reviewer's LGTM, expecting the reviewer to merge it.**

**Don't:**

*   Waiting indefinitely after reviewer posts 'LGTM'.

**Do:**

*   Vote `Verified+1` and `Commit-Queue+2` manually to submit the change to the
    automated queue.

**Exceptions:** Contributors lacking trusted permissions must ping a repository
maintainer to apply the final `Commit-Queue+2` vote.

--------------------------------------------------------------------------------

#### T1-02: Automated Submission via Commit-Queue (CQ)

> **Rule:** Must utilize the Gerrit Commit-Queue (CQ) labeling system to merge
> code. Maintainers must never perform direct manual submissions.
>
> **What:** Merging code must be triggered via the Gerrit Commit-Queue (CQ)
> labeling system rather than relying on direct manual submission by
> maintainers.
>
> **Applies To:** Gerrit code review UI and CI/CD submission workflow.
>
> **Why:** Contributors would request maintainers to directly merge patches once
> approved, bypassing the automated commit-queue pipeline, which guarantees that
> final integration tests pass before pushing to the target branch. Failing to
> adhere to this typically results in **Bypassed CI / Direct Submit**.

**Trap 1: Requesting a manual push or direct submit from repository maintainers
after receiving code review approval.**

**Don't:**

*   Leaving a comment: "I believe everything is ready for integrating this. So
    if either of you can submit it, it would be appreciated."

**Do:**

*   Applying the `Commit-Queue +2` (CQ+2) label in Gerrit, which delegates
    testing and the final merge operation to the automated bot.

--------------------------------------------------------------------------------

#### T1-03: Gerrit Trusted Contributor Review Enforcement Verification

> **Rule:** Verify review enforcement requirements are satisfied by contributors
> within the explicitly configured trusted group. Never cast misleading +2 votes
> if you lack valid trusted group privileges.
>
> **What:** Gerrit submission requirements may mandate specific approval levels
> (e.g., two trusted contributors). Votes from users with +2 access who are not
> in the designated 'trusted' group do not satisfy the 'Review-Enforcement'
> submit requirement.
>
> **Applies To:** Gerrit repository administration and code review voting
> workflows.
>
> **Why:** Non-trusted contributors with +2 rights were casting +2 votes on
> changes. These votes did not fulfill the 'Two trusted contributors'
> Review-Enforcement requirement, leading to stalled submissions and confusion
> regarding why the UI showed a +2 but blocked submission. Failing to adhere to
> this typically results in **Blocked Submission / Silent Requirement Failure**.

**Trap 1: Relying on a standard +2 vote from a non-trusted contributor to
fulfill strict Review-Enforcement requirements.**

**Don't:**

*   Leaving a +2 vote on a change as a non-trusted contributor, creating the
    false appearance that the Review-Enforcement requirement has been partially
    or fully met.

**Do:**

*   Verifying the reviewer is in the explicitly configured trusted group for the
    repository. If not, the reviewer should manually downgrade their invalid +2
    vote to a +1 to clearly indicate that their vote does not count toward the
    enforcement threshold.

**Exceptions:** Repositories where specific non-employee groups have been
explicitly added to the trusted administrators list.

--------------------------------------------------------------------------------

#### T1-04: Mandatory Gerrit Labels for Automated Submission

> **Rule:** Always apply `Verified+1` and `Commit-Queue+2` labels to initiate
> the CI merge process. Never leave an approved CL in a technically unlabeled
> state.
>
> **What:** A code change must receive explicit `Verified+1` and
> `Commit-Queue+2` labels by the author or reviewer to trigger the automated CI
> merge process.
>
> **Applies To:** Gerrit workflow / Merge execution phase.
>
> **Why:** Historically, leaving a Change List (CL) in an approved but unlabeled
> state causes the integration pipeline to stall indefinitely, requiring manual
> intervention or reviewer pinging to trigger the CI queue. Failing to adhere to
> this typically results in **Merge Pipeline Stall**.

**Trap 1: Acknowledging an approval but failing to apply the appropriate Gerrit
labels to initiate the merge pipeline.**

**Don't:**

*   Leaving the CL in an approved state and waiting for auto-submission without
    applying the `Verified+1` or `Commit-Queue+2` labels.

**Do:**

*   Explicitly applying `Verified+1` (and `Commit-Queue+2` if ready) once
    reviewers have approved the logic, to instruct the automation to merge the
    code.

--------------------------------------------------------------------------------

#### T1-05: Gerrit Automated Submission Triggers

> **Rule:** Must actively signal patch readiness to Gerrit systems using proper
> label thresholds. Avoid leaving patchsets idle assuming upstream maintainer
> action.
>
> **What:** A patchset requires specific label thresholds ('Verified+1' and
> 'Commit-Queue+2') to trigger automated submission in the Gerrit workflow.
>
> **Applies To:** Gerrit review UI and automated CI/CD submission process for
> the git-repo codebase.
>
> **Why:** Contributors frequently asked how to integrate changes after
> receiving an approval, leading to stalled patches because the automated
> pipeline was not explicitly triggered. Failing to adhere to this typically
> results in **Stalled Patch Integration**.

**Trap 1: Leaving an approved patchset idle and waiting for maintainers to
manually merge it.**

**Don't:**

*   Waiting indefinitely after receiving an 'LGTM' without setting workflow
    labels.

**Do:**

*   The patch author manually sets the 'Verified' flag (if locally tested) and
    applies the 'Commit-Queue+2' vote to signal readiness for automated merge.

--------------------------------------------------------------------------------

#### T1-06: Active Reviewer Rerouting for Stalled Changes

> **Rule:** Actively reroute reviews stalled by unresponsive or out-of-office
> (OOO) primary reviewers. Must explicitly tag alternate maintainers and
> document the absence to prevent lifecycle stalls.
>
> **What:** If the primary reviewer is out-of-office (OOO) or unresponsive for
> an extended period, contributors must actively CC and reroute the review to
> another active maintainer.
>
> **Applies To:** Gerrit review cycle and reviewer assignment process.
>
> **Why:** Patchsets have historically stalled for over a month due to reviewers
> taking extended leave without actively delegating their review queues. Failing
> to adhere to this typically results in **Indefinite Review Stalls**.

**Trap 1: Waiting weeks or months for an inactive or OOO reviewer to respond to
a patchset update.**

**Don't:**

*   Leaving a review assigned strictly to an unresponsive reviewer without
    notifying other maintainers or attempting to escalate.

**Do:**

*   Tag a new reviewer with 'PTAL' (Please Take A Look) in the thread,
    explicitly noting the original reviewer's absence, and confirm alignment
    with the original author.

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T4 | Python Code Formatting and Linting - *Proper formatting
    and static analysis are enforced before changes become eligible for final
    Gerrit review and automated integration.*
*   **Upstream:** T5 | Commit Metadata and History Standardization - *Accurate
    commit messaging and isolated history must be validated by reviewers prior
    to receiving approval labels.*
*   **Downstream:** T3 | CI Builder Environment and Execution Integrity -
    *Triggering the Commit-Queue directly invokes downstream LUCI environments
    to guarantee execution integrity prior to branch merge.*

## Chapter: CI Builder Environment and Execution Integrity

**Context:** This section defines strict guidelines for ensuring the resilience
of build scripts against missing dependencies and managing process execution
contexts within LUCI and local testing environments. Adherence guarantees robust
verification across diverse operating systems and CI pipelines while preventing
silent builder failures.

### Summary

| Rule ID   | Principle / Constraint    | Priority | Primary Symptom / Trap    |
| :-------- | :------------------------ | :------- | :------------------------ |
| **T3-01** | Verification Against      | High     | Running a standard local  |
:           : Breaking Change Build     :          : `make` without testing    :
:           : Configurations            :          : strict configurations or  :
:           :                           :          : breaking-change flags.    :
| **T3-02** | Windows Developer Mode    | Medium   | Attempting to run full    |
:           : Requirements for Tool     :          : local verification on a   :
:           : Verification              :          : standard Windows user     :
:           :                           :          : account.                  :
| **T3-03** | Graceful Degradation for  | Medium   | Assuming all local        |
:           : Missing Builder Utilities :          : developer utilities exist :
:           :                           :          : in the strict CI builder  :
:           :                           :          : environment and           :
:           :                           :          : unconditionally executing :
:           :                           :          : them.                     :
| **T3-04** | Contextual Diagnostic     | High     | Observing a generic CI    |
:           : Logging for LUCI CI       :          : failure without isolating :
:           : Failures                  :          : the specific process      :
:           :                           :          : execution context or      :
:           :                           :          : dependency resolution     :
:           :                           :          : step.                     :

--------------------------------------------------------------------------------

### Rules

#### T3-01: Verification Against Breaking Change Build Configurations

> **Rule:** Always explicitly test core build structure modifications with
> breaking changes enabled to ensure forward compatibility.
>
> **What:** When modifying core build structures, the build must be tested
> explicitly with breaking changes enabled to ensure forward compatibility and
> correct regeneration of generated files.
>
> **Applies To:** Local build environments and Makefile targets.
>
> **Why:** Changes might succeed in a standard default build but fail when
> breaking change toggles are activated, hiding underlying dependency or
> regeneration issues. Failing to adhere to this typically results in **Build
> Breakage / Stale Artifacts**.

**Trap 1: Running a standard local `make` without testing strict configurations
or breaking-change flags.**

**Don't:**

```bash
make -j
```

**Do:**

```bash
make -j WITH_BREAKING_CHANGES=1
```

--------------------------------------------------------------------------------

#### T3-02: Windows Developer Mode Requirements for Tool Verification

> **Rule:** Must execute local tool verification on Windows (gWindows) using an
> Administrator account to enable Developer Mode.
>
> **What:** Local verification of git-repo tooling on Windows (gWindows)
> explicitly requires the host environment to be running with Administrator
> privileges to enable Developer Mode.
>
> **Applies To:** Windows (gWindows) test environments verifying file system
> operations.
>
> **Why:** Without Developer Mode enabled (which necessitates Admin rights),
> features relying on advanced OS-level file system operations (like symlinks)
> cannot execute, permanently blocking full local test suite execution on
> standard accounts. Failing to adhere to this typically results in
> **Verification Blocked / OS Permission Error**.

**Trap 1: Attempting to run full local verification on a standard Windows user
account.**

**Don't:**

*   Executing the test suite from a non-elevated command prompt on Windows
    without Developer Mode.

**Do:**

*   Elevate to an Administrator account to enable Developer Mode before
    executing the test suite on gWindows.

--------------------------------------------------------------------------------

#### T3-03: Graceful Degradation for Missing Builder Utilities

> **Rule:** Always implement auto-skip logic for optional utilities in build
> scripts rather than hard-failing when unavailable on the CI builder.
>
> **What:** Build scripts and test suites must implement auto-skip logic for
> optional, environment-specific utilities rather than hard-failing when the
> utility is unavailable on the CI builder.
>
> **Applies To:** CI Builder environment scripts and test suites, specifically
> testing external CLI utilities (e.g., `help2man`).
>
> **Why:** When a required utility was not pre-installed on the CI builder
> image, the build hard-failed. Adding auto-skip logic allows the CI pipeline to
> remain unblocked while still providing local testing benefits for developers
> who have the tool installed. Failing to adhere to this typically results in
> **Build Failure / Blocked CI**.

**Trap 1: Assuming all local developer utilities exist in the strict CI builder
environment and unconditionally executing them.**

**Don't:**

```python
# BAD: Hard failure if utility is missing
subprocess.run(["help2man", "repo"], check=True)
```

**Do:**

```python
# GOOD: Auto-skip test if utility is missing in the environment
if not shutil.which("help2man"):
    self.skipTest("help2man not installed")
subprocess.run(["help2man", "repo"], check=True)
```

**Exceptions:** Core dependencies required for fundamental build steps cannot be
skipped and must be installed on the bot image.

--------------------------------------------------------------------------------

#### T3-04: Contextual Diagnostic Logging for LUCI CI Failures

> **Rule:** Must investigate CI builder failures by extracting and analyzing
> full execution context logs to isolate environmental roadblocks.
>
> **What:** CI builder failures must be investigated using full execution
> context logs (e.g., LUCI context, vpython3 resolution, and retcode outputs) to
> isolate environmental roadblocks.
>
> **Applies To:** LUCI builder execution environment, vpython3 resolution, and
> CI pipeline debugging.
>
> **Why:** CI commands failed with `retcode 1` due to external factors like
> specific URLs being flagged as suspect by internal security tools, breaking
> the build environment. Failing to adhere to this typically results in **Silent
> Builder Failure**.

**Trap 1: Observing a generic CI failure without isolating the specific process
execution context or dependency resolution step.**

**Don't:**

*   Restarting the CI pipeline blindly when a job fails with a generic retcode,
    ignoring potential external network or security blockers.

**Do:**

*   Extract the step-by-step LUCI context log, verify path resolution (e.g.,
    CIPD packages), and explicitly document external blockers like security
    flags in the review.

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T6 | Testing Strategy and State Isolation - *Test
    implementation dictates how missing builder utilities are mocked or
    gracefully skipped during execution.*
*   **Downstream:** T1 | Gerrit Submission and Labeling Workflow - *Automated
    Verified+1 labels rely entirely on the stable, unblocked execution of CI
    builder pipelines.*

## Chapter: Python Code Formatting and Linting

**Context:** This domain governs the automated enforcement of Python style
guidelines, mandating strict PEP-8 compliance, import sorting, and consistent
string quoting. All Python modifications must pass centralized static analysis
pipelines before integration to ensure codebase uniformity and prevent CI
regressions.

### Summary

| Rule ID   | Principle / Constraint   | Priority | Primary Symptom / Trap    |
| :-------- | :----------------------- | :------- | :------------------------ |
| **T4-01** | Automated Flake8         | Medium   | Relying purely on manual  |
:           : Post-Submit Verification :          : code review or sporadic   :
:           :                          :          : local linting without a   :
:           :                          :          : continuous integration    :
:           :                          :          : check.                    :
| **T4-02** | Mandatory Python         | High     | Using single quotes for   |
:           : Formatting and Import    :          : strings and appending new :
:           : Sorting                  :          : imports to the bottom of  :
:           :                          :          : the import block without  :
:           :                          :          : alphabetical or           :
:           :                          :          : categorical sorting.      :
| **T4-03** | Strict Python Import     | High     | Mixing local application  |
:           : Ordering                 :          : imports with standard     :
:           :                          :          : library imports, causing  :
:           :                          :          : linting tools to fail the :
:           :                          :          : CQ job.                   :

--------------------------------------------------------------------------------

### Rules

#### T4-01: Automated Flake8 Post-Submit Verification

> **Rule:** Always configure and maintain centralized CI workflows to
> automatically run static analysis and validate Python code styling
> post-submit.
>
> **What:** Static analysis and Python linting must be automated via a
> centralized CI pipeline (e.g., Flake8 post-submit workflows) to enforce
> consistent style and prevent basic errors.
>
> **Applies To:** All Python files in the git-repo codebase; specifically
> validated via `.github/workflows/flake8-postsubmit.yml`.
>
> **Why:** Relying strictly on manual code review to catch styling and linting
> violations is error-prone. Automation ensures a baseline of code quality on
> every code push without consuming human review cycles. Failing to adhere to
> this typically results in **Linting Regression / Style Violation**.

**Trap 1: Relying purely on manual code review or sporadic local linting without
a continuous integration check.**

**Don't:**

*   Committing Python code without an active CI linting workflow configuration.

**Do:**

*   Maintain `.github/workflows/flake8-postsubmit.yml` to automatically run
    flake8 on target branches.

--------------------------------------------------------------------------------

#### T4-02: Mandatory Python Formatting and Import Sorting

> **Rule:** Must format Python code to enforce double-quoted strings and
> alphabetically sorted import blocks to satisfy automated formatting checks.
>
> **What:** Python code modifications must pass automated style and linting
> checks ('Verify git-repo CL'), which strictly enforce string quote conventions
> (preferring double quotes), import block sorting, and PEP-8 style formatting.
>
> **Applies To:** All Python source files modified in the git-repo codebase.
>
> **Why:** Developers submitting patches with single-quoted strings or unsorted
> imports triggered automated CI failures in the `Verify git-repo CL` job,
> completely blocking code submission until formatting tools were executed
> locally. Failing to adhere to this typically results in **CI Pipeline
> Failure**.

**Trap 1: Using single quotes for strings and appending new imports to the
bottom of the import block without alphabetical or categorical sorting.**

**Don't:**

```python
import sys
import os

msg = 'This is an error'
```

**Do:**

```python
import os
import sys

msg = "This is an error"
```

--------------------------------------------------------------------------------

#### T4-03: Strict Python Import Ordering

> **Rule:** Always segment and order Python imports strictly according to
> project standards (standard library, third-party, local) to prevent CQ
> pipeline failures.
>
> **What:** Python module imports must adhere strictly to the project's
> formatting rules (e.g., standard library, third-party, local module ordering)
> to pass automated Commit-Queue (CQ) checks.
>
> **Applies To:** Python source files.
>
> **Why:** Non-standard import blocks cause the automated CI/CQ linting pipeline
> to fail, completely blocking submission even if the core functional logic of
> the patch is flawless. Failing to adhere to this typically results in **CI
> Linting Failure**.

**Trap 1: Mixing local application imports with standard library imports,
causing linting tools to fail the CQ job.**

**Don't:**

```python
import sys
import my_local_module
import os
```

**Do:**

```python
import os
import sys

import my_local_module
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T3 | CI Builder Environment and Execution Integrity -
    *Reliable CI builder environments must be available to execute the static
    analysis and Python formatting verifications.*
*   **Downstream:** T1 | Gerrit Submission and Labeling Workflow - *Formatting
    and linting rules must be fully satisfied before automated mechanisms like
    the Commit-Queue (CQ+2) will merge code into the repository.*

## Chapter: Commit Metadata and History Standardization

**Context:** This domain governs the structural composition and metadata
formatting of change lists (CLs) within the git-repo codebase. Strict adherence
ensures precise issue tracker integration, reliable CI/CD parsing, and atomic,
bisectable repository history.

### Summary

| Rule ID   | Principle / Constraint    | Priority | Primary Symptom / Trap    |
| :-------- | :------------------------ | :------- | :------------------------ |
| **T5-01** | Strict Commit Message Bug | Medium   | Providing free-text       |
:           : Tag Formatting            :          : descriptions, arbitrary   :
:           :                           :          : prefixes, or non-standard :
:           :                           :          : bug references in the     :
:           :                           :          : commit block.             :
| **T5-02** | Atomic and Bisectable     | High     | Waiting for an entire     |
:           : Change Integration        :          : feature stack of multiple :
:           :                           :          : interdependent CLs to be  :
:           :                           :          : approved before merging   :
:           :                           :          : the base commits.         :
| **T5-03** | Explicit Bug Tracker      | Medium   | Submitting a fix or       |
:           : Linking for Context       :          : revert without            :
:           : Restoration               :          : referencing the           :
:           :                           :          : corresponding bug tracker :
:           :                           :          : issue detailing the       :
:           :                           :          : specific regression or    :
:           :                           :          : stack trace.              :
| **T5-04** | Atomic Change List        | Medium   | Submitting a single large |
:           : Decomposition             :          : CL that touches multiple  :
:           :                           :          : isolated components or    :
:           :                           :          : implements several        :
:           :                           :          : distinct features         :
:           :                           :          : simultaneously.           :

--------------------------------------------------------------------------------

### Rules

#### T5-01: Strict Commit Message Bug Tag Formatting

> **Rule:** Must use the exact `Bug: <number>` syntax in commit messages to
> properly link issue trackers.
>
> **What:** Commit messages must link directly to issue trackers using the
> explicit 'Bug: <number>' syntax to allow reliable parsing by CI/CD and history
> tracking systems.
>
> **Applies To:** Commit messages across all git-repo changes.
>
> **Why:** Improperly formatted bug tags fail to link with the external issue
> tracker, severing historical context and breaking automated post-submit
> tracking workflows. Failing to adhere to this typically results in **Broken
> Traceability / Pre-submit Failure**.

**Trap 1: Providing free-text descriptions, arbitrary prefixes, or non-standard
bug references in the commit block.**

**Don't:**

```text
Fixes bug 486536908
Closes issue 486536908
```

**Do:**

```text
Bug: 486536908
```

--------------------------------------------------------------------------------

#### T5-02: Atomic and Bisectable Change Integration

> **Rule:** Always submit code incrementally as isolated, functional units
> rather than hoarding monolithic stacks.
>
> **What:** Code changes must be submitted incrementally as isolated, functional
> units rather than waiting to merge a massive interdependent stack all at once.
>
> **Applies To:** Git commit history, PR structuring, and stack-based code
> integration.
>
> **Why:** Contributors accustomed to integrating full monolithic stacks at once
> held off on landing initial, stable changes. This practice hinders the ability
> to isolate regressions via `git bisect` and prevents foundational code from
> "baking" in production. Failing to adhere to this typically results in
> **Bisection Breakage / Monolithic Rollbacks**.

**Trap 1: Waiting for an entire feature stack of multiple interdependent CLs to
be approved before merging the base commits.**

**Don't:**

*   Holding all changes in a stack locally or in code review until the final
    feature patch is approved, then landing 10+ patches simultaneously.

**Do:**

*   Landing initial, independent CLs one-by-one as soon as they are approved.
    Ensuring each commit is independently usable and does not break the build.

--------------------------------------------------------------------------------

#### T5-03: Explicit Bug Tracker Linking for Context Restoration

> **Rule:** Must include a direct URL to the relevant bug tracker issue
> documenting the failure traceback when submitting a regression fix or revert.
>
> **What:** When submitting a change (especially a revert or bug fix) addressing
> a specific runtime regression, the commit metadata or patchset-level comments
> must include a direct link to the bug tracker issue documenting the failure
> traceback.
>
> **Applies To:** Commit messages and patchset documentation during code
> reviews, particularly for reverts.
>
> **Why:** A previous commit caused a runtime regression (e.g., an
> AttributeError related to a missing object attribute). Without linking the
> specific issue containing the traceback, reviewers lacked the necessary
> context to justify restoring the previous codebase state. Failing to adhere to
> this typically results in **Undocumented Regression / Context Loss**.

**Trap 1: Submitting a fix or revert without referencing the corresponding bug
tracker issue detailing the specific regression or stack trace.**

**Don't:**

*   Reverting a change with a vague description like "Fixing previous breakage"
    or "Reverting due to pipeline failure" without providing the traceback
    source.

**Do:**

*   Linking the specific issue tracker URL containing the exact failure mode.
    Example: "for more context, see
    https://g-issues.gerritcodereview.com/issues/[ISSUE_ID]#comment4"

--------------------------------------------------------------------------------

#### T5-04: Atomic Change List Decomposition

> **Rule:** Never submit large, monolithic change lists; always decompose them
> into logically independent patchsets.
>
> **What:** Large, monolithic change lists (CLs) must be broken down into
> smaller, logically independent patchsets to ensure accurate review and
> historical bisectability.
>
> **Applies To:** Version control history and code review scoping.
>
> **Why:** Massive CLs heavily increase reviewer cognitive load, making thorough
> reviews impossible and complicating future `git bisect` operations when
> tracking down the origin of a regression. Failing to adhere to this typically
> results in **Unreviewable Monolithic Change**.

**Trap 1: Submitting a single large CL that touches multiple isolated components
or implements several distinct features simultaneously.**

**Don't:**

*   A single CL containing sweeping refactoring, new feature implementation, and
    unrelated bug fixes.

**Do:**

*   Breaking the monolithic change into smaller, logically dependent or
    independent CLs where each addresses one specific piece of the feature or
    refactor.

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Downstream:** T1 | Gerrit Submission and Labeling Workflow - *Gerrit and
    CI pipelines strictly rely on standardized commit metadata to link tracking
    issues and depend on atomic patchsets to execute automated review and
    verification correctly.*

## Chapter: Testing Strategy and State Isolation

**Context:** This chapter governs test implementation boundaries, emphasizing
pragmatic mocking limits to prevent false positives and detailing acceptable
workflows for deferred test coverage. Strict adherence ensures robust state
isolation and maintains development velocity without compromising verification
integrity.

### Summary

| Rule ID   | Principle / Constraint   | Priority | Primary Symptom / Trap     |
| :-------- | :----------------------- | :------- | :------------------------- |
| **T6-01** | Pragmatic Mocking        | Medium   | Mocking the entire core    |
:           : Boundaries in Unit Tests :          : state or framework         :
:           :                          :          : dependencies just to force :
:           :                          :          : a unit test for a highly   :
:           :                          :          : integrated function.       :
| **T6-02** | Deferred Test            | Medium   | Submitting functional code |
:           : Implementation via       :          : without matching test      :
:           : Follow-up                :          : coverage and stalling the  :
:           :                          :          : merge while complex tests  :
:           :                          :          : are written.               :

--------------------------------------------------------------------------------

### Rules

#### T6-01: Pragmatic Mocking Boundaries in Unit Tests

> **Rule:** Always restrict unit tests to isolated methods and avoid aggressive
> mocking of core functionality to prevent brittle, false-positive verification.
>
> **What:** Do not aggressively mock core functionality in unit tests; restrict
> unit tests to isolated methods to avoid creating brittle tests based on false
> assumptions when an integration framework is unavailable.
>
> **Applies To:** Test suite implementation (Unit vs. Integration testing
> boundaries).
>
> **Why:** Over-mocking complex systems in unit tests leads to scenarios where
> tests pass but the core integration fails in production because the unit test
> mocks assumed incorrect behavior about the underlying environment. Failing to
> adhere to this typically results in **False Positive Test Passage**.

**Trap 1: Mocking the entire core state or framework dependencies just to force
a unit test for a highly integrated function.**

**Don't:**

*   Mocking file systems, external processes, and global state heavily to test a
    core workflow orchestrator in a unit test suite.

**Do:**

*   Limiting unit tests strictly to isolated utility methods (e.g., adding
    promisor files) and explicitly documenting testing gaps that require
    integration test frameworks.

**Exceptions:** Isolated helper methods or purely functional data
transformations should be fully unit tested with appropriate mocked inputs.

--------------------------------------------------------------------------------

#### T6-02: Deferred Test Implementation via Follow-up

> **Rule:** Never stall critical feature merges indefinitely for test
> implementation if maintainers authorize formalized, immediate follow-up test
> coverage.
>
> **What:** New logic requires automated tests; however, reviewers may permit
> test coverage to be implemented in a subsequent follow-up CL to maintain
> development velocity.
>
> **Applies To:** Feature development, regression testing, and code review
> criteria.
>
> **Why:** Reviewers identified a lack of test coverage for new functionality
> but opted not to block the immediate patchset, instead formalizing the test
> requirement as a near-term follow-up task. Failing to adhere to this typically
> results in **Missing Test Coverage**.

**Trap 1: Submitting functional code without matching test coverage and stalling
the merge while complex tests are written.**

**Don't:**

*   Blocking a necessary feature indefinitely due to missing unit tests when a
    follow-up CL is viable and acceptable to maintainers.

**Do:**

*   Approve the feature with an explicit, documented 'TODO' for a follow-up CL
    dedicated strictly to adding the corresponding automated tests.

**Exceptions:** Critical path features or security fixes where a lack of
immediate coverage introduces an unacceptable regression risk.

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T1 | Gerrit Submission and Labeling Workflow - *Reviewer
    approval mechanisms and label enforcement dictate when a feature can merge
    while deferring tests to a follow-up CL.*
*   **Downstream:** T3 | CI Builder Environment and Execution Integrity -
    *Pragmatically bounded unit and integration tests ensure reliable CI
    pipeline execution without false-positive success markers.*
