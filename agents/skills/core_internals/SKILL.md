---
name: core-internals
description: Provides guidance and best practices on concurrent synchronization, IPC, filesystem atomicity, git subprocess wrapping, XML manifests, and CLI argument parsing for git-repo.
---

# Git Repo Core Internals Engineering Guide

## Executive Summary

Welcome to the authoritative engineering guide for Git Repository Management
within the git-repo codebase. This repository of tribal knowledge exists to
safeguard the intricate orchestration of our multi-repository synchronization
toolchain. Historically, complex operations such as parallelized network
fetches, layered manifest overrides, and interactive terminal rendering have
been vulnerable to subtle concurrency races, deadlocks, and fragile system
states. This guide captures these critical failure modes—ranging from IPC
serialization bottlenecks and filesystem lock contentions to non-hermetic test
pollution—and establishes rigid engineering constraints to prevent their
regression.

To maintain system stability, this guide enforces strict architectural
boundaries across the tooling ecosystem. It mandates stateless execution for
multiprocessing pools, guaranteed atomicity for worktree layout modifications,
and deterministic error translation for all standard Git subprocesses.
Furthermore, it defines the standard operating procedures for canonical manifest
object deduplication, the modernization of our hermetic testing frameworks, and
the delivery of consistent, machine-readable CLI interfaces. By adhering to
these paradigms, incoming engineers will ensure the reliability, performance,
and extensibility of git-repo's core repository management infrastructure.

## Summary

| Chapter Theme / Title                | Scope & Objective                     |
| :----------------------------------- | :------------------------------------ |
| **Concurrent Synchronization & IPC** | This domain governs the stable        |
:                                      : orchestration of parallel network     :
:                                      : fetches, local checkouts, and         :
:                                      : interleaved subprocess routines. It   :
:                                      : strictly enforces safe                :
:                                      : multiprocessing IPC, deterministic    :
:                                      : Git locking via exponential backoff,  :
:                                      : and state synchronization across      :
:                                      : concurrent pool workers.              :
| **Filesystem Atomicity & Worktree    | This domain governs the deterministic |
: Layout**                             : creation, migration, and cleanup of   :
:                                      : internal repository structures and    :
:                                      : Git worktrees. It relies on ephemeral :
:                                      : temporary directories, atomic rename  :
:                                      : operations, and robust error recovery :
:                                      : to prevent corrupted states during    :
:                                      : unexpected interruptions.             :
| **Subprocess Git Integration & Error | This chapter defines the constraints  |
: Translation**                        : for wrapping, executing, and          :
:                                      : translating standard Git subprocesses :
:                                      : within the Repo tooling ecosystem. It :
:                                      : mandates the use of centralized       :
:                                      : command abstractions, strict version  :
:                                      : gating, and deterministic stream      :
:                                      : handling to guarantee reliable        :
:                                      : repository state management and       :
:                                      : actionable error reporting.           :
| **Manifest Object Model &            | This chapter governs the parsing,     |
: Deduplication**                      : validation, and canonicalization of   :
:                                      : XML manifest components. It strictly  :
:                                      : enforces semantic immutability via    :
:                                      : NamedTuple implementations, defensive :
:                                      : copying for hierarchical override     :
:                                      : scoping, and deterministic            :
:                                      : JSON-backed file tracking across the  :
:                                      : subsystem.                            :
| **Hermetic Testing & Test            | This domain governs the migration of  |
: Modernization**                      : legacy unittest suites to modern      :
:                                      : pytest functional paradigms and the   :
:                                      : establishment of hermetic session     :
:                                      : fixtures. It enforces strict          :
:                                      : environment isolation to prevent      :
:                                      : global state pollution (e.g.,         :
:                                      : developer .gitconfig bleeding) while  :
:                                      : safely intercepting standard streams  :
:                                      : and filesystem paths.                 :
| **CLI Argument Parsing & UX          | This chapter governs the lifecycle,   |
: Consistency**                        : validation, and execution of          :
:                                      : command-line arguments, enforcing     :
:                                      : strict standardization for            :
:                                      : machine-readable serialization,       :
:                                      : unified logging, and deterministic,   :
:                                      : thread-safe terminal interactions.    :
| **Repo Hooks Framework**             | The Repo Hooks Framework governs the  |
:                                      : execution, parameter validation, and  :
:                                      : lifecycle management of user-defined  :
:                                      : scripts within the repository         :
:                                      : ecosystem. It ensures seamless        :
:                                      : integration of extensions like        :
:                                      : post-sync or pre-upload while         :
:                                      : strictly isolating their execution    :
:                                      : failures from core operational        :
:                                      : workflows.                            :

--------------------------------------------------------------------------------
--------------------------------------------------------------------------------

## Chapter: Concurrent Synchronization & IPC

**Context:** This domain governs the stable orchestration of parallel network
fetches, local checkouts, and interleaved subprocess routines. It strictly
enforces safe multiprocessing IPC, deterministic Git locking via exponential
backoff, and state synchronization across concurrent pool workers.

### Summary

| Rule ID   | Principle / Constraint    | Priority | Primary Symptom / Trap    |
| :-------- | :------------------------ | :------- | :------------------------ |
| **T1-01** | Stateless Class Methods   | High     | Passing bound instance    |
:           : for Parallel Pool Workers :          : methods to a parallel     :
:           :                           :          : executor, dragging        :
:           :                           :          : unnecessary state into    :
:           :                           :          : the multiprocessing       :
:           :                           :          : serialization pipeline.   :
| **T1-02** | Buffered Serialization of | High     | Executing terminal print  |
:           : Concurrent Standard       :          : calls directly from       :
:           : Output                    :          : within a parallelized     :
:           :                           :          : worker routine.           :
| **T1-03** | Interleaved Sync Path     | High     | Dispatching parallel      |
:           : Validation                :          : checkout jobs across all  :
:           :                           :          : project variants without  :
:           :                           :          : verifying layout types.   :
| **T1-04** | Guaranteed                | Critical | Placing save operations   |
:           : Synchronization State     :          : at the very end of an     :
:           : Persistence               :          : execution path without    :
:           :                           :          : exception guards.         :
| **T1-05** | Jittered Exponential      | Critical | Firing `git submodule     |
:           : Backoff for Git           :          : init` concurrently        :
:           : Configuration Locks       :          : without retry logic for   :
:           :                           :          : `config.lock` failures.   :
| **T1-06** | Exponential Backoff for   | High     | Failing a git command     |
:           : Concurrent Git Config     :          : immediately without       :
:           : Locks                     :          : evaluating standard       :
:           :                           :          : streams for transient     :
:           :                           :          : lock errors.              :
| **T1-07** | Hard Termination on       | Critical | Logging an error state    |
:           : Interleaved Sync Stalls   :          : inside a `while` loop but :
:           :                           :          : allowing the next loop    :
:           :                           :          : iteration to execute.     :
| **T1-08** | Resource Management via   | High     | Initializing proxy        |
:           : Context Handlers for IPC  :          : connections or            :
:           :                           :          : multiprocessing managers  :
:           :                           :          : as raw variable           :
:           :                           :          : assignments without a     :
:           :                           :          : guaranteed teardown       :
:           :                           :          : phase.                    :
| **T1-09** | Dual-Channel Error        | High     | Iterating over aggregated |
:           : Handling in Parallel      :          : data lists to decide if a :
:           : Processing                :          : parallel orchestration    :
:           :                           :          : should abort.             :
| **T1-10** | Minimum Process Pool Job  | Critical | Directly using            |
:           : Count Safeguard           :          : `min(target, len(items))` :
:           :                           :          : to determine pool size,   :
:           :                           :          : which breaks if the item  :
:           :                           :          : list is unexpectedly      :
:           :                           :          : empty.                    :
| **T1-11** | Safeguarding Object State | Critical | Truncating object         |
:           : Across Parallel Execution :          : payloads to scalar        :
:           : Boundaries                :          : indices during IPC        :
:           :                           :          : context setup without     :
:           :                           :          : updating the receiver     :
:           :                           :          : logic to rehydrate the    :
:           :                           :          : objects.                  :
| **T1-12** | Explicit Context          | High     | Assuming child workers    |
:           : Initialization for        :          : inherit updated class     :
:           : Multiprocessing Pools     :          : variables inherently      :
:           :                           :          : without explicit          :
:           :                           :          : initialization.           :
| **T1-13** | Dynamic Task Chunk Sizing | Medium   | Passing a hardcoded batch |
:           : in Parallel Execution     :          : integer to the            :
:           :                           :          : `chunksize` parameter.    :
| **T1-14** | Deferred Worktree         | High     | Returning early from the  |
:           : Operations in Sync Local  :          : sync phase without        :
:           : Half                      :          : applying required file    :
:           :                           :          : operations.               :

--------------------------------------------------------------------------------

### Rules

#### T1-01: Stateless Class Methods for Parallel Pool Workers

> **Rule:** Always implement multiprocessing pool targets as stateless class
> methods or standalone functions to bypass process serialization constraints.
>
> **What:** Worker execution targets within multiprocessing pools must be
> constructed as fully decoupled class methods or standalone functions to bypass
> process serialization constraints.
>
> **Applies To:** Multiprocessing process pools, concurrent task scheduling, and
> `ExecuteInParallel` implementations.
>
> **Why:** Command execution objects were heavily bound to system state.
> Attempting to pass instance methods (`self.method`) to a multiprocessing pool
> frequently caused `PicklingError` crashes, as the underlying Python
> serialization mechanism cannot cleanly isolate bound object graphs. Failing to
> adhere to this typically results in **IPC Serialization Error**.

**Trap 1: Passing bound instance methods to a parallel executor, dragging
unnecessary state into the multiprocessing serialization pipeline.**

**Don't:**

```python
class InfoCommand:
    def _worker_logic(self, project):
        pass

    def run(self):
        self.ExecuteInParallel(jobs, self._worker_logic, projects)
```

**Do:**

```python
class InfoCommand:
    @classmethod
    def _worker_logic(cls, project_idx):
        project = cls.get_parallel_context()["projects"][project_idx]
        pass

    def run(self):
        self.ExecuteInParallel(jobs, self._worker_logic, range(len(projects)))
```

**Exceptions:** Threading-based execution models where memory is shared and
pickling is not strictly enforced.

--------------------------------------------------------------------------------

#### T1-02: Buffered Serialization of Concurrent Standard Output

> **Rule:** Must capture standard output generated by concurrently executing
> tasks into isolated memory buffers for sequential display in the parent
> process.
>
> **What:** Data emitted by concurrently executing tasks must be captured into
> isolated memory buffers and returned to the parent process for sequential
> display.
>
> **Applies To:** Parallel process execution layers generating human-readable
> CLI output.
>
> **Why:** When command execution was parallelized, worker processes wrote
> directly to standard output. This created severe race conditions resulting in
> garbled, interleaved text output on the user's terminal. Failing to adhere to
> this typically results in **Interleaved Terminal Output**.

**Trap 1: Executing terminal print calls directly from within a parallelized
worker routine.**

**Don't:**

```python
@classmethod
def _DiffHelper(cls, project):
    print(f"Project: {project.name}")
    print(f"Revision: {project.rev}")
```

**Do:**

```python
@classmethod
def _DiffHelper(cls, project):
    buf = io.StringIO()
    buf.write(f"Project: {project.name}\n")
    buf.write(f"Revision: {project.rev}\n")
    return buf.getvalue()

# In main process:
for output in results:
    print(output, end="")
```

--------------------------------------------------------------------------------

#### T1-03: Interleaved Sync Path Validation

> **Rule:** Always validate the presence of a worktree when executing
> interleaved sync processes to prevent layout evaluation crashes.
>
> **What:** When executing interleaved sync processes (parallelized network
> fetches and checkouts), the operation must explicitly validate the presence of
> a worktree, as not all Git repository types (e.g., mirrors) maintain local
> file checkouts.
>
> **Applies To:** Concurrency logic within `sync.py`.
>
> **Why:** Changing the default mode of `repo sync` to interleaved parallelized
> checkout tasks indiscriminately. This immediately broke AOSP mirror syncing
> because mirrors lack local checkout paths, resulting in a `TypeError` when
> evaluating `NoneType` paths. Failing to adhere to this typically results in
> **TypeError / Sync Failure**.

**Trap 1: Dispatching parallel checkout jobs across all project variants without
verifying layout types.**

**Don't:**

*   Assuming `project.worktree` always contains an `os.PathLike` object during
    interleaved syncing.

**Do:**

*   Adding guard clauses to verify `project.worktree is not None` and handling
    `--mirror` modes explicitly before adding checkout tasks to the thread pool.

--------------------------------------------------------------------------------

#### T1-04: Guaranteed Synchronization State Persistence

> **Rule:** Must execute synchronization telemetry saving operations within
> `try...finally` blocks to guarantee data retention across execution
> interrupts.
>
> **What:** Core sync operations must wrap network and filesystem operations in
> `try...finally` blocks, ensuring that synchronization metadata (`_fetch_times`
> and `_local_sync_state`) is persisted even if the sync operation fails or is
> interrupted.
>
> **Applies To:** `subcmds/sync.py`, particularly the `_Fetch` logic and
> multiprocessing worker loops.
>
> **Why:** If a synchronization process encountered an error (like a fetch
> failure), the operation exited early, dropping valuable telemetry and
> optimization data (fetch times) for projects that successfully synced prior to
> the crash. Failing to adhere to this typically results in **Telemetry Loss /
> Sync State Inconsistency**.

**Trap 1: Placing save operations at the very end of an execution path without
exception guards.**

**Don't:**

```python
result = self._Fetch(to_fetch, opt, err_event)
if not result.success:
    raise SyncError("failed")

# BAD: Never reached if an error is raised
self._fetch_times.Save()
```

**Do:**

```python
try:
    result = self._Fetch(to_fetch, opt, err_event)
    if not result.success:
        raise SyncError("failed")
finally:
    # GOOD: Always saves telemetry state
    self._fetch_times.Save()
```

--------------------------------------------------------------------------------

#### T1-05: Jittered Exponential Backoff for Git Configuration Locks

> **Rule:** Always wrap concurrent Git mutations to shared configurations in an
> exponential backoff routine with jitter to mitigate transient filesystem
> locks.
>
> **What:** When initializing submodules concurrently (e.g., `git submodule
> init`), the system must employ an exponential backoff mechanism with
> randomized jitter to handle transient filesystem lock errors on `.git/config`.
>
> **Applies To:** Submodule initialization and any highly parallel Git
> subprocesses mutating shared configuration state.
>
> **Why:** Running `repo sync -j<N>` caused multiple child processes to
> simultaneously attempt `git submodule init`, which led to lock contention on
> the parent project's config file and caused the entire sync operation to fail.
> Failing to adhere to this typically results in **File Lock Contention / Sync
> Failure**.

**Trap 1: Firing `git submodule init` concurrently without retry logic for
`config.lock` failures.**

**Don't:**

```python
# BAD: Fails immediately if .git/config.lock exists
subprocess.run(["git", "submodule", "init", "--", path], check=True)
```

**Do:**

```python
# GOOD: Catch lock errors and retry with jitter
for attempt in range(MAX_RETRIES):
    p = subprocess.run(["git", "submodule", "init", "--", path], stderr=subprocess.PIPE)
    if p.returncode == 0:
        break
    if "could not lock config file" in p.stderr:
        time.sleep(base_delay * (2 ** attempt) + random.uniform(0, jitter))
```

**Exceptions:** Non-lock related Git errors should still fail immediately
without retrying.

--------------------------------------------------------------------------------

#### T1-06: Exponential Backoff for Concurrent Git Config Locks

> **Rule:** Must analyze captured Git error streams to detect config lock
> contention and orchestrate retries via structured logging instead of immediate
> process failure.
>
> **What:** Concurrent git operations modifying `.git/config` (such as submodule
> initialization) must utilize an exponential retry mechanism with jitter to
> handle transient filesystem lock contention. Standard output and error streams
> must be captured and parsed to detect these locks.
>
> **Applies To:** project.py, specifically concurrent `git submodule init`
> operations or any parallel processes altering local repository configuration.
>
> **Why:** When synchronizing with high job values (-j), multiple parallel
> processes modifying `.git/config` triggered race conditions, throwing 'could
> not lock config file' errors and aborting the sync. Failing to adhere to this
> typically results in **Transient Sync Failure / Lock Contention**.

**Trap 1: Failing a git command immediately without evaluating standard streams
for transient lock errors.**

**Don't:**

```python
# BAD: Fails immediately on lock contention
if GitCommand(self, cmd).Wait() != 0:
    raise GitError(f"{self.name} submodule init failed")
```

**Do:**

```python
# GOOD: Captures stdout/stderr and retries on 'lock' matches
git_cmd = GitCommand(None, cmd, capture_stdout=True, capture_stderr=True)
if git_cmd.Wait() != 0:
    error = git_cmd.stderr or git_cmd.stdout
    if "lock" in error:
        # apply exponential backoff + jitter logic
    else:
        git_cmd.VerifyCommand()  # Propagate real error
```

**Trap 2: Using raw `print` statements to log retry attempts, which breaks
structured output formats.**

**Don't:**

```python
# BAD: Unstructured print to stdout
print(f"Attempt {attempt+1}: git {' '.join(cmd)} failed. Sleeping...")
```

**Do:**

```python
# GOOD: Forwarded to centralized logger
logger.warning("Attempt %d/%d: git %s failed. Error: %s. Sleeping %.2fs before retrying.", attempt+1, max_retries, cmd, error, delay)
```

**Exceptions:** Non-lock related Git errors should break the retry loop and be
propagated immediately via `git_cmd.VerifyCommand()`.

--------------------------------------------------------------------------------

#### T1-07: Hard Termination on Interleaved Sync Stalls

> **Rule:** Must trigger a definitive execution break and flag error signals
> whenever an unresolvable stall is detected in an interleaved control loop.
>
> **What:** When an unresolvable stall is detected within an interleaved or
> parallel execution loop, the system must trigger a definitive state break
> (e.g., setting global events and breaking the loop) to prevent infinite
> deadlocks.
>
> **Applies To:** subcmds/sync.py, specifically `_SyncInterleaved` or any
> looping logic monitoring pending sets.
>
> **Why:** A bug existed where a stall was logged but the loop terminator
> (`break`) and error trigger (`err_event.set()`) were accidentally omitted.
> This allowed the sync routine to lock up infinitely when interdependent
> projects failed to checkout. Failing to adhere to this typically results in
> **Infinite Loop / Deadlock**.

**Trap 1: Logging an error state inside a `while` loop but allowing the next
loop iteration to execute.**

**Don't:**

```python
# BAD: Omitted termination control flow
if prev_pending == pending_relpaths:
    logger.error("Stall detected")
prev_pending = pending_relpaths
```

**Do:**

```python
# GOOD: Set event signals and immediately break
if prev_pending == pending_relpaths:
    logger.error("Stall detected")
    err_event.set()
    break
```

--------------------------------------------------------------------------------

#### T1-08: Resource Management via Context Handlers for IPC

> **Rule:** Always initialize multiprocessing components and background proxies
> within `with` statement context blocks to assure teardown semantics.
>
> **What:** Multiprocessing managers and SSH proxies initialized for parallel
> workflows must be wrapped in `with` block context managers to guarantee
> cleanup of background processes and multiplexing sockets.
>
> **Applies To:** Concurrent network operations and parallelized repository
> synchronization (`subcmds/sync.py`).
>
> **Why:** When adding an interleaved fetch/checkout feature, parallel
> operations required shared synchronization dictionaries and SSH connection
> multiplexing. Without context managers, exceptions or interrupts (e.g.,
> KeyboardInterrupt) would leave orphaned background processes and abandoned
> sockets. Failing to adhere to this typically results in **Resource Leaks /
> Orphaned Sockets**.

**Trap 1: Initializing proxy connections or multiprocessing managers as raw
variable assignments without a guaranteed teardown phase.**

**Don't:**

```python
# BAD: No guaranteed cleanup on exception
manager = multiprocessing.Manager()
ssh_proxy = ssh.ProxyManager(manager)
process_tasks(ssh_proxy)
```

**Do:**

```python
# GOOD: Context managers assure RAII semantics
with multiprocessing.Manager() as manager:
    with ssh.ProxyManager(manager) as ssh_proxy:
        process_tasks(ssh_proxy)
```

--------------------------------------------------------------------------------

#### T1-09: Dual-Channel Error Handling in Parallel Processing

> **Rule:** Must decouple fast-fail signaling events from aggregated batch data
> processing logic to ensure immediate worker termination across processes.
>
> **What:** In concurrent execution environments, inter-process signaling (for
> immediate control flow) must be strictly separated from data aggregation (for
> end-of-batch error reporting).
>
> **Applies To:** Multi-process synchronization pools (`_SyncInterleaved`,
> `_SyncPhased`) and worker callback processors.
>
> **Why:** Reviewers questioned why a separate event flag was used when an array
> of errors was already being populated. Using only an aggregated list prevented
> workers from rapidly terminating each other via fail-fast mechanisms. Failing
> to adhere to this typically results in **Delayed Worker Termination**.

**Trap 1: Iterating over aggregated data lists to decide if a parallel
orchestration should abort.**

**Don't:**

```python
# BAD: Waiting to process the whole batch before aborting
errors.append(result.error)
if errors and opt.fail_fast:
    pool.close()
```

**Do:**

```python
# GOOD: Using an IPC Event for immediate cross-process signaling
err_event.set()
errors.append(result.error)
if not ret and opt.fail_fast:
    pool.close()
```

--------------------------------------------------------------------------------

#### T1-10: Minimum Process Pool Job Count Safeguard

> **Rule:** Must bind dynamically computed multiprocessing job allocations to a
> minimum floor of 1 to prevent initialization crashes.
>
> **What:** When determining the number of worker processes for parallel
> execution based on a variable target length (e.g., an array of projects), the
> resulting worker count must be explicitly bound to a minimum of 1.
>
> **Applies To:** Network fetch logic and multiprocessing pool initializations
> (e.g., `_Fetch` in `sync.py`).
>
> **Why:** A regression occurred where passing an empty project list evaluated
> the worker count to 0. This crashed the multiprocessing pool initialization
> with a ValueError. Returning early was rejected as a fix because secondary
> side-effects (like state saves) within the function still needed to execute.
> Failing to adhere to this typically results in **ValueError / Process Pool
> Crash**.

**Trap 1: Directly using `min(target, len(items))` to determine pool size, which
breaks if the item list is unexpectedly empty.**

**Don't:**

```python
jobs = min(opt.jobs_network, len(projects_list))
```

**Do:**

```python
jobs = max(1, min(opt.jobs_network, len(projects_list)))
```

--------------------------------------------------------------------------------

#### T1-11: Safeguarding Object State Across Parallel Execution Boundaries

> **Rule:** Always transmit deeply serialized objects directly across parallel
> boundaries, or strictly reconstruct object relationships within the downstream
> worker.
>
> **What:** When offloading command execution to parallel processes, workers
> must receive properly serialized complex object data, not dissociated
> identifiers, unless the downstream API explicitly reconstructs the object
> state.
>
> **Applies To:** Parallel execution contexts (`ParallelContext`,
> `ExecuteInParallel`) within multi-project commands like `repo forall` and
> `repo upload`.
>
> **Why:** A refactoring attempt to optimize IPC by passing integer project
> indices instead of full project objects to parallel workers caused critical
> breakage. Worker processes subsequently attempted to access attributes (like
> `.manifest`) on integer types, leading to unhandled exceptions. Failing to
> adhere to this typically results in **AttributeError / Early Exit
> Regression**.

**Trap 1: Truncating object payloads to scalar indices during IPC context setup
without updating the receiver logic to rehydrate the objects.**

**Don't:**

```python
# Worker receives an integer index instead of a Project
manifests = {
    project.manifest.topdir: project.manifest
}
```

**Do:**

```python
# Worker receives fully serialized Project objects (or properly reconstructs them)
manifests = {
    project.manifest.topdir: project.manifest
}
```

--------------------------------------------------------------------------------

#### T1-12: Explicit Context Initialization for Multiprocessing Pools

> **Rule:** Must dictate shared states through an explicit `initializer`
> argument injected into the multiprocessing pool rather than implicitly relying
> on execution fork behavior.
>
> **What:** Shared parallel context must be managed using an explicit context
> manager and passed via `initializer` and `initargs` in `multiprocessing.Pool`,
> rather than relying on unvalidated class attributes or fork memory semantics.
>
> **Applies To:** Any command or module utilizing `multiprocessing.Pool` (e.g.,
> `ExecuteInParallel`).
>
> **Why:** Relying on `fork` memory semantics for sharing context works on some
> Linux systems but fails deterministically on environments (like macOS/Windows)
> where memory is not automatically shared or when the multiprocessing start
> method defaults to `spawn`. Failing to adhere to this typically results in
> **State Leakage / Uninitialized Context**.

**Trap 1: Assuming child workers inherit updated class variables inherently
without explicit initialization.**

**Don't:**

```python
# BAD: Implicit state sharing
cls.parallel_context = data
with multiprocessing.Pool(jobs) as pool:
    pool.imap_unordered(func, inputs)
```

**Do:**

```python
# GOOD: Explicit initializer passed to workers
with multiprocessing.Pool(
    jobs,
    initializer=cls._SetParallelContext,
    initargs=(cls._parallel_context,)
) as pool:
    pool.imap_unordered(func, inputs)
```

**Trap 2: A context manager directly yielding an internal dictionary, allowing
unvalidated and lingering usage.**

**Don't:**

```python
# BAD: Direct yield of state without lifecycle validation
@contextlib.contextmanager
def ParallelContext(cls):
    yield cls._parallel_context
```

**Do:**

```python
# GOOD: Lifecycle management and defensive assertions
@contextlib.contextmanager
def ParallelContext(cls):
    assert cls._parallel_context is None
    cls._parallel_context = {}
    try:
        yield
    finally:
        cls._parallel_context = None
```

--------------------------------------------------------------------------------

#### T1-13: Dynamic Task Chunk Sizing in Parallel Execution

> **Rule:** Always formulate the `chunksize` of mapping workers dynamically
> based on the dataset to job ratio to avoid workload serialization blocks.
>
> **What:** When utilizing `multiprocessing.Pool.imap_unordered`, the
> `chunksize` must be dynamically calculated based on the ratio of inputs to
> worker jobs, rather than statically hardcoded.
>
> **Applies To:** Parallel task dispatch mechanisms (`ExecuteInParallel`,
> synchronization loops).
>
> **Why:** Using a statically hardcoded chunk size (e.g., `WORKER_BATCH_SIZE =
> 32`) forced all tasks onto a single worker thread when the total number of
> projects in the manifest was fewer than 32, completely negating the benefit of
> parallelism for smaller workloads. Failing to adhere to this typically results
> in **Thread Serialization / Under-utilization**.

**Trap 1: Passing a hardcoded batch integer to the `chunksize` parameter.**

**Don't:**

```python
# BAD: Hardcoded chunksize leads to serialization for small input lists
submit(func, inputs, chunksize=WORKER_BATCH_SIZE)
```

**Do:**

```python
# GOOD: Dynamic chunking balances load across workers
calc_chunk = min(max(1, len(inputs) // jobs), WORKER_BATCH_SIZE)
submit(func, inputs, chunksize=calc_chunk)
```

**Exceptions:** When evaluating specifically within tests that forcefully
isolate to a single job execution (`jobs=1`).

--------------------------------------------------------------------------------

#### T1-14: Deferred Worktree Operations in Sync Local Half

> **Rule:** Must enqueue manifest copy and link actions into the synchronization
> buffer explicitly prior to issuing early return signals for up-to-date
> repositories.
>
> **What:** File link (`linkfile`) and copy (`copyfile`) directives must be
> scheduled using the synchronization buffer (`syncbuf.later1`) within the
> `Sync_LocalHalf` execution phase. They must not be bypassed if the repository
> exits its sync early due to being up-to-date.
>
> **Applies To:** Local synchronization logic of projects (`project.py` ->
> `Sync_LocalHalf`).
>
> **Why:** A bug existed where if a project had published commits in Gerrit
> (meaning its local state was merged), the sync process would return early and
> entirely skip applying the manifest's `linkfile` and `copyfile` operations,
> leading to missing or stale files in the developer's worktree. Failing to
> adhere to this typically results in **Worktree Desync / Missing Files**.

**Trap 1: Returning early from the sync phase without applying required file
operations.**

**Don't:**

```python
# BAD: Skipped file modifications when commits are published
if pub == head:
    return
```

**Do:**

```python
# GOOD: Schedule file operations via syncbuf before returning
if pub == head:
    syncbuf.later1(self, _doff, not verbose)
    return
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T3 | Subprocess Git Integration & Error Translation -
    *Standardizes Git command stream capturing and exception typing, enabling
    reliable lock contention detection.*
*   **Downstream:** T2 | Filesystem Atomicity & Worktree Layout - *Relies on
    parallel execution guard clauses to ensure worktrees exist before checkout
    operations are dispatched.*
*   **Downstream:** T6 | CLI Argument Parsing & UX Consistency - *Requires
    buffered standard outputs and structured logger directives from parallel
    tasks to maintain coherent terminal formatting.*

## Chapter: Filesystem Atomicity & Worktree Layout

**Context:** This domain governs the deterministic creation, migration, and
cleanup of internal repository structures and Git worktrees. It relies on
ephemeral temporary directories, atomic rename operations, and robust error
recovery to prevent corrupted states during unexpected interruptions.

### Summary

| Rule ID   | Principle / Constraint        | Priority | Primary Symptom /     |
:           :                               :          : Trap                  :
| :-------- | :---------------------------- | :------- | :-------------------- |
| **T2-01** | Unique Subproject Keys in     | High     | Using the git         |
:           : Worktree Environments         :          : directory or          :
:           :                               :          : repository name as a  :
:           :                               :          : unique hash key for   :
:           :                               :          : deduplicating project :
:           :                               :          : objects.              :
| **T2-02** | Non-Destructive Bottom-Up     | High     | Using aggressive      |
:           : Directory Pruning             :          : recursive delete      :
:           :                               :          : calls to wipe an old  :
:           :                               :          : link destination      :
:           :                               :          : without verifying its :
:           :                               :          : internal contents.    :
| **T2-03** | Guaranteed Cleanup of         | Critical | Running destructive   |
:           : Temporary Git Artifacts       :          : or state-modifying    :
:           :                               :          : operations without    :
:           :                               :          : wrapping the cleanup  :
:           :                               :          : routine in a          :
:           :                               :          : `finally` block.      :
| **T2-04** | Atomic Directory              | High     | Initializing a        |
:           : Initialization via Temporary  :          : complex directory     :
:           : Worktrees                     :          : structure directly at :
:           :                               :          : its final target path :
:           :                               :          : without atomicity     :
:           :                               :          : guarantees.           :
| **T2-05** | Pathlib Adoption over os.path | Medium   | Relying on heavily    |
:           :                               :          : nested string-based   :
:           :                               :          : os.path               :
:           :                               :          : constructions.        :
| **T2-06** | Atomic Directory              | Critical | Creating and mutating |
:           : Initialization via Temporary  :          : a system directory at :
:           : Renames                       :          : its final, visible    :
:           :                               :          : destination.          :
| **T2-07** | Encapsulation of Transient    | High     | Swapping out instance |
:           : Configuration State           :          : configuration         :
:           :                               :          : variables back and    :
:           :                               :          : forth during setup.   :
| **T2-08** | Explicit Temporary Resource   | Critical | Keeping a stale       |
:           : Ownership and Release         :          : variable reference to :
:           :                               :          : a temporary directory :
:           :                               :          : after it has been     :
:           :                               :          : renamed, allowing a   :
:           :                               :          : deferred cleanup      :
:           :                               :          : routine to operate on :
:           :                               :          : an unowned path.      :
| **T2-09** | Configuration Object          | High     | Using a temporary     |
:           : Invalidation Post-Rename      :          : config object to set  :
:           :                               :          : flags after the       :
:           :                               :          : underlying directory  :
:           :                               :          : has been renamed.     :
| **T2-10** | Granular Safety Checks for    | Critical | Deleting a shared     |
:           : Destructive Worktree          :          : object directory      :
:           : Operations                    :          : immediately upon      :
:           :                               :          : deleting a single     :
:           :                               :          : project that uses it. :
| **T2-11** | Explicit Warnings for Legacy  | Critical | Silently executing a  |
:           : Garbage Collection Fallbacks  :          : legacy fallback for   :
:           :                               :          : repository safety     :
:           :                               :          : configurations        :
:           :                               :          : without informing the :
:           :                               :          : user of the potential :
:           :                               :          : unreliability.        :
| **T2-12** | Atomic Commits for Filesystem | High     | Bundling filesystem   |
:           : Restructuring                 :          : path migrations,      :
:           :                               :          : structural            :
:           :                               :          : re-designs, and       :
:           :                               :          : initialization logic  :
:           :                               :          : changes into a single :
:           :                               :          : Pull                  :
:           :                               :          : Request/Patchset.     :
| **T2-13** | Precise Symlink Target        | High     | Using a generic       |
:           : Replacement During Submodule  :          : string `.replace()`   :
:           : Migration                     :          : to update a portion   :
:           :                               :          : of a file path.       :
| **T2-14** | Isolating Filesystem          | High     | Executing internal    |
:           : Migrations from Network-Only  :          : directory migrations  :
:           : Operations                    :          : globally prior to     :
:           :                               :          : downloading network   :
:           :                               :          : changes.              :
| **T2-15** | Idempotent Cross-Platform     | High     | Relying on standard   |
:           : File Cleanup                  :          : library file removal  :
:           :                               :          : and failing to handle :
:           :                               :          : the scenario where    :
:           :                               :          : the file no longer    :
:           :                               :          : exists.               :
| **T2-16** | Self-Healing Binary JSON      | High     | Opening JSON state    |
:           : Deserialization               :          : files in text mode    :
:           :                               :          : without validating    :
:           :                               :          : structure, allowing   :
:           :                               :          : exceptions to bubble  :
:           :                               :          : up and break the CLI. :
| **T2-17** | Atomic File Writes for        | Critical | Using the standard    |
:           : Repository Configurations     :          : python `open()`       :
:           :                               :          : context manager and   :
:           :                               :          : `print()` to mutate   :
:           :                               :          : core git directories. :
| **T2-18** | File Descriptor Lock Scope    | Medium   | Processing strings    |
:           : Minimization                  :          : and building          :
:           :                               :          : directory paths       :
:           :                               :          : inside the file       :
:           :                               :          : reading scope.        :
| **T2-19** | Two-Phase Atomic Deletion for | High     | Directly triggering   |
:           : Worktrees                     :          : `rmtree` on a live    :
:           :                               :          : repository path.      :
| **T2-20** | Conditional Absolute Path     | High     | Blindly deleting and  |
:           : Resolution for Git Worktrees  :          : rewriting the         :
:           :                               :          : `gitdir` file using   :
:           :                               :          : `os.path.relpath`     :
:           :                               :          : without checking if   :
:           :                               :          : the source path is    :
:           :                               :          : absolute first.       :
| **T2-21** | Independent Manifest          | High     | Defaulting to a       |
:           : Repository Shallow Cloning    :          : shallow clone for     :
:           :                               :          : configuration         :
:           :                               :          : repositories, causing :
:           :                               :          : subsequent            :
:           :                               :          : initialization/branch :
:           :                               :          : switching commands to :
:           :                               :          : fail due to missing   :
:           :                               :          : objects.              :

--------------------------------------------------------------------------------

### Rules

#### T2-01: Unique Subproject Keys in Worktree Environments

> **Rule:** Always use repository-relative paths instead of git directory names
> as unique deduplication keys to prevent collisions in worktree environments.
>
> **What:** Repository-relative paths must be used instead of git directory
> names as unique deduplication keys to prevent collisions in environments
> utilizing git worktrees.
>
> **Applies To:** Subproject iteration and deduplication logic, primarily within
> `command.py` or project discovery utilities.
>
> **Why:** When tracking derived subprojects, the system originally used
> `gitdir` as a unique identifier. In git worktree setups, multiple distinct
> project instances can share the same underlying `gitdir`, leading to silent
> data collisions and missed projects during sync operations. Failing to adhere
> to this typically results in **Data Collision / Omission**.

**Trap 1: Using the git directory or repository name as a unique hash key for
deduplicating project objects.**

**Don't:**

```python
derived_projects.update(
    (p.gitdir, p) for p in project.GetDerivedSubprojects()
)
```

**Do:**

```python
derived_projects.update(
    (p.RelPath(local=False), p) for p in project.GetDerivedSubprojects()
)
```

#### T2-02: Non-Destructive Bottom-Up Directory Pruning

> **Rule:** Always utilize non-destructive, bottom-up directory iteration that
> exclusively targets empty directories and symlinks during legacy path cleanup.
>
> **What:** Legacy path cleanup must utilize non-destructive, bottom-up
> directory iteration that specifically targets empty directories and symlinks,
> avoiding recursive tree destruction.
>
> **Applies To:** Workspace migration, obsolete symlink cleanup, and
> `platform_utils` file deletion wrappers.
>
> **Why:** When a subproject's destination directory changed, the
> synchronization tool utilized aggressive recursive deletion (`rmtree`) to
> remove the previous location. This routinely endangered untracked developer
> code or extraneous files housed inside the obsolete tree. Failing to adhere to
> this typically results in **Accidental Data Deletion**.

**Trap 1: Using aggressive recursive delete calls to wipe an old link
destination without verifying its internal contents.**

**Don't:**

```python
if platform_utils.isdir(absDest):
    platform_utils.rmtree(absDest)
```

**Do:**

```python
# Use a safe helper that only removes empty dirs/symlinks bottom-up
platform_utils.removedirs(absDest)
```

**Trap 2: Attempting directory deletion without explicitly pruning stale
manifest files first.**

**Don't:**

```python
platform_utils.removedirs(need_remove_path)
# Misses files entirely as removedirs stops at regular files
```

**Do:**

```python
if os.path.isfile(need_remove_path) or os.path.islink(need_remove_path):
    platform_utils.remove(need_remove_path)
platform_utils.removedirs(os.path.dirname(need_remove_path))
```

**Exceptions:** Explicitly defined cases where a directory is formally tracked
and deleted from the manifest metadata, explicitly commanding removal.

#### T2-03: Guaranteed Cleanup of Temporary Git Artifacts

> **Rule:** Must wrap any operation mutating the local `.git` repository with
> temporary states inside a `try/finally` block to guarantee restoration.
>
> **What:** Operations mutating the local `.git` repository with temporary
> states (e.g., tracking alt refs during fetch) must wrap the operation in a
> `try/finally` block to guarantee state restoration.
>
> **Applies To:** Subprocess network operations and filesystem interactions
> affecting the `.git` database.
>
> **Why:** If a network operation threw an exception (like a `GitAuthError`
> prompting for credentials), the cleanup logic was bypassed. This left orphaned
> references in the object database and corrupted future repository syncs.
> Failing to adhere to this typically results in **Stale Repository State**.

**Trap 1: Running destructive or state-modifying operations without wrapping the
cleanup routine in a `finally` block.**

**Don't:**

```python
setup_temporary_refs()
run_git_fetch() # Might throw GitAuthError
cleanup_temporary_refs()
```

**Do:**

```python
setup_temporary_refs()
try:
    run_git_fetch()
finally:
    cleanup_temporary_refs()
```

#### T2-04: Atomic Directory Initialization via Temporary Worktrees

> **Rule:** Always perform directory initialization via temporary directories
> and an atomic rename to prevent fragmented repository states.
>
> **What:** Directory initialization processes must use temporary directories
> and atomic renames to prevent partial or corrupted states upon unexpected
> interruption.
>
> **Applies To:** Filesystem operations involving git repository setup,
> specifically superproject initialization and dot-git dir creation.
>
> **Why:** Historically, initializing git directories directly in their final
> path left behind broken, partially-initialized structures if the user or
> system interrupted the process. This caused subsequent workflow executions to
> fail permanently. Failing to adhere to this typically results in **Corrupt
> State / Initialization Failure**.

**Trap 1: Initializing a complex directory structure directly at its final
target path without atomicity guarantees.**

**Don't:**

```python
os.makedirs(final_git_dir, exist_ok=True)
subprocess.run(['git', 'init', final_git_dir])
```

**Do:**

```python
temp_dir = tempfile.mkdtemp(dir=target_base)
try:
    subprocess.run(['git', 'init', temp_dir])
    platform_utils.rename(temp_dir, final_git_dir)
finally:
    platform_utils.rmtree(temp_dir, ignore_errors=True)
```

#### T2-05: Pathlib Adoption over os.path

> **Rule:** Avoid legacy `os.path` APIs; prefer modern `pathlib.Path` structures
> for traversing, joining, and creating files.
>
> **What:** Use modern Python `pathlib.Path` paradigms for traversing, joining,
> and creating files instead of the legacy `os.path` APIs.
>
> **Applies To:** Filesystem and worktree directory manipulation.
>
> **Why:** Chaining `os.path.join` and calling `os.mkdir` repeatedly bloated the
> codebase, was less readable, and invited platform separator path bugs. Failing
> to adhere to this typically results in **Pathing Errors / High Complexity**.

**Trap 1: Relying on heavily nested string-based os.path constructions.**

**Don't:**

```python
manifest_dir = os.path.join(self.repodir, 'manifests')
os.mkdir(manifest_dir)
with open(os.path.join(manifest_dir, 'config'), 'w') as fp:
    fp.write(data)
```

**Do:**

```python
manifest_dir = self.repodir / 'manifests'
manifest_dir.mkdir(parents=True, exist_ok=True)
(manifest_dir / 'config').write_text(data)
```

**Exceptions:** Legacy modules pending modernization where intermingling
`os.path` strings and `Path` objects would break typing contracts.

#### T2-06: Atomic Directory Initialization via Temporary Renames

> **Rule:** Never construct complex internal `.git` directories in-situ; execute
> initialization inside an ephemeral directory and atomically rename it upon
> completion.
>
> **What:** Complex directory structures (like internal `.git` directories) must
> be constructed inside an ephemeral temporary directory on the same filesystem
> volume, and only moved to their final path via an atomic rename once fully
> validated.
>
> **Applies To:** Filesystem creation (`os.makedirs`) and repository
> initialization (`_InitGitDir`).
>
> **Why:** Interrupted or failed operations left partially initialized `.git`
> directories in-situ. Follow-up operations encountered corrupt directory trees,
> which the legacy recovery logic could not reliably clean up. Failing to adhere
> to this typically results in **Corrupt Repository State**.

**Trap 1: Creating and mutating a system directory at its final, visible
destination.**

**Don't:**

```python
os.makedirs(self.gitdir)
self._ReferenceGitDir(self.objdir, self.gitdir)
```

**Do:**

```python
tmp_gitdir = create_tmp_dir(os.path.dirname(self.gitdir))
os.makedirs(tmp_gitdir)
self._ReferenceGitDir(self.objdir, tmp_gitdir)
platform_utils.rename(tmp_gitdir, self.gitdir)
```

#### T2-07: Encapsulation of Transient Configuration State

> **Rule:** Never reassign class-level instance attributes to intermediate paths
> during object setup; use local variables for temporary state tracking.
>
> **What:** Never temporarily reassign class-level instance attributes (e.g.,
> `self.config`) to point to intermediate or ephemeral paths. Use local
> variables for temporary objects during setup, assigning the final result to
> the class instance only upon success.
>
> **Applies To:** Object initialization workflows within `project.py`.
>
> **Why:** During atomic `.git` directory initialization, `self.config` was
> temporarily overwritten to point to a temporary working directory. If the
> operation crashed, the object was left in an invalid state, pointing to a
> deleted transient path. Failing to adhere to this typically results in
> **Corrupt Instance State**.

**Trap 1: Swapping out instance configuration variables back and forth during
setup.**

**Don't:**

```python
self.config = GitConfig.ForRepository(gitdir=tmp_gitdir)
# initialization steps
platform_utils.rename(tmp_gitdir, self.gitdir)
self.config = GitConfig.ForRepository(gitdir=self.gitdir)
```

**Do:**

```python
tmp_config = GitConfig.ForRepository(gitdir=tmp_gitdir)
# apply setup using tmp_config
platform_utils.rename(tmp_gitdir, self.gitdir)
self.config = GitConfig.ForRepository(gitdir=self.gitdir)
```

#### T2-08: Explicit Temporary Resource Ownership and Release

> **Rule:** Always nullify references to a temporary directory immediately after
> successfully renaming it to its permanent destination.
>
> **What:** When executing atomic directory initializations via temporary paths,
> the reference to the temporary directory must be explicitly nullified
> immediately after successfully renaming it to its final destination.
>
> **Applies To:** Filesystem operations, specifically in `project.py` atomic Git
> directory initializations (`_InitGitDir`).
>
> **Why:** If a temporary directory reference was maintained after being
> atomic-renamed, the subsequent error-handling or `finally` cleanup block could
> mistakenly delete the directory. In parallel environments, another concurrent
> job could validly create a new temporary directory at that exact freed path,
> causing the current process to inadvertently nuke an active resource belonging
> to another job. Failing to adhere to this typically results in **Data Loss /
> Race Condition**.

**Trap 1: Keeping a stale variable reference to a temporary directory after it
has been renamed, allowing a deferred cleanup routine to operate on an unowned
path.**

**Don't:**

```python
try:
    tmp_gitdir = tempfile.mkdtemp()
    # ... initialize ...
    platform_utils.rename(tmp_gitdir, self.gitdir)
    # BAD: tmp_gitdir still holds the path string
finally:
    if tmp_gitdir and os.path.exists(tmp_gitdir):
        platform_utils.rmtree(tmp_gitdir) # Risk of race condition
```

**Do:**

```python
try:
    tmp_gitdir = tempfile.mkdtemp()
    # ... initialize ...
    platform_utils.rename(tmp_gitdir, self.gitdir)
    tmp_gitdir = None  # GOOD: explicitly release ownership of the path
finally:
    if tmp_gitdir and os.path.exists(tmp_gitdir):
        platform_utils.rmtree(tmp_gitdir)
```

#### T2-09: Configuration Object Invalidation Post-Rename

> **Rule:** Must discard intermediate configuration instances bound to temporary
> paths once the underlying directory is atomic-renamed.
>
> **What:** Configuration instances (e.g., `GitConfig`) bound to a temporary
> filesystem path must be abandoned after the path is atomic-renamed. A new
> instance tracking the permanent directory path must be used for subsequent
> settings.
>
> **Applies To:** Git config lifecycle management across atomic filesystem
> boundary events.
>
> **Why:** Applying configuration changes like `gc.pruneExpire` using an object
> instantiated against a temporary path resulted in IO errors or lost state if
> the operations occurred after the directory was moved to its final, permanent
> location. Failing to adhere to this typically results in **Lost Configuration
> / IO Error**.

**Trap 1: Using a temporary config object to set flags after the underlying
directory has been renamed.**

**Don't:**

```python
curr_config = GitConfig.ForRepository(gitdir=tmp_gitdir)
platform_utils.rename(tmp_gitdir, self.gitdir)
curr_config.SetString("gc.pruneExpire", "never")  # BAD: Path no longer valid
```

**Do:**

```python
curr_config = GitConfig.ForRepository(gitdir=tmp_gitdir)
platform_utils.rename(tmp_gitdir, self.gitdir)
self.config.SetString("gc.pruneExpire", "never")  # GOOD: Using permanent config tracking self.gitdir
```

#### T2-10: Granular Safety Checks for Destructive Worktree Operations

> **Rule:** Must evaluate explicit dependency subsets and prompt overrides
> before wiping shared object directories.
>
> **What:** Destructive operations (like wiping directories) must separately
> evaluate and prompt overrides for distinct risk categories (uncommitted local
> changes vs. shared object directories), and only delete a shared object
> directory if all dependent projects are successfully wiped.
>
> **Applies To:** Commands modifying or deleting project directories and
> `.repo/project-objects`.
>
> **Why:** Deleting shared `.repo` state indiscriminately could leave other
> referencing projects broken if they relied on the same object directory,
> requiring strict subset checks before `rmtree` execution. Failing to adhere to
> this typically results in **Repository Corruption / Data Loss**.

**Trap 1: Deleting a shared object directory immediately upon deleting a single
project that uses it.**

**Don't:**

```python
# BAD: Deletes shared objdir, breaking other projects
project.DeleteWorktree(force=True)
if os.path.exists(project.objdir):
    platform_utils.rmtree(project.objdir)
```

**Do:**

```python
# GOOD: Verify all users of the objdir are deleted first
project.DeleteWorktree(force=True)
successful_wipes.add(project.relpath)

# Later...
if users.issubset(successful_wipes):
    platform_utils.rmtree(objdir)
```

#### T2-11: Explicit Warnings for Legacy Garbage Collection Fallbacks

> **Rule:** Must emit a visible warning to `sys.stderr` when disabling Git
> garbage collection via legacy fallback configurations.
>
> **What:** When disabling Git garbage collection for shared network
> repositories using legacy mechanisms (`gc.pruneExpire=never`), the tooling
> must emit a visible `sys.stderr` warning due to the unreliability of older Git
> clients.
>
> **Applies To:** Git configuration manipulation and local filesystem management
> (`_GCProjects`).
>
> **Why:** Older Git clients (pre 2.7.0) do not natively support the
> `extensions.preciousObjects` flag. To prevent garbage collection from
> corrupting shared objects, `repo` forces `gc.pruneExpire` to `never`. Because
> this is imperfect, it can lead to unreliable repository states, requiring
> explicit user notification. Failing to adhere to this typically results in
> **Data Loss / Corruption**.

**Trap 1: Silently executing a legacy fallback for repository safety
configurations without informing the user of the potential unreliability.**

**Don't:**

```python
# BAD: Silent fallback to legacy GC directive
if git_require((2, 7, 0)):
    project.config.SetString('extensions.preciousObjects', 'true')
else:
    project.config.SetString('gc.pruneExpire', 'never')
```

**Do:**

```python
# GOOD: Alerting the user to the legacy system risk
if git_require((2, 7, 0)):
    project.config.SetString('extensions.preciousObjects', 'true')
else:
    print('WARNING: shared projects are unreliable when using old versions of git...', file=sys.stderr)
    project.config.SetString('gc.pruneExpire', 'never')
```

#### T2-12: Atomic Commits for Filesystem Restructuring

> **Rule:** Always strictly isolate structural filesystem modifications and
> migrations into single atomic commits to maintain bisectability.
>
> **What:** Refactoring critical filesystem paths (like migrating internal
> `.git` submodule structures) must be strictly isolated into atomic commits to
> preserve bisectability.
>
> **Applies To:** Worktree layout updates, `.git` metadata migrations, and
> submodule structure changes.
>
> **Why:** A monolithic commit attempted to restructure how submodules were
> stored (from `subprojects/` to `modules/`), update initialization logic, and
> alter fetching. This density made code review difficult and created a high
> risk of regressions that would be impossible to bisect cleanly. Failing to
> adhere to this typically results in **Unbisectable Regressions**.

**Trap 1: Bundling filesystem path migrations, structural re-designs, and
initialization logic changes into a single Pull Request/Patchset.**

**Don't:**

*   Submit 1 patchset: [Refactor] Move submodules to modules/, update git config
    flags, and modify sync --init behaviors.

**Do:**

*   Submit 3 sequential patchsets: 1) Isolate init flag changes. 2) Migrate
    filesystem directories from `subprojects` to `modules`. 3) Enable Git
    recurse submodules integration.

#### T2-13: Precise Symlink Target Replacement During Submodule Migration

> **Rule:** Always use explicit path prefixes instead of generic substring
> replacements to update symlink targets during legacy layout migrations.
>
> **What:** Symlink updates during filesystem layout migrations must use exact
> path prefixes rather than global substring replacements to update relative
> targets safely.
>
> **Applies To:** Repository migration logic (`project.py`); specifically
> `_MigrateSubprojectLinks` or similar symlink target modifications.
>
> **Why:** During the migration of legacy submodule directories, using generic
> string replacement (`target.replace`) on symlink paths unintentionally
> corrupted paths if a user's directory structure legitimately contained the
> target string (e.g., `subproject-objects`) in a higher-level parent directory
> name. Failing to adhere to this typically results in **Broken Symlinks /
> Corruption**.

**Trap 1: Using a generic string `.replace()` to update a portion of a file
path.**

**Don't:**

```python
if "subproject-objects" in target:
    new_target = target.replace(
        "subproject-objects", "module-objects"
    )
```

**Do:**

```python
if target.startswith("../../subproject-objects/"):
    new_target = target.replace(
        "../../subproject-objects/", "../../module-objects/"
    )
```

#### T2-14: Isolating Filesystem Migrations from Network-Only Operations

> **Rule:** Never execute internal repository layout migrations as part of
> network fetch iterations.
>
> **What:** Internal repository layout migrations must only execute during local
> worktree initialization phases, never during network fetch iterations.
>
> **Applies To:** Repository sync operations (`subcmds/sync.py`) and worktree
> checkout logic (`project.py`).
>
> **Why:** Binding irreversible filesystem layout migrations to the `sync`
> command's network-fetch loop risked partially migrating the repository if the
> process was interrupted, or if a user requested a network-only sync, leaving
> the local workspace out of sync with internal references. Failing to adhere to
> this typically results in **Repository Corruption**.

**Trap 1: Executing internal directory migrations globally prior to downloading
network changes.**

**Don't:**

```python
# In subcmds/sync.py during network fetching
for p in all_projects:
    p._MigrateOldSubprojectDirs()
    # ... fetch logic
```

**Do:**

```python
# Inside project.py during _InitWorkTree() or checkout
def _InitWorkTree(self):
    self._MigrateOldSubmoduleDirs()
    # ... symlink creation and checkout logic
```

#### T2-15: Idempotent Cross-Platform File Cleanup

> **Rule:** Must employ `platform_utils.remove()` for file cleanup to safely
> absorb OS access violations and gracefully swallow `ENOENT`.
>
> **What:** File cleanup operations must use the internal
> `platform_utils.remove()` instead of the standard `os.remove()` to handle
> Windows-specific OS limitations. Furthermore, cleanup must be idempotent by
> explicitly catching and swallowing `errno.ENOENT` errors.
>
> **Applies To:** Local worktree operations, internal state file cleanup (e.g.,
> deleting obsolete copyfiles or linkfiles).
>
> **Why:** Sync operations would abruptly crash on Windows due to unhandled
> `EACCES` issues on read-only files/symlinks with native `os.remove()`.
> Furthermore, if a tracking file was already deleted manually by the user or a
> prior interrupted run, unhandled `ENOENT` exceptions would needlessly fail the
> operation. Failing to adhere to this typically results in **Crash on
> Missing/Locked File**.

**Trap 1: Relying on standard library file removal and failing to handle the
scenario where the file no longer exists.**

**Don't:**

```python
if path:
  try:
    os.remove(path)
  except OSError as error:
    print(f'error: remove {path} failed.')
    return 1
```

**Do:**

```python
try:
  platform_utils.remove(path)
except OSError as e:
  if e.errno == errno.ENOENT:
    # File does not exist, safe to ignore
    pass
```

#### T2-16: Self-Healing Binary JSON Deserialization

> **Rule:** Always read internal JSON state files in binary mode (`rb`) and
> implement explicit error catching to seamlessly discard corrupted states.
>
> **What:** Internal JSON tracking files must be read in binary mode (`rb`) to
> allow the JSON parser to detect text encoding safely. Additionally, parsing
> must be wrapped in a `try/except` block to automatically delete the file and
> recover if the JSON is corrupted.
>
> **Applies To:** Manifest metadata tracking files, internal cache parsing
> (e.g., `copy-link-files.json`).
>
> **Why:** When the operating system's default text encoding did not match the
> file's encoding, a `UnicodeDecodeError` could occur. Additionally, if the JSON
> state file was corrupted (e.g., due to an abrupt power loss or killed
> process), `repo sync` would permanently fail until the user manually
> discovered and deleted the corrupted state file. Failing to adhere to this
> typically results in **Corrupt State Deadlock**.

**Trap 1: Opening JSON state files in text mode without validating structure,
allowing exceptions to bubble up and break the CLI.**

**Don't:**

```python
with open(copylinkfiles_path, 'r') as fd:
  old_copylinkfiles_path = json.load(fd)
```

**Do:**

```python
with open(copylinkfiles_path, 'rb') as fp:
  try:
    old_copylinkfiles_path = json.load(fp)
  except:
    print('error: %s is not a json formatted file.' % copylinkfiles_path, file=sys.stderr)
    platform_utils.remove(copylinkfiles_path)
    return False
```

#### T2-17: Atomic File Writes for Repository Configurations

> **Rule:** Must utilize atomic file writes rather than standard contexts when
> generating core `.git` configuration files.
>
> **What:** System state modifications, specifically writing the `.git` pointer
> files for submodules, must be performed using an atomic write pattern (e.g.,
> writing to a lockfile and renaming) rather than standard file descriptors.
>
> **Applies To:** All file I/O operations directly modifying `.git` contents,
> worktrees, or manifest definitions.
>
> **Why:** Using standard `open()` and writing to `.git` files directly leaves
> the repository vulnerable to corruption if the process is interrupted (e.g.,
> via Ctrl+C or SIGTERM) during the write loop, resulting in a partially written
> pointer. Failing to adhere to this typically results in **Corrupted Git
> Worktree**.

**Trap 1: Using the standard python `open()` context manager and `print()` to
mutate core git directories.**

**Don't:**

```python
with open(dotgit, "w") as fp:
    print(f"gitdir: {rel_path}", file=fp)
```

**Do:**

```python
_lwrite(dotgit, f"gitdir: {rel_path}\n")
```

#### T2-18: File Descriptor Lock Scope Minimization

> **Rule:** Minimize file descriptor lock retention by executing string and
> state logic outside of standard reading contexts.
>
> **What:** Data processing and variable manipulation must be extracted out of
> file descriptor lock contexts (`with open(...)`) to minimize resource
> retention.
>
> **Applies To:** Any block parsing local text or configuration files.
>
> **Why:** Holding file descriptors open while executing CPU-bound string
> manipulations increases lock contention probability and expands the attack
> surface for race conditions when multiple concurrent processes read/write
> repository states. Failing to adhere to this typically results in **Resource
> Lock Contention**.

**Trap 1: Processing strings and building directory paths inside the file
reading scope.**

**Don't:**

```python
with open(dotgit) as fp:
    setting = fp.read()
    gitdir = setting.split(":")[1].strip()
    dotgit_path = os.path.normpath(os.path.join(self.worktree, gitdir))
```

**Do:**

```python
with open(dotgit) as fp:
    setting = fp.read()

# Lock released, safe to process
gitdir = setting.split(":")[1].strip()
dotgit_path = os.path.normpath(os.path.join(self.worktree, gitdir))
```

#### T2-19: Two-Phase Atomic Deletion for Worktrees

> **Rule:** Must enact permanent `.git` and worktree removal via a two-phase
> destruction pattern utilizing a temporary trash path.
>
> **What:** When permanently removing a `.git` directory or worktree, the system
> must first perform an atomic rename to a temporary trash path before
> initiating the recursive deletion.
>
> **Applies To:** Garbage collection (`gc.py`), worktree cleanup, and submodule
> removal logic.
>
> **Why:** Recursive deletion is not instantaneous. If a user forcefully
> interrupted (Ctrl+C) the `rmtree` operation, the directory was left in a
> 'wedged' (partially deleted but still registered) state, permanently breaking
> future syncs for that repository. Failing to adhere to this typically results
> in **Wedged / Orphaned Worktree**.

**Trap 1: Directly triggering `rmtree` on a live repository path.**

**Don't:**

```python
for path in to_delete:
    platform_utils.rmtree(path)
```

**Do:**

```python
for path in to_delete:
    temp_path = rename_to_trash(path)
    platform_utils.rmtree(temp_path)
```

#### T2-20: Conditional Absolute Path Resolution for Git Worktrees

> **Rule:** Always independently verify if a tracked worktree path is absolute
> before initiating internal path recreation procedures.
>
> **What:** Updates to `.git` directory reference files (e.g., `gitdir:`) must
> verify whether the stored worktree path is absolute before attempting to
> recreate it as a relative path to avoid path corruption and permissions
> errors.
>
> **Applies To:** Internal Git directory layout management, specifically
> cross-platform Git worktree initialization (`project.py`).
>
> **Why:** On certain platforms like Windows, modifying the internal `dotgit`
> file in situ fails due to file permissions. Code was added to delete and
> recreate the file using relative paths. However, depending on the Git version,
> the initial path could already be relative, making conversion unsafe without
> an `isabs()` check. Failing to adhere to this typically results in
> **Permission Denied / Path Corruption**.

**Trap 1: Blindly deleting and rewriting the `gitdir` file using
`os.path.relpath` without checking if the source path is absolute first.**

**Don't:**

```python
platform_utils.remove(dotgit)
with open(dotgit, "w", newline="\n") as fp:
    print("gitdir:", os.path.relpath(git_worktree_path, self.worktree), file=fp)
```

**Do:**

```python
if os.path.isabs(git_worktree_path):
    platform_utils.remove(dotgit)
    with open(dotgit, "w", newline="\n") as fp:
        print("gitdir:", os.path.relpath(git_worktree_path, self.worktree), file=fp)
```

#### T2-21: Independent Manifest Repository Shallow Cloning

> **Rule:** Never propagate the primary manifest `--depth` flag to govern the
> core manifest repository's clone boundaries.
>
> **What:** The depth configuration for cloning the central manifest repository
> must be explicitly decoupled from the depth configuration applied to the child
> projects it governs, and its default must not regress existing multi-stage
> init workflows.
>
> **Applies To:** Repo initialization commands (`repo init`, `subcmds/init.py`).
>
> **Why:** Using the global `--depth` flag inadvertently forced shallow clones
> on all child projects. Introducing a dedicated `--manifest-depth` option fixed
> this, but defaulting it to 1 caused a regression during 'double repo init'
> workflows (where subsequent checkouts failed against truncated manifest
> histories). Failing to adhere to this typically results in **Workflow
> Regression / History Truncation**.

**Trap 1: Defaulting to a shallow clone for configuration repositories, causing
subsequent initialization/branch switching commands to fail due to missing
objects.**

**Don't:**

```python
group.add_option('--manifest-depth', type='int', default=1, metavar='DEPTH',
                 help='create a shallow clone of the manifest repo')
```

**Do:**

```python
group.add_option('--manifest-depth', type='int', default=0, metavar='DEPTH',
                 help='create a shallow clone of the manifest repo')
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T3 | Subprocess Git Integration & Error Translation - *Network
    operations and git process invocations require safe staging paths and
    catchable exceptions to trigger filesystem cleanups.*
*   **Downstream:** T1 | Concurrent Synchronization & IPC - *Parallel checkout
    operations depend heavily on atomic path modifications and lock-free
    directory states to prevent race conditions.*
*   **Downstream:** T4 | Manifest Object Model & Deduplication - *Filesystem
    migrations and subproject tree building directly parse and reflect
    canonicalized XML manifest declarations.*

## Chapter: Subprocess Git Integration & Error Translation

**Context:** This chapter defines the constraints for wrapping, executing, and
translating standard Git subprocesses within the Repo tooling ecosystem. It
mandates the use of centralized command abstractions, strict version gating, and
deterministic stream handling to guarantee reliable repository state management
and actionable error reporting.

### Summary

| Rule ID   | Principle / Constraint    | Priority | Primary Symptom / Trap    |
| :-------- | :------------------------ | :------- | :------------------------ |
| **T3-01** | Unborn Branch Resolution  | High     | Catching a `rev-parse`    |
:           : via Symbolic-Ref          :          : GitError and immediately  :
:           :                           :          : falling back to manual    :
:           :                           :          : file system reads or      :
:           :                           :          : emitting warnings.        :
| **T3-02** | Centralized GitCommand    | Medium   | Wrapping `subprocess.run` |
:           : Abstraction Usage         :          : manually inside a class   :
:           :                           :          : to invoke Git.            :
| **T3-03** | NUL-Byte Delimiters for   | High     | Formatting git fields     |
:           : Git Output Parsing        :          : with tabs and defending   :
:           :                           :          : against length            :
:           :                           :          : variations.               :
| **T3-04** | Subprocess Execution      | Medium   | Stringifying Path         |
:           : Context and Native Path   :          : objects, using            :
:           : Passing                   :          : Git-specific directory    :
:           :                           :          : shifts, and suppressing   :
:           :                           :          : piped output.             :
| **T3-05** | Runtime Git Version       | High     | Invoking a modern git CLI |
:           : Constraints for Promisor  :          : flag without ensuring     :
:           : Packs                     :          : compatibility first.      :
| **T3-06** | Centralized Dependency    | Medium   | Catching missing binary   |
:           : Availability Caching      :          : exceptions to terminate   :
:           :                           :          : the process instead of    :
:           :                           :          : returning control to the  :
:           :                           :          : caller.                   :
| **T3-07** | Subprocess Return Code    | High     | Calling a non-existent    |
:           : Validation                :          : subprocess execution      :
:           :                           :          : method on an already      :
:           :                           :          : completed process object. :
| **T3-08** | Strict Git Version        | High     | Injecting convenient,     |
:           : Compatibility             :          : modern CLI flags into     :
:           :                           :          : subprocess wrappers.      :
| **T3-09** | Rebase Override for       | High     | Throwing a                |
:           : Published Local Branches  :          : `LocalSyncFail` when an   :
:           :                           :          : upstream gain exists,     :
:           :                           :          : completely ignoring the   :
:           :                           :          : `force_rebase` argument.  :
| **T3-10** | SSO Authentication        | High     | Treating all exit code    |
:           : Failure Translation       :          : 128 errors equally        :
:           :                           :          : without sniffing stdout   :
:           :                           :          : for authentication prompt :
:           :                           :          : aborts.                   :
| **T3-11** | Direct Read Fallback for  | High     | Raising a fatal internal  |
:           : Unborn Git HEAD           :          : exception immediately     :
:           :                           :          : upon a `GitError` when    :
:           :                           :          : checking for the HEAD     :
:           :                           :          : reference.                :
| **T3-12** | Safe Git Subprocess       | Critical | Assuming subprocess       |
:           : Output Handling           :          : success and attempting to :
:           :                           :          : return an output variable :
:           :                           :          : that hasn't been          :
:           :                           :          : initialized.              :
| **T3-13** | Shallow Clone SHA-1 Fetch | Critical | Assuming a fetch of an    |
:           : Fallback                  :          : arbitrary SHA-1 will      :
:           :                           :          : unconditionally succeed   :
:           :                           :          : if `--depth` is used.     :
| **T3-14** | Validating Gerrit Push    | High     | Constructing push options |
:           : Option Syntax             :          : with incorrect,           :
:           :                           :          : unverified key strings.   :
| **T3-15** | Submodule Initialization  | Critical | Blindly initializing      |
:           : Guard Under Git Worktrees :          : submodules without        :
:           :                           :          : verifying if the          :
:           :                           :          : underlying Git worktree   :
:           :                           :          : feature is active.        :
| **T3-16** | XDG Compliant Git         | High     | Hardcoding the user's     |
:           : Configuration Resolution  :          : home directory as the     :
:           :                           :          : sole location for         :
:           :                           :          : `.gitconfig`.             :
| **T3-17** | Strongly-Typed Subprocess | High     | Catching a subprocess     |
:           : Error Contexting          :          : failure and re-raising it :
:           :                           :          : as a generic git error    :
:           :                           :          : with a concatenated       :
:           :                           :          : string message.           :
| **T3-18** | Line-Based Log Extraction | Medium   | Truncating stdout to a    |
:           : for Subprocess            :          : fixed number of           :
:           : Diagnostics               :          : characters and ignoring   :
:           :                           :          : stderr entirely.          :

--------------------------------------------------------------------------------

### Rules

#### T3-01: Unborn Branch Resolution via Symbolic-Ref

> **Rule:** Always attempt `git symbolic-ref` before falling back to manual file
> parsing to correctly resolve unborn branches.
>
> **What:** When querying local Git branch structures, `git symbolic-ref` must
> be attempted as a fallback before file parsing to correctly identify unborn
> branches where `rev-parse` fails.
>
> **Applies To:** Subprocess Git integrations resolving `HEAD` or local refs.
>
> **Why:** Freshly initialized repositories and orphan branches present 'unborn'
> states where standard `rev-parse` commands returned errors, triggering
> false-positive warnings or crashing the client. Failing to adhere to this
> typically results in **Incorrect Branch Detection**.

**Trap 1: Catching a `rev-parse` GitError and immediately falling back to manual
file system reads or emitting warnings.**

**Don't:**

```python
try:
    return rev_parse(HEAD)
except GitError:
    logger.warning("Unparseable HEAD")
    return parse_file(HEAD)
```

**Do:**

```python
try:
    return rev_parse(HEAD)
except GitError:
    try:
        return run_git_command("symbolic-ref", "-q", HEAD)
    except GitError:
        pass
    return parse_file(HEAD)
```

--------------------------------------------------------------------------------

#### T3-02: Centralized GitCommand Abstraction Usage

> **Rule:** Strictly use the internal `GitCommand` abstraction for local Git
> operations instead of invoking raw `subprocess.run`.
>
> **What:** Use the internal `GitCommand` abstraction for executing Git
> operations rather than raw `subprocess.run` to guarantee consistent tracing,
> environment handling, and error translations.
>
> **Applies To:** Any module interacting with local git binaries, such as
> `git_refs.py`.
>
> **Why:** Developers bypassing the centralized wrapper led to duplicated
> subprocess execution logic, loss of global tracing capabilities (e.g.,
> `REPO_TRACE`), and fragmented error handling across the codebase. Failing to
> adhere to this typically results in **Missing Tracing / Environment Bugs**.

**Trap 1: Wrapping `subprocess.run` manually inside a class to invoke Git.**

**Don't:**

```python
def _Run(self, *cmd):
    return subprocess.run(
        ['git', f'--git-dir={self._gitdir}', *cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )
```

**Do:**

```python
from git_command import GitCommand

def _Run(self, cmd):
    p = GitCommand(
        None,
        cmd,
        capture_stdout=True,
        capture_stderr=True,
        bare=True,
        gitdir=self._gitdir,
    )
    p.Wait()
    return p
```

**Exceptions:** Low-level testing utilities isolated from the core application
state, where bypassing `GitCommand` is necessary to bootstrap a test repository.

--------------------------------------------------------------------------------

#### T3-03: NUL-Byte Delimiters for Git Output Parsing

> **Rule:** Always specify NUL-byte delimiters (`%00`) when parsing Git command
> output to prevent splitting errors.
>
> **What:** When parsing Git formatted output, utilize the NUL byte (`%00`)
> instead of tabs or spaces, and leverage precise tuple unpacking without length
> validation.
>
> **Applies To:** Parsing output from Git commands like `git for-each-ref` or
> `git status`.
>
> **Why:** Using whitespace or tabs to split field data exposed the parser to
> failures if reference names or other entities inherently included those
> characters. NUL delimiters guarantee absolute safety and allow removal of
> defensive parsing loops. Failing to adhere to this typically results in **Data
> Parsing Failure**.

**Trap 1: Formatting git fields with tabs and defending against length
variations.**

**Don't:**

```python
# Using tab delimiter and checking len
subprocess.run(['git', 'for-each-ref', '--format=%(objectname)\t%(refname)'])
for line in output.splitlines():
    fields = line.split('\t')
    if len(fields) < 2:
        continue
    ref_id, name = fields[:2]
```

**Do:**

```python
# Using NUL delimiter and direct unpacking
GitCommand(..., ['for-each-ref', '--format=%(objectname)%00%(refname)%00%(symref)'])
for line in output.splitlines():
    ref_id, name, symref = line.split('\0')
```

--------------------------------------------------------------------------------

#### T3-04: Subprocess Execution Context and Native Path Passing

> **Rule:** Pass native `pathlib.Path` objects via the `cwd` argument rather
> than stringifying them or utilizing Git's `-C` flag.
>
> **What:** Execute subprocesses with correct internal API paradigms: omit Git's
> `-C` in favor of the `cwd=` parameter, pass `pathlib.Path` objects inherently,
> and drop `-q` when actively capturing output.
>
> **Applies To:** Subprocess command building and execution in test scaffolding
> and Git interactions.
>
> **Why:** Passing `-C` combined with forced string casting of paths created
> redundant logic. Additionally, suppressing underlying git output via `-q`
> completely masked the root cause of errors captured within the internal stream
> buffers. Failing to adhere to this typically results in **Obscured
> Diagnostics**.

**Trap 1: Stringifying Path objects, using Git-specific directory shifts, and
suppressing piped output.**

**Don't:**

```python
subprocess.check_call(
    ['git', '-C', str(git_dir), 'init', '-q'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
```

**Do:**

```python
subprocess.check_call(
    ['git', 'init'],
    cwd=git_dir,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
```

--------------------------------------------------------------------------------

#### T3-05: Runtime Git Version Constraints for Promisor Packs

> **Rule:** Explicitly verify local Git version compatibility before injecting
> modern CLI flags into subprocess calls.
>
> **What:** Operations utilizing modern Git arguments like
> `--missing=allow-promisor` must be explicitly gated by a minimal supported
> version check against the local executable.
>
> **Applies To:** Subprocess handlers for `git rev-list` and repacking
> mechanisms on partial clones.
>
> **Why:** Git 2.17.0 introduced advanced promisor arguments. Hardcoding these
> arguments in the execution engine crashed older repository clients on machines
> where Git had been downgraded or not updated. Failing to adhere to this
> typically results in **Subprocess Crash**.

**Trap 1: Invoking a modern git CLI flag without ensuring compatibility first.**

**Don't:**

```python
if opt.repack:
    return self.repack_projects(projects, opt)
```

**Do:**

```python
if opt.repack:
    git_require((2, 17, 0), fail=True, msg="--repack")
    return self.repack_projects(projects, opt)
```

--------------------------------------------------------------------------------

#### T3-06: Centralized Dependency Availability Caching

> **Rule:** Centralize and cache external dependency checks to fail gracefully
> without abruptly terminating the calling process.
>
> **What:** External dependency checks (e.g., verifying SSH installation) must
> be centralized, cached internally, and fail gracefully without forcibly
> exiting the calling process.
>
> **Applies To:** System API wrappers and subprocess managers (e.g.,
> `ProxyManager`, `ssh.py`).
>
> **Why:** Deep utility functions checking for external binaries previously
> called `sys.exit(1)` upon `FileNotFoundError`. This abruptly terminated the
> execution for users in environments missing the dependency, even if their
> specific workflow did not actually require it. Failing to adhere to this
> typically results in **Unexpected Process Termination**.

**Trap 1: Catching missing binary exceptions to terminate the process instead of
returning control to the caller.**

**Don't:**

```python
def version():
    try:
        return _parse_ssh_version()
    except FileNotFoundError:
        print("fatal: ssh not installed", file=sys.stderr)
        sys.exit(1)
```

**Do:**

```python
def version():
    try:
        return _parse_ssh_version()
    except FileNotFoundError as e:
        print("warn: ssh not installed", file=sys.stderr)
        raise e
```

**Trap 2: Duplicating inline `try-except` blocks for missing binaries across
multiple execution methods rather than centralizing state.**

**Don't:**

```python
def run_command1(self):
    try:
        subprocess.Popen(['ssh'])
    except FileNotFoundError:
        return False

def run_command2(self):
    try:
        subprocess.Popen(['ssh'])
    except FileNotFoundError:
        return False
```

**Do:**

```python
def __enter__(self):
    try:
        version()
        self._ssh_installed = True
    except FileNotFoundError:
        self._ssh_installed = False
    return self

def run_command(self):
    if not self._ssh_installed:
        return False
    subprocess.Popen(['ssh'])
```

--------------------------------------------------------------------------------

#### T3-07: Subprocess Return Code Validation

> **Rule:** Validate subprocess success strictly using `check_returncode()` on
> the completed process object.
>
> **What:** When utilizing the standard Python `subprocess` library, the correct
> method to validate execution success on a `CompletedProcess` object is
> `check_returncode()`. Do not call `check_call()` on the returned object.
>
> **Applies To:** Any Python code wrapping git commands and handling
> `subprocess.CompletedProcess` results.
>
> **Why:** Legacy code inadvertently called `check_call()` on the result of
> `run_command`, which triggered a runtime `AttributeError` instead of raising
> the expected `subprocess.CalledProcessError` on failure. Failing to adhere to
> this typically results in **AttributeError**.

**Trap 1: Calling a non-existent subprocess execution method on an already
completed process object.**

**Don't:**

```python
ret = subprocess.run(cmd, capture_output=True)
ret.check_call()  # Raises AttributeError
```

**Do:**

```python
ret = subprocess.run(cmd, capture_output=True)
# This will raise subprocess.CalledProcessError for us
ret.check_returncode()
```

--------------------------------------------------------------------------------

#### T3-08: Strict Git Version Compatibility

> **Rule:** Never pass Git flags that are unsupported by the minimum required
> Git version listed in the project's manifest.
>
> **What:** Do not pass modern CLI flags to subprocess Git operations if those
> flags are not supported by the minimum required Git version listed in the
> project's dependency manifest.
>
> **Applies To:** Git subprocess string assembly in `project.py`.
>
> **Why:** The `--no-auto-gc` flag was appended to clone commands to prevent
> deadlocks, but this flag did not exist in Git 1.7.9, immediately breaking
> checkout operations for environments restricted to the minimum supported
> baseline. Failing to adhere to this typically results in **Unknown Option
> Error**.

**Trap 1: Injecting convenient, modern CLI flags into subprocess wrappers.**

**Don't:**

```python
cmd.append("--no-auto-gc")
```

**Do:**

*   Disabling auto-gc via configuration setters (`self.config.SetInt("gc.auto",
    0)`) that are safely interpreted across legacy Git versions.

--------------------------------------------------------------------------------

#### T3-09: Rebase Override for Published Local Branches

> **Rule:** Allow rewriting of published local commits by respecting the
> `force_rebase` argument during sync operations.
>
> **What:** When a local branch is published but not yet merged upstream, `repo
> sync --rebase` must respect the `force_rebase` argument to allow rewriting
> published commits, rather than unconditionally throwing a sync failure.
>
> **Applies To:** `project.py`, specifically `_Rebase` and `_FastForward` path
> execution during sync.
>
> **Why:** The tool previously threw an error instructing the user to run with
> `--rebase`, but didn't actually execute the rebase when the flag was provided,
> forcing developers to manually fix the state. Failing to adhere to this
> typically results in **Broken UX / Unhandled Rebase State**.

**Trap 1: Throwing a `LocalSyncFail` when an upstream gain exists, completely
ignoring the `force_rebase` argument.**

**Don't:**

```python
if upstream_gain and not force_rebase:
    # Fails even if force_rebase is TRUE due to logic gap
    fail(LocalSyncFail("branch is published... rerun with the --rebase option"))
```

**Do:**

```python
if upstream_gain:
    if force_rebase:
        syncbuf.later1(self, _dorebase, not verbose)
    else:
        fail(LocalSyncFail("branch is published... rerun with the --rebase option"))
```

--------------------------------------------------------------------------------

#### T3-10: SSO Authentication Failure Translation

> **Rule:** Intercept Git exit code 128 and translate it to a typed
> `GitAuthError` when stdout indicates an SSO session abort.
>
> **What:** Git commands that fail with exit code 128 due to an SSO session
> abort must be explicitly intercepted and translated into a typed
> `GitAuthError`, preventing them from being masked as a missing reference.
>
> **Applies To:** project.py, Git Subprocess Wrappers evaluating `gitcmd.stdout`
> and return codes (specifically fetch/sync operations interacting with SSO
> remote helpers).
>
> **Why:** In non-interactive environments, an expired SSO token caused Git to
> fail with a generic exit code 128. The tool misinterpreted this as a missing
> upstream reference, leading to confusing error logs that obscured the
> underlying authentication requirement. Failing to adhere to this typically
> results in **Ambiguous Auth Failure**.

**Trap 1: Treating all exit code 128 errors equally without sniffing stdout for
authentication prompt aborts.**

**Don't:**

```python
# BAD: Ambiguous handling of 128
elif current_branch_only and is_sha1 and ret == 128:
    # Assuming missing upstream reference
    raise GitError("Couldn't find the ref you asked for")
```

**Do:**

```python
# GOOD: Explicit trap for SSO helpers
elif ret == 128 and gitcmd.stdout and "remote helper 'sso' aborted session" in gitcmd.stdout:
    raise GitAuthError(gitcmd.stdout)
```

**Exceptions:** Repositories containing multiple remotes where an auth failure
on a secondary remote might be non-fatal. (Currently flagged for future review
but translation stands).

--------------------------------------------------------------------------------

#### T3-11: Direct Read Fallback for Unborn Git HEAD

> **Rule:** Implement a direct file system read of `.git/HEAD` as a fallback
> when standard sub-commands fail to resolve the reference.
>
> **What:** When standard Git commands fail to resolve the current HEAD (e.g.,
> throwing a `GitError`), the system must fall back to directly reading the
> internal `.git/HEAD` file from the filesystem before propagating a fatal
> error.
>
> **Applies To:** project.py, `GetHead()` implementations traversing repository
> state.
>
> **Why:** Empty repositories or states featuring unborn branches caused `git
> rev-parse HEAD` to fail outright. Without a fallback, this cascaded into a
> `NoManifestException` and aborted the entire synchronization process. Falling
> back to the raw `.git/HEAD` text bypassed the strict ref checks. Failing to
> adhere to this typically results in **Hard Crash / NoManifestException**.

**Trap 1: Raising a fatal internal exception immediately upon a `GitError` when
checking for the HEAD reference.**

**Don't:**

```python
# BAD: Strict reliance on git sub-commands
try:
    return self.rev_parse(HEAD)
except GitError as e:
    path = self.GetDotgitPath(subpath=HEAD)
    raise NoManifestException(path, str(e))
```

**Do:**

```python
# GOOD: Fallback text parsing mechanism
try:
    return self.rev_parse(HEAD)
except GitError as e:
    path = self.GetDotgitPath(subpath=HEAD)
    try:
        with open(path) as fd:
            # Read branch manually
    except OSError:
        raise NoManifestException(path, str(e))
```

**Exceptions:** If the physical `.git/HEAD` file raises an `OSError` (meaning it
truly does not exist on disk), a `NoManifestException` is necessary and valid.

--------------------------------------------------------------------------------

#### T3-12: Safe Git Subprocess Output Handling

> **Rule:** Always validate the return code of a Git subprocess before accessing
> its standard output properties.
>
> **What:** Git subprocess output wrappers must explicitly handle non-zero exit
> codes to prevent accessing uninitialized variables, and stream properties must
> be spell-checked against the underlying class definitions.
>
> **Applies To:** Git subprocess wrappers (`git_superproject.py`, `GitCommand`)
> and any execution context capturing stdout/stderr.
>
> **Why:** When a Git command (like `git rev-parse`) failed, the code attempted
> to return a variable (`data`) that was only initialized on success, causing an
> `UnboundLocalError`. Furthermore, error logging attempts crashed due to a typo
> accessing `p.stdwerr` instead of `p.stderr`. Failing to adhere to this
> typically results in **Runtime Crash / UnboundLocalError**.

**Trap 1: Assuming subprocess success and attempting to return an output
variable that hasn't been initialized.**

**Don't:**

```python
# BAD: data is unbound if retval != 0
retval = p.Wait()
if retval == 0:
    data = p.stdout
else:
    log_error("Failed")
return data
```

**Do:**

```python
# GOOD: Explicit error handling with early return
retval = p.Wait()
if retval != 0:
    log_error(f"Failed: {p.stderr}")
    return None
return p.stdout
```

**Trap 2: Typo in the attribute name for capturing standard error from the
`GitCommand` class.**

**Don't:**

```python
# BAD: Invalid attribute triggers AttributeError
self._LogWarning("Error: {}", p.stdwerr)
```

**Do:**

```python
# GOOD: Correct attribute reference
self._LogWarning("Error: {}", p.stderr)
```

--------------------------------------------------------------------------------

#### T3-13: Shallow Clone SHA-1 Fetch Fallback

> **Rule:** Provide a full-sync fallback when shallow fetch requests for
> specific SHA-1s are rejected by server policies.
>
> **What:** Git fetch requests targeting specific SHA-1s with `--depth` enabled
> must handle graceful fallbacks, as server-side policies often restrict
> unadvertised object fetching.
>
> **Applies To:** Git fetch routines in `project.py`, specifically during
> incremental or optimized shallow clones.
>
> **Why:** When optimizing syncs by directly fetching specific SHA-1s with a
> depth limitation, operations failed silently or returned generic errors
> because some Git servers do not advertise all objects, explicitly rejecting
> such requests. Failing to adhere to this typically results in **Sync
> Failure**.

**Trap 1: Assuming a fetch of an arbitrary SHA-1 will unconditionally succeed if
`--depth` is used.**

**Don't:**

```python
# BAD: Missing fallback for unadvertised objects
ret = fetch_sha1(depth=1)
if ret < 0:
    break
```

**Do:**

```python
# GOOD: Explicit fallback to a full sync (depth-less) if the specific SHA-1 is rejected
ret = fetch_sha1(depth=1)
if depth and is_sha1 and ret == 1:
    # Server may not allow fetching unadvertised refs, fallback to full sync
    break
```

**Exceptions:** Servers specifically configured to allow
`uploadpack.allowReachableSHA1InWant` or similar parameters, though the client
cannot assume this.

--------------------------------------------------------------------------------

#### T3-14: Validating Gerrit Push Option Syntax

> **Rule:** Pass custom Gerrit push options strictly using the documented
> `custom-keyed-value` parameter syntax.
>
> **What:** When passing custom metadata to Gerrit via Git push options,
> strictly adhere to the `custom-keyed-value` syntax as defined by the remote
> server documentation.
>
> **Applies To:** `upload.py` operations mapping superproject state to `git push
> -o`.
>
> **Why:** The client attempted to attach superproject metadata to push
> operations using `custom-key-value`, which was ignored by the Gerrit server
> because the documented parameter was `custom-keyed-value`. Failing to adhere
> to this typically results in **Metadata Loss / Server Rejection**.

**Trap 1: Constructing push options with incorrect, unverified key strings.**

**Don't:**

```python
# BAD: Incorrect key format
push_options.append(f"custom-key-value=rootRepo:{host}/{sp_name}")
```

**Do:**

```python
# GOOD: Matches external documentation
push_options.append(f"custom-keyed-value=rootRepo:{host}/{sp_name}")
```

--------------------------------------------------------------------------------

#### T3-15: Submodule Initialization Guard Under Git Worktrees

> **Rule:** Skip Git submodule initialization sequences if the repository is
> actively utilizing Git worktrees.
>
> **What:** Submodule initialization operations (`git submodule init`) must be
> explicitly skipped if the repository is configured to use Git worktrees.
>
> **Applies To:** Git command wrappers, worktree initialization sequences, and
> submodule lifecycle operations in `project.py`.
>
> **Why:** Upstream Git has known bugs and incomplete feature support regarding
> the use of submodules within worktrees. Attempting to initialize submodules
> under these conditions leads to undefined behavior and broken repository
> states. Failing to adhere to this typically results in **Upstream Git Bug /
> Inconsistency**.

**Trap 1: Blindly initializing submodules without verifying if the underlying
Git worktree feature is active.**

**Don't:**

```python
self._InitWorkTree(force_sync=force_sync, submodules=submodules)
if self.has_subprojects:
    self._InitSubmodules()
```

**Do:**

```python
self._InitWorkTree(force_sync=force_sync, submodules=submodules)
# Avoid doing a submodule init when using worktrees as the support for
# submodules is incomplete.
if self.has_subprojects and not self.use_git_worktrees:
    self._InitSubmodules()
```

--------------------------------------------------------------------------------

#### T3-16: XDG Compliant Git Configuration Resolution

> **Rule:** Resolve user Git configuration files natively honoring the
> `XDG_CONFIG_HOME` environment variable before defaulting to legacy paths.
>
> **What:** Git configuration lookups must natively respect the
> `XDG_CONFIG_HOME` environment variable, falling back to `~/.config/git/config`
> before finally querying the legacy `~/.gitconfig` location.
>
> **Applies To:** Git configuration parsing, environment setup, and hermetic
> tests.
>
> **Why:** Users who migrated their dotfiles to the XDG Base Directory
> Specification experienced issues because internal tooling rigidly expected
> `~/.gitconfig` to exist, bypassing user intentions and leading to
> unauthenticated or unconfigured repository actions. Failing to adhere to this
> typically results in **Orphaned Configuration State**.

**Trap 1: Hardcoding the user's home directory as the sole location for
`.gitconfig`.**

**Don't:**

```python
def _getUserConfig():
    return os.path.expanduser("~/.gitconfig")
```

**Do:**

```python
def _getUserConfig():
    """This matches git: https://git-scm.com/docs/git-config#FILES"""
    xdg_config_home = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    xdg_config_file = os.path.join(xdg_config_home, "git", "config")
    if os.path.exists(xdg_config_file):
        return xdg_config_file
    return os.path.expanduser("~/.gitconfig")
```

--------------------------------------------------------------------------------

#### T3-17: Strongly-Typed Subprocess Error Contexting

> **Rule:** Raise strongly-typed `GitCommandError` exceptions with granular
> state context instead of generic Git errors.
>
> **What:** Git commands that yield non-zero exit codes must raise a specialized
> `GitCommandError` containing granular execution context, rather than a generic
> `GitError`.
>
> **Applies To:** Subprocess execution wrappers within `git_command.py` and
> downstream consumers handling Git process states.
>
> **Why:** When commands failed silently or raised generic errors, downstream
> handlers could not differentiate between configuration errors and actual
> subprocess failures, leading to loss of arguments and return codes. Failing to
> adhere to this typically results in **Lost Diagnostic Context**.

**Trap 1: Catching a subprocess failure and re-raising it as a generic git error
with a concatenated string message.**

**Don't:**

```python
if self.rc != 0:
    raise GitError("%s: %s" % (command[1], e))
```

**Do:**

```python
if self.rc != 0:
    raise GitCommandError(
        message="git command failure",
        project=project.name,
        command_args=self.cmdv,
        git_rc=self.rc,
        git_stdout=stdout,
    )
```

--------------------------------------------------------------------------------

#### T3-18: Line-Based Log Extraction for Subprocess Diagnostics

> **Rule:** Extract and log the first meaningful line of both standard output
> and error streams rather than enforcing arbitrary truncation limits.
>
> **What:** When capturing subprocess logs for error reporting, extract the
> first meaningful line of `stdout` and `stderr` instead of relying on arbitrary
> character limits.
>
> **Applies To:** Error truncation logic for Git subprocesses in `Wait()`
> blocks.
>
> **Why:** Truncating output by an arbitrary number of characters (e.g., 80
> chars) occasionally cut off the actual error string. Furthermore, ignoring
> `stderr` hid the root cause of the subprocess failure. Failing to adhere to
> this typically results in **Obfuscated Error Logs**.

**Trap 1: Truncating stdout to a fixed number of characters and ignoring stderr
entirely.**

**Don't:**

```python
stdout = self.stdout[:80] if self.stdout else None
```

**Do:**

```python
# Prefer extracting the first full line and including stderr
stdout_line = self.stdout.splitlines()[0] if self.stdout else None
stderr_line = self.stderr.splitlines()[0] if self.stderr else None
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T2 | Filesystem Atomicity & Worktree Layout - *Subprocess
    executions must coordinate with filesystem atomicity rules, particularly
    regarding submodule paths and worktree usage to prevent upstream Git bugs.*
*   **Downstream:** T5 | Hermetic Testing & Test Modernization - *Testing
    frameworks depend on hermetic GitCommand wrappers and mocked stream capture
    to validate subprocess behaviors safely.*

## Chapter: Manifest Object Model & Deduplication

**Context:** This chapter governs the parsing, validation, and canonicalization
of XML manifest components. It strictly enforces semantic immutability via
`NamedTuple` implementations, defensive copying for hierarchical override
scoping, and deterministic JSON-backed file tracking across the subsystem.

### Summary

| Rule ID   | Principle / Constraint    | Priority | Primary Symptom / Trap    |
| :-------- | :------------------------ | :------- | :------------------------ |
| **T4-01** | Strict Traversal Prefix   | High     | Using broad substring     |
:           : Matching for Relative     :          : matching to detect        :
:           : URLs                      :          : relative traversal        :
:           :                           :          : sequences.                :
| **T4-02** | Extend-Project            | High     | Omitting group            |
:           : Inheritance Scoping       :          : inheritance constraints   :
:           :                           :          : for dynamically           :
:           :                           :          : overridden node elements. :
| **T4-03** | Tuple Immutability in     | Medium   | Instantiating transient   |
:           : Membership Checks         :          : list objects inside loop  :
:           :                           :          : conditions.               :
| **T4-04** | Defensive Copying of      | High     | Assigning a shared        |
:           : Shared Collections Prior  :          : collection reference and  :
:           : to In-Place Mutation      :          : immediately using an      :
:           :                           :          : in-place operator,        :
:           :                           :          : unknowingly mutating the  :
:           :                           :          : original source.          :
| **T4-05** | Immutable NamedTuples for | High     | Overriding `__hash__` and |
:           : Hashable Object           :          : `__eq__` on a standard    :
:           : Deduplication             :          : mutable Python class to   :
:           :                           :          : allow set insertion.      :
| **T4-06** | Strict Empty Set          | Critical | Falling back to the empty |
:           : Initialization Over       :          : bracket literal when a    :
:           : Dictionary Literals       :          : null set is encountered   :
:           :                           :          : prior to a union          :
:           :                           :          : operation.                :
| **T4-07** | Immutable Manifest        | High     | Implementing custom       |
:           : Elements for Reliable     :          : `__eq__` and `__hash__`   :
:           : Deduplication             :          : on mutable classes and    :
:           :                           :          : using `list.append()`     :
:           :                           :          : which allows duplicates   :
:           :                           :          : to accrue.                :
| **T4-08** | Mutually Exclusive XML    | Medium   | Independent `if`          |
:           : Node Parsing              :          : conditions checking       :
:           :                           :          : `nodeName` sequentially   :
:           :                           :          : in a loop.                :
| **T4-09** | JSON Serialization for    | High     | Dumping file paths        |
:           : File Path State Tracking  :          : sequentially into a flat  :
:           :                           :          : text file using newlines  :
:           :                           :          : as the only delimiter.    :
| **T4-10** | Set Operations for File   | Medium   | Using manual for-loops    |
:           : Deltas                    :          : and list appends to       :
:           :                           :          : calculate the difference  :
:           :                           :          : between two collections.  :
| **T4-11** | Upstream Base Revision    | Medium   | Overriding a project      |
:           : Validation in Layered     :          : revision without          :
:           : Manifests                 :          : asserting the previous    :
:           :                           :          : expected state.           :

--------------------------------------------------------------------------------

### Rules

#### T4-01: Strict Traversal Prefix Matching for Relative URLs

> **Rule:** Always explicitly evaluate exact path-traversal prefixes (`./` or
> `../`) when resolving relative URLs. Never rely on generic substring matching.
>
> **What:** Relative URL path detection must explicitly evaluate exact
> path-traversal prefixes to avoid inadvertently capturing hidden files or
> custom naming structures.
>
> **Applies To:** URL string manipulation and Git submodule path resolution.
>
> **Why:** The path parser attempted to identify relative submodule paths by
> checking if the URL started with a dot (`.`). This excessively broad
> evaluation failed on identically named hidden repositories or custom
> sub-namespaces (e.g., `.foo`), improperly joining them to the base URL.
> Failing to adhere to this typically results in **Invalid Path Resolution**.

**Trap 1: Using broad substring matching to detect relative traversal
sequences.**

**Don't:**

```python
if url.startswith("."):
    url = urllib.parse.urljoin("%s/" % self.remote.url, url)
```

**Do:**

```python
if url.startswith("./") or url.startswith("../"):
    url = urllib.parse.urljoin("%s/" % self.remote.url, url)
```

--------------------------------------------------------------------------------

#### T4-02: Extend-Project Inheritance Scoping

> **Rule:** Must explicitly restrict `extend-project` XML nodes from
> automatically inheriting contextually local execution scopes (`local:` groups)
> from root parents.
>
> **What:** When managing XML manifestation directives, `extend-project` nodes
> must be actively restricted from inheriting contextually local execution
> scopes (`local:` groups).
>
> **Applies To:** XML manifest engine mappings and override properties.
>
> **Why:** Without explicit protection, extended project entities
> unintentionally inherited top-level project local groups, confusing the
> inclusion and exclusion scoping directives that drive synchronization
> boundaries. Failing to adhere to this typically results in **Scope
> Contamination**.

**Trap 1: Omitting group inheritance constraints for dynamically overridden node
elements.**

**Don't:**

*   Allow XML logic to process `extend-project` the exact same way it processes
    raw `project` roots without negative test coverage.

**Do:**

*   Implement testing and parsing guards proving that elements processed under
    `extend-project` actively strip `local:` group attributes.

--------------------------------------------------------------------------------

#### T4-03: Tuple Immutability in Membership Checks

> **Rule:** Always use immutable tuples instead of list literals for membership
> tests against constant sequences within hot loops.
>
> **What:** Utilize immutable tuples `()` instead of list literals `[]` when
> performing membership tests (the `in` operator) against constant sequences to
> minimize reallocation overhead and adhere to idiomatic Python.
>
> **Applies To:** XML manifest parsing logic (`manifest_xml.py`) and hot loops
> across the codebase.
>
> **Why:** During recursive node parsing, list literals were instantiated on
> every iteration solely to check if a node name matched fixed schema elements.
> Failing to adhere to this typically results in **Performance Degradation**.

**Trap 1: Instantiating transient list objects inside loop conditions.**

**Don't:**

```python
if node.nodeName in ["include", "project"]:
```

**Do:**

```python
if node.nodeName in ("include", "project"):
```

--------------------------------------------------------------------------------

#### T4-04: Defensive Copying of Shared Collections Prior to In-Place Mutation

> **Rule:** Must defensively copy shared parent collections before applying
> in-place update operators (`|=`), strictly handling null-safety during the
> process.
>
> **What:** When propagating inherited collections (e.g., manifest group sets)
> to child nodes, shared parent sets must be defensively copied prior to
> applying in-place union or update operators (`|=`). Null-safety must be
> handled during the copy.
>
> **Applies To:** XML Manifest Parsing (`manifest_xml.py`); hierarchical state
> propagation where child elements inherit and augment parent states.
>
> **Why:** Assigning a parent's group set directly to a child and then using the
> in-place union operator (`|=`) modified the original parent set in memory.
> This caused the child's specific groups to 'leak' into unrelated sibling nodes
> processed subsequently. Failing to adhere to this typically results in **State
> Corruption / Group Leakage**.

**Trap 1: Assigning a shared collection reference and immediately using an
in-place operator, unknowingly mutating the original source.**

**Don't:**

```python
# BAD: In-place modification mutates the shared parent_groups object
nodeGroups = parent_groups
if node.hasAttribute("groups"):
    nodeGroups |= self._ParseSet(node.getAttribute("groups"))
```

**Do:**

```python
# GOOD: Create a localized copy before mutation
nodeGroups = parent_groups.copy() if parent_groups else set()
if node.hasAttribute("groups"):
    nodeGroups |= self._ParseSet(node.getAttribute("groups"))
```

**Trap 2: Falling back to an empty set instantiation after a copy call without
guarding against a null reference.**

**Don't:**

```python
# BAD: Raises AttributeError if parent_groups is None
include_groups = parent_groups.copy() or set()
```

**Do:**

```python
# GOOD: Null-safe default evaluation prior to the copy invocation
include_groups = (parent_groups or set()).copy()
```

--------------------------------------------------------------------------------

#### T4-05: Immutable NamedTuples for Hashable Object Deduplication

> **Rule:** Always subclass `NamedTuple` to define custom objects stored in
> hash-based collections. Never implement manual `__hash__` and `__eq__`
> functions on mutable classes.
>
> **What:** Custom objects stored in hash-based collections (like `set` or used
> as `dict` keys) for deduplication must guarantee immutability. Avoid manually
> implementing `__eq__` and `__hash__` on mutable classes; instead, subclass
> `NamedTuple`.
>
> **Applies To:** Manifest deduplication logic (`project.py`); specifically
> elements like `_CopyFile` and `_LinkFile` stored in sets.
>
> **Why:** Manually implementing `__hash__` on a standard class based on its
> mutable `__dict__` attributes created a landmine. If the object's properties
> changed after insertion into a set, the hash mismatched, rendering the object
> unreachable and breaking deduplication. Failing to adhere to this typically
> results in **Memory Leak / Deduplication Failure**.

**Trap 1: Overriding `__hash__` and `__eq__` on a standard mutable Python class
to allow set insertion.**

**Don't:**

```python
# BAD: Properties can mutate, altering the hash post-insertion
class _CopyFile:
    def __init__(self, src, dest):
        self.src = src
        self.dest = dest
    def __hash__(self):
        return hash(repr(sorted(self.__dict__.items())))
    def __eq__(self, other):
        return self.__dict__ == other.__dict__
```

**Do:**

```python
# GOOD: Use typing.NamedTuple to guarantee immutability
from typing import NamedTuple

class _CopyFile(NamedTuple):
    src: str
    dest: str
```

--------------------------------------------------------------------------------

#### T4-06: Strict Empty Set Initialization Over Dictionary Literals

> **Rule:** Must explicitly invoke `set()` when initializing empty collections
> meant for set operations. Never fall back to the empty bracket literal `{}`.
>
> **What:** When initializing or providing a fallback empty collection meant for
> set operations (such as union `|` or `|=`), explicitly instantiate a `set()`
> rather than using the empty literal `{}`.
>
> **Applies To:** Python collection management globally; prominently surfaced
> during list-to-set manifest group migrations.
>
> **Why:** During a migration from lists to sets for group parsing, an empty
> default was incorrectly represented as `{}`. Since `{}` evaluates to a `dict`
> in Python, attempting a set union between a valid set and the empty dict threw
> an immediate, fatal `TypeError`. Failing to adhere to this typically results
> in **Runtime Crash / TypeError**.

**Trap 1: Falling back to the empty bracket literal when a null set is
encountered prior to a union operation.**

**Don't:**

```python
# BAD: '{}' creates an empty dictionary, throwing a TypeError upon union
expanded_project_groups = {"all"} | (self.groups or {})
```

**Do:**

```python
# GOOD: Explicitly initialize an empty set
expanded_project_groups = {"all"} | (self.groups or set())
```

--------------------------------------------------------------------------------

#### T4-07: Immutable Manifest Elements for Reliable Deduplication

> **Rule:** Always represent manifest file operations as inherently immutable
> structures to guarantee safe, order-preserving deduplication.
>
> **What:** Manifest elements representing file operations must be implemented
> as immutable structures (e.g., `NamedTuple`) to ensure safe deduplication and
> deterministic order preservation, avoiding manual string-based hashing.
>
> **Applies To:** Manifest parsing models, specifically `<copyfile>` and
> `<linkfile>` abstractions.
>
> **Why:** Previously, manifest objects were stored in mutable lists, relying on
> manual string representations (`repr`) and sorted dictionary items for
> hashing. This risked state corruption and failed to cleanly deduplicate
> repeated entries while maintaining the relative declaration sequence. Failing
> to adhere to this typically results in **Silent Data Corruption / Redundant
> File Operations**.

**Trap 1: Implementing custom `__eq__` and `__hash__` on mutable classes and
using `list.append()` which allows duplicates to accrue.**

**Don't:**

```python
class _CopyFile:
    def __hash__(self):
        # BAD: Manual serialization of mutable dictionary
        return hash(repr(sorted(self.__dict__.items())))

self.copyfiles.append(_CopyFile(src, dest))
```

**Do:**

```python
class _CopyFile(NamedTuple):
    # GOOD: Inherently immutable and hashable
    src: str
    dest: str

# GOOD: Using a dict to deduplicate while preserving insertion order
self.copyfiles[_CopyFile(src, dest)] = True
```

--------------------------------------------------------------------------------

#### T4-08: Mutually Exclusive XML Node Parsing

> **Rule:** Always chain mutually exclusive XML node type checks using an
> `if-elif` structure rather than independent sequential statements.
>
> **What:** When parsing mutually exclusive XML node types, use an `if-elif`
> structure to avoid redundant condition evaluations.
>
> **Applies To:** XML parsing loops (e.g., iterating over `node.childNodes` in
> `manifest_xml.py`).
>
> **Why:** A sequence of independent `if` statements forced unnecessary string
> comparisons even after a matching node name was found. Failing to adhere to
> this typically results in **CPU Overhead / Inefficient Parsing**.

**Trap 1: Independent `if` conditions checking `nodeName` sequentially in a
loop.**

**Don't:**

```python
if n.nodeName == "copyfile":
    self._ParseCopyFile(p, n)
if n.nodeName == "linkfile":
    self._ParseLinkFile(p, n)
```

**Do:**

```python
if n.nodeName == "copyfile":
    self._ParseCopyFile(p, n)
elif n.nodeName == "linkfile":
    self._ParseLinkFile(p, n)
```

--------------------------------------------------------------------------------

#### T4-09: JSON Serialization for File Path State Tracking

> **Rule:** Must persist dynamically generated manifest file outputs using
> structured JSON serialization. Never use newline-delimited plaintext for path
> lists.
>
> **What:** Persistent tracking mechanisms for manifest-generated file
> operations must use structured JSON serialization instead of newline-delimited
> plaintext to support special characters in paths.
>
> **Applies To:** Manifest state management (`subcmds/sync.py`), internal
> `.repo` tracking files (e.g., `copy-link-files.json`).
>
> **Why:** Tracking `<copyfile>` and `<linkfile>` operations via flat,
> newline-delimited text files broke serialization and cleanup when file paths
> legally contained newline (`\n`) characters. Structured JSON protects against
> these bounds issues. Failing to adhere to this typically results in **Parsing
> Errors / Orphaned Files**.

**Trap 1: Dumping file paths sequentially into a flat text file using newlines
as the only delimiter.**

**Don't:**

```python
with open('linkfile.list', 'w') as fd:
    for path in new_linkfiles:
        fd.write(path + '\n')
```

**Do:**

```python
with open('copy-link-files.json', 'w') as fd:
    json.dump({'linkfile': new_linkfiles, 'copyfile': new_copyfiles}, fd)
```

--------------------------------------------------------------------------------

#### T4-10: Set Operations for File Deltas

> **Rule:** Always compute the delta between unordered lists of file paths using
> native Python set operations (`-`).
>
> **What:** When computing the delta between lists of file paths (e.g., figuring
> out which obsolete files to remove), utilize Python set operations rather than
> manual iterations with truthiness and membership checks.
>
> **Applies To:** Deduplicating objects, comparing manifest states, computing
> file differences.
>
> **Why:** Calculating the difference between historical tracking data and new
> target paths was done using O(N*M) nested iterations with redundant truthiness
> checks, leading to verbose and less performant code. Failing to adhere to this
> typically results in **Algorithmic Inefficiency**.

**Trap 1: Using manual for-loops and list appends to calculate the difference
between two collections.**

**Don't:**

```python
need_remove_files = []
for old_path in old_dict.get('linkfile', []):
  if old_path and old_path not in new_paths:
    need_remove_files.append(old_path)
```

**Do:**

```python
need_remove_files = []
need_remove_files.extend(
    set(old_dict.get('linkfile', [])) -
    set(new_paths)
)
```

**Exceptions:** Ordered constraints where file evaluation sequence matters (sets
are unordered).

--------------------------------------------------------------------------------

#### T4-11: Upstream Base Revision Validation in Layered Manifests

> **Rule:** Must assert multi-layer manifest overrides (`extend-project`)
> against the parent project's expected state by utilizing a `base-rev`
> attribute.
>
> **What:** When overriding (`extend-project`) or removing (`remove-project`)
> projects in a layered manifest structure, changes should be validated against
> the expected state of the parent project via a `base-rev` attribute.
>
> **Applies To:** XML Manifest parsing logic (`manifest_xml.py`) during
> multi-manifest ingestion.
>
> **Why:** Downstream projects using layered manifests would unknowingly apply
> overrides (like custom revisions) to upstream components that had drastically
> changed their underlying state or branches, resulting in 'undead patches' that
> silently masked critical upstream changes. Failing to adhere to this typically
> results in **Silent Configuration Divergence**.

**Trap 1: Overriding a project revision without asserting the previous expected
state.**

**Don't:**

```xml
<!-- BAD: Blind override leaves system vulnerable to upstream changes -->
<extend-project name="my-project" revision="refs/changes/123" />
```

**Do:**

```xml
<!-- GOOD: Base-rev acts as a guardrail -->
<extend-project name="my-project" base-rev="upstream_hash" revision="refs/changes/123" />
```

**Trap 2: Checking string-based manifest attributes using implicit truthiness.**

**Don't:**

```python
# BAD: Implicit truthiness skips validation if revisionExpr is unexpectedly empty
if base and p.revisionExpr and p.revisionExpr != base:
    raise Error()
```

**Do:**

```python
# GOOD: Strict comparison catches empty/None states if a base is declared
if base and p.revisionExpr != base:
    raise Error()
```

**Exceptions:** The `base-rev` attribute is optional to maintain backward
compatibility for users migrating to the new manifest schema.

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T2 | Filesystem Atomicity & Worktree Layout - *File path
    extraction and submodule path resolution mapped here strictly govern
    worktree creation and legacy migration algorithms downstream.*
*   **Downstream:** T6 | CLI Argument Parsing & UX Consistency - *Structured
    JSON serialization outputted from manifest paths sets the direct format
    constraint for CLI UX and tooling integrations.*

## Chapter: Hermetic Testing & Test Modernization

**Context:** This domain governs the migration of legacy `unittest` suites to
modern `pytest` functional paradigms and the establishment of hermetic session
fixtures. It enforces strict environment isolation to prevent global state
pollution (e.g., developer `.gitconfig` bleeding) while safely intercepting
standard streams and filesystem paths.

### Summary

| Rule ID   | Principle / Constraint          | Priority | Primary Symptom /   |
:           :                                 :          : Trap                :
| :-------- | :------------------------------ | :------- | :------------------ |
| **T5-01** | Idiomatic Truthiness Validation | Medium   | Asserting strict    |
:           : in Tests                        :          : identity against    :
:           :                                 :          : Python boolean      :
:           :                                 :          : singletons.         :
| **T5-02** | Pytest Over Legacy Unittest     | High     | Subclassing         |
:           : Framework                       :          : `unittest.TestCase` :
:           :                                 :          : and configuring     :
:           :                                 :          : state inside a      :
:           :                                 :          : `setUp` method for  :
:           :                                 :          : new test files.     :
| **T5-03** | Dedicated Test Utilities for    | Medium   | Copy-pasting        |
:           : API Helpers                     :          : utility functions   :
:           :                                 :          : across test modules :
:           :                                 :          : or placing standard :
:           :                                 :          : functions into      :
:           :                                 :          : pytest conftest     :
:           :                                 :          : files.              :
| **T5-04** | Test Framework Modernization to | High     | Modifying           |
:           : Pytest                          :          : environment         :
:           :                                 :          : variables globally  :
:           :                                 :          : at module load to   :
:           :                                 :          : support tests.      :
| **T5-05** | Standard Output Capture via     | Medium   | Using the mock      |
:           : Context Managers                :          : framework to        :
:           :                                 :          : intercept a core    :
:           :                                 :          : language stream.    :
| **T5-06** | Direct Helper Functions Over    | Medium   | Defining a pytest   |
:           : Fixture Factories               :          : fixture that yields :
:           :                                 :          : a nested function   :
:           :                                 :          : to bypass global    :
:           :                                 :          : state limitations.  :
| **T5-07** | Elimination of Redundant Path   | Medium   | Chaining explicit   |
:           : Assertions                      :          : existence checks    :
:           :                                 :          : before access       :
:           :                                 :          : checks.             :
| **T5-08** | Pathlib Utility Constants for   | Medium   | Using nested        |
:           : Test Path Resolution            :          : `os.path.dirname`   :
:           :                                 :          : and `os.path.join`  :
:           :                                 :          : to traverse back to :
:           :                                 :          : the parent          :
:           :                                 :          : directory.          :
| **T5-09** | Pytest Adoption for Test Suite  | High     | Creating test case  |
:           : Definition                      :          : classes that        :
:           :                                 :          : inherit from        :
:           :                                 :          : `unittest.TestCase` :
:           :                                 :          : and asserting via   :
:           :                                 :          : `self.assertEqual`. :
| **T5-10** | Minimal Mocking Isolation for   | High     | Using stacked patch |
:           : Test Reliability                :          : decorators for      :
:           :                                 :          : non-relevant        :
:           :                                 :          : sub-routines (e.g., :
:           :                                 :          : standard error      :
:           :                                 :          : outputs or          :
:           :                                 :          : colorizers) just to :
:           :                                 :          : trigger an embedded :
:           :                                 :          : autocorrection      :
:           :                                 :          : flow.               :
| **T5-11** | Canonical Resolution for System | Medium   | Patching            |
:           : Library Mocks                   :          : `time.sleep` by     :
:           :                                 :          : referencing the     :
:           :                                 :          : specific host       :
:           :                                 :          : application file    :
:           :                                 :          : where it was        :
:           :                                 :          : locally imported.   :
| **T5-12** | Memoized Function Cache         | High     | Mocking the         |
:           : Clearing in Setup               :          : underlying behavior :
:           :                                 :          : of a cached         :
:           :                                 :          : function but        :
:           :                                 :          : leaving the LRU     :
:           :                                 :          : cache intact across :
:           :                                 :          : tests.              :
| **T5-13** | Idiomatic Standard Stream       | Medium   | Using `mock.patch`  |
:           : Redirection                     :          : to manually inject  :
:           :                                 :          : a `StringIO` object :
:           :                                 :          : over `sys.stderr`.  :
| **T5-14** | Context Manager Nesting         | Medium   | Adding a new level  |
:           : Consolidation                   :          : of indentation for  :
:           :                                 :          : every context       :
:           :                                 :          : manager invoked.    :
| **T5-15** | Anti-Change Detector Tests      | Medium   | Asserting exact     |
:           :                                 :          : equality of string  :
:           :                                 :          : outputs including   :
:           :                                 :          : standardized        :
:           :                                 :          : prefixes.           :
| **T5-16** | Infrastructure Prebuilts via    | Medium   | Relying on tools    |
:           : vpython                         :          : that dynamically    :
:           :                                 :          : build Python from   :
:           :                                 :          : source to test      :
:           :                                 :          : across multiple     :
:           :                                 :          : versions.           :
| **T5-17** | Modernized Filesystem Paths via | Medium   | Using               |
:           : Pathlib                         :          : `os.path.join` and  :
:           :                                 :          : `with open(...,     :
:           :                                 :          : 'w')` for basic     :
:           :                                 :          : text file creation  :
:           :                                 :          : in tests.           :
| **T5-18** | Standardized Module-Level Mock  | Medium   | Importing specific  |
:           : Imports                         :          : classes or          :
:           :                                 :          : exceptions directly :
:           :                                 :          : from test targets   :
:           :                                 :          : or standard         :
:           :                                 :          : libraries.          :
| **T5-19** | Pytest Adoption for New Test    | High     | Creating subclasses |
:           : Modules                         :          : of                  :
:           :                                 :          : `unittest.TestCase` :
:           :                                 :          : and using           :
:           :                                 :          : `self.assertEqual`. :
| **T5-20** | High-Fidelity Test Targets over | High     | Using `MagicMock`   |
:           : Permissive Mocks                :          : to bypass           :
:           :                                 :          : instantiating core  :
:           :                                 :          : models.             :
| **T5-21** | Session-Scoped Hermetic Git     | Medium   | Executing `git      |
:           : Identity Injection              :          : config` inside      :
:           :                                 :          : individual test     :
:           :                                 :          : setup blocks to     :
:           :                                 :          : fake a user         :
:           :                                 :          : identity.           :
| **T5-22** | Automated Lifecycle Management  | High     | Spawning detached   |
:           : for Test Filesystem Artifacts   :          : temporary           :
:           :                                 :          : directories and     :
:           :                                 :          : manually            :
:           :                                 :          : maintaining cleanup :
:           :                                 :          : blocks.             :
| **T5-23** | Idiomatic String Evaluation in  | Medium   | Iterating over raw  |
:           : Mocked Test Streams             :          : string splits and   :
:           :                                 :          : manually validating :
:           :                                 :          : line length to      :
:           :                                 :          : count valid output  :
:           :                                 :          : strings.            :
| **T5-24** | Hermetic Isolation of Git       | High     | Relying on default  |
:           : Configuration Directories in    :          : system paths for    :
:           : Tests                           :          : the home directory  :
:           :                                 :          : during test         :
:           :                                 :          : execution.          :
| **T5-25** | Scope Hierarchy Enforcement in  | Medium   | Injecting           |
:           : Pytest Fixtures                 :          : `tmp_path` into a   :
:           :                                 :          : fixture decorated   :
:           :                                 :          : with                :
:           :                                 :          : `scope="session"`.  :
| **T5-26** | Strict Python Version           | Medium   | Adding modern       |
:           : Compatibility for Third-Party   :          : third-party test    :
:           : Plugins                         :          : dependencies to     :
:           :                                 :          : legacy-supported    :
:           :                                 :          : projects without    :
:           :                                 :          : validating the      :
:           :                                 :          : minimum required    :
:           :                                 :          : Python constraints. :
| **T5-27** | Hermetic Isolation of Terminal  | High     | Relying on the      |
:           : UI Color Configurations         :          : default state of    :
:           :                                 :          : the `Coloring`      :
:           :                                 :          : class without       :
:           :                                 :          : forcing it during   :
:           :                                 :          : setup, implicitly   :
:           :                                 :          : depending on        :
:           :                                 :          : environmental       :
:           :                                 :          : variables.          :
| **T5-28** | Abstract Intent Documentation   | Medium   | Documenting exact   |
:           : in Unit Tests                   :          : data values being   :
:           :                                 :          : asserted directly   :
:           :                                 :          : in the test         :
:           :                                 :          : docstring.          :

--------------------------------------------------------------------------------

### Rules

#### T5-01: Idiomatic Truthiness Validation in Tests

> **Rule:** Always use implicit truthiness or falsiness evaluations in test
> assertions unless strict type matching is explicitly required.
>
> **What:** Test suites must use implicit truthy/falsy validations rather than
> asserting strict identity against boolean singletons unless exact type
> enforcement is necessary.
>
> **Applies To:** Python assertions in test frameworks (pytest, unittest).
>
> **Why:** Tests relying on strict boolean identity (`is True`) became brittle
> when refactoring configurations or flag implementations that returned
> alternative truthy values. Failing to adhere to this typically results in
> **Brittle Assertions**.

**Trap 1: Asserting strict identity against Python boolean singletons.**

**Don't:**

```python
assert opts.include_summary is True
```

**Do:**

```python
assert opts.include_summary
```

**Exceptions:** Situations where distinguishing between None and False is
structurally critical to the application logic.

--------------------------------------------------------------------------------

#### T5-02: Pytest Over Legacy Unittest Framework

> **Rule:** Must implement new test suites using modular `pytest` definitions
> instead of propagating `unittest.TestCase` boilerplate.
>
> **What:** New test modules must be implemented using standalone `pytest`
> functional constructs rather than inheriting from `unittest.TestCase` to avoid
> heavy class-based boilerplate.
>
> **Applies To:** Test module architecture (`tests/test_*.py`).
>
> **Why:** The project previously utilized deeply nested `unittest.TestCase`
> structures with complex `setUp` inheritance, which obfuscated test
> initialization and hindered code reusability. Failing to adhere to this
> typically results in **High Boilerplate / Lock-In**.

**Trap 1: Subclassing `unittest.TestCase` and configuring state inside a `setUp`
method for new test files.**

**Don't:**

```python
class InfoCommand(unittest.TestCase):
    def setUp(self):
        self.cmd = build_cmd()
```

**Do:**

```python
def _get_cmd():
    return build_cmd()

def test_command_defaults():
    cmd = _get_cmd()
    assert cmd.is_valid()
```

--------------------------------------------------------------------------------

#### T5-03: Dedicated Test Utilities for API Helpers

> **Rule:** Never overload `conftest.py` with generic API helpers; always place
> reusable test queries in dedicated utility modules.
>
> **What:** Shared test APIs and environment-probing logic (e.g., checking Git
> feature support) must be placed in dedicated utility modules (like
> `utils_for_test.py`) rather than duplicated or shoved into `conftest.py`.
>
> **Applies To:** Test suite architecture and environment scaffolding.
>
> **Why:** Developers were duplicating identical environment checks across
> different test files or misusing `conftest.py` (which should only contain
> fixtures) to store functional APIs. Failing to adhere to this typically
> results in **Test Code Duplication**.

**Trap 1: Copy-pasting utility functions across test modules or placing standard
functions into pytest conftest files.**

**Don't:**

```python
# Inside test_project.py AND test_git_refs.py
def _SupportsReftable():
    return check_git_support()
```

**Do:**

```python
# Inside tests/utils_for_test.py
def supports_reftable():
    return check_git_support()

# Inside test_project.py
import utils_for_test
@unittest.skipUnless(utils_for_test.supports_reftable(), "...")
```

**Exceptions:** Test fixtures (such as initialized directories or mock
generators) which belong in `conftest.py`.

--------------------------------------------------------------------------------

#### T5-04: Test Framework Modernization to Pytest

> **Rule:** Avoid global module-level environment mutations; consistently
> leverage `pytest` global configuration fixtures.
>
> **What:** Legacy `unittest.TestCase` structures must be migrated to functional
> `pytest` paradigms, leveraging global configuration fixtures over class-based
> `setUp` and `tearDown` methods.
>
> **Applies To:** Entire Python test suite and all new unit tests.
>
> **Why:** Heavy inheritance and isolated setup code within `unittest.TestCase`
> resulted in repeated environment mutation logic, obscured dependencies, and an
> inability to easily share global setup mechanisms like dummy user identities
> or tracing control. Failing to adhere to this typically results in **Global
> State Pollution**.

**Trap 1: Modifying environment variables globally at module load to support
tests.**

**Don't:**

```python
import os
os.environ['REPO_TRACE'] = '0'

class GitRefsTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
```

**Do:**

```python
# Rely on conftest.py fixtures automatically handling environments.
def test_git_refs(tmp_path, disable_repo_trace, setup_user_identity):
    gitdir = tmp_path / '.git'
    # Run assertions using standard assert statements
    assert head == refs.get('HEAD')
```

--------------------------------------------------------------------------------

#### T5-05: Standard Output Capture via Context Managers

> **Rule:** Must utilize `contextlib.redirect_stdout` to capture standard output
> streams rather than injecting raw stream mocks.
>
> **What:** Use the standard library `contextlib.redirect_stdout` for capturing
> command output in test scopes, instantiated directly as a one-liner, rather
> than utilizing the `unittest.mock` framework to patch system streams.
>
> **Applies To:** Python test suites (Pytest/Unittest) intercepting CLI stdout
> payloads.
>
> **Why:** Tests were previously relying on `@mock.patch` for `sys.stdout` or
> utilizing multi-line context manager instantiations, which unnecessarily
> coupled output capture to the mocking engine and added boilerplate. Failing to
> adhere to this typically results in **Unnecessary Mocking / Test Bloat**.

**Trap 1: Using the mock framework to intercept a core language stream.**

**Don't:**

```python
@mock.patch("sys.stdout", new_callable=io.StringIO)
def test_something(self, mock_stdout):
    # test logic
```

**Do:**

```python
import contextlib
import io

def test_something():
    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        # test logic
```

**Trap 2: Creating the string buffer variable outside the context manager scope
unnecessarily.**

**Don't:**

```python
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    _run_status(manifest, ["-o"])
```

**Do:**

```python
with contextlib.redirect_stdout(io.StringIO()) as stdout:
    _run_status(manifest, ["-o"])
```

--------------------------------------------------------------------------------

#### T5-06: Direct Helper Functions Over Fixture Factories

> **Rule:** Avoid defining dummy `pytest` fixtures solely to return nested
> function callbacks; use straightforward module-level helpers instead.
>
> **What:** Do not abuse the Pytest fixture system to generate and return local
> functions. If a utility does not benefit from the fixture lifecycle management
> (setup/teardown), it should be a standard module-level or private helper
> function.
>
> **Applies To:** Pytest files requiring test data initialization or repetitive
> setup procedures.
>
> **Why:** Test frameworks became overly complex when developers wrapped simple
> initialization logic in `@pytest.fixture` annotations just to yield a callable
> function to the test case. Failing to adhere to this typically results in
> **Fixture Graph Bloat**.

**Trap 1: Defining a pytest fixture that yields a nested function to bypass
global state limitations.**

**Don't:**

```python
@pytest.fixture
def init_temp_git_tree():
    def _init_temp_git_tree(git_dir: Path) -> None:
        # init logic
    return _init_temp_git_tree
```

**Do:**

```python
def _init_temp_git_tree(git_dir: Path) -> None:
    # init logic
```

--------------------------------------------------------------------------------

#### T5-07: Elimination of Redundant Path Assertions

> **Rule:** Never prepend path existence assertions prior to invoking
> permissions or loading assertions that implicitly validate existence.
>
> **What:** Do not assert the existence of a file prior to asserting its
> specific permissions or state. Subsequent OS-level operations implicitly
> validate path existence.
>
> **Applies To:** Python unittests validating filesystem layouts, binary
> configurations, or hook executable permissions.
>
> **Why:** Tests contained boilerplate blocks invoking `os.path.isfile()` purely
> to offer a custom string format failure, even though the immediate next line
> invoking `os.access()` would fail correctly with an implicit lack of
> existence. Failing to adhere to this typically results in **Test
> Boilerplate**.

**Trap 1: Chaining explicit existence checks before access checks.**

**Don't:**

```python
self.assertTrue(os.path.isfile(repo_path), f"{repo_path} does not exist")
self.assertTrue(os.access(repo_path, os.X_OK), f"{repo_path} is not executable")
```

**Do:**

```python
self.assertTrue(os.access(repo_path, os.X_OK), f"{repo_path} is not executable")
```

--------------------------------------------------------------------------------

#### T5-08: Pathlib Utility Constants for Test Path Resolution

> **Rule:** Always resolve test filesystem boundaries using centralized
> `pathlib` objects instead of string-concatenating legacy `os.path` operations.
>
> **What:** Path constructions in test files should utilize modern pathlib
> objects via centralized utility constants (e.g., `utils_for_test.THIS_DIR`)
> instead of verbose `os.path` operations.
>
> **Applies To:** Python test suites interacting with the file system.
>
> **Why:** Manual path constructions using nested `os.path.dirname(__file__)`
> calls created verbose, hard-to-read boilerplate that cluttered the test logic.
> Failing to adhere to this typically results in **Verbose Code Base**.

**Trap 1: Using nested `os.path.dirname` and `os.path.join` to traverse back to
the parent directory.**

**Don't:**

```python
repo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "repo")
```

**Do:**

```python
repo_path = utils_for_test.THIS_DIR.parent / "repo"
```

--------------------------------------------------------------------------------

#### T5-09: Pytest Adoption for Test Suite Definition

> **Rule:** Must author all file-level test assertions utilizing `pytest` syntax
> constructs over legacy `unittest` equivalents.
>
> **What:** Test files must be defined using the modern `pytest` framework,
> avoiding class-based `unittest.TestCase` inheritance and relying on standard
> `assert` semantics.
>
> **Applies To:** The entire Python testing suite.
>
> **Why:** The legacy `unittest` structure required extensive, verbose
> boilerplate for state setup, test case classes, and specific assertion methods
> that restricted readability. Failing to adhere to this typically results in
> **Test Verbosity**.

**Trap 1: Creating test case classes that inherit from `unittest.TestCase` and
asserting via `self.assertEqual`.**

**Don't:**

```python
import unittest
class RepoTests(unittest.TestCase):
    def test_example(self):
        self.assertEqual(a, b)
```

**Do:**

```python
# Standalone pytest functions
def test_example():
    assert a == b
```

--------------------------------------------------------------------------------

#### T5-10: Minimal Mocking Isolation for Test Reliability

> **Rule:** Avoid deeply nested or exhaustively mocked test wrappers; isolate
> and invoke inner target logic primitives instead.
>
> **What:** Mock usage must be limited strictly to necessary external
> intercepts. Exhaustive mock environments must not be created just to drive a
> small piece of inner logic; instead, structural refactoring must isolate the
> logical boundary.
>
> **Applies To:** Test suites involving deep API structures and side-effects.
>
> **Why:** Relying on heavily nested, brittle 'house of cards' mock
> configurations meant tests frequently failed when unrelated code modifications
> broke the strict internal mock assumptions, turning tests into throwaway
> artifacts. Failing to adhere to this typically results in **Fragile Mock
> Collapse**.

**Trap 1: Using stacked patch decorators for non-relevant sub-routines (e.g.,
standard error outputs or colorizers) just to trigger an embedded autocorrection
flow.**

**Don't:**

```python
with mock.patch("main.RepoClient", return_value=mock_client):
    with mock.patch("main.SetDefaultColoring"):
        repo._RunLong("tart", gopts, argv, log)
```

**Do:**

*   Isolate the logic into `_autocorrect_command_name()` and test it by passing
    minimal data primitives: `res = self.repo._autocorrect_command_name("tart",
    mock_config)`.

**Exceptions:** Testing hard, native OS-level boundary bindings.

--------------------------------------------------------------------------------

#### T5-11: Canonical Resolution for System Library Mocks

> **Rule:** Always patch standard libraries at their canonical origin namespace
> rather than targeting the local module import resolution boundary.
>
> **What:** Standard library functions must be targeted for testing patches at
> their canonical origin namespace rather than the local import footprint of the
> target module.
>
> **Applies To:** Test configuration defining `mock.patch` paths.
>
> **Why:** Patching against the local module import representation strictly
> coupled tests to a given file's exact inclusion syntax. Minor refactors
> altering module import aliases completely disabled testing verification.
> Failing to adhere to this typically results in **Brittle Patch Routing**.

**Trap 1: Patching `time.sleep` by referencing the specific host application
file where it was locally imported.**

**Don't:**

```python
@mock.patch("main.time.sleep")
```

**Do:**

```python
@mock.patch("time.sleep")
```

--------------------------------------------------------------------------------

#### T5-12: Memoized Function Cache Clearing in Setup

> **Rule:** Always flush the `lru_cache` of mocked globally-accessible memoized
> functions within the test initialization sequence.
>
> **What:** When mocking globally accessible functions decorated with
> `@functools.lru_cache`, the cache must be explicitly cleared in the test
> suite's `setUp` routine.
>
> **Applies To:** Unit test suites interacting with memoized functions.
>
> **Why:** Failing to clear the `lru_cache` of globally executed functions
> during testing caused subsequent tests in the runner to receive cached mock
> results injected by prior tests, leading to non-deterministic, cascading
> failures. Failing to adhere to this typically results in **State Contamination
> / Flaky Tests**.

**Trap 1: Mocking the underlying behavior of a cached function but leaving the
LRU cache intact across tests.**

**Don't:**

```python
class SshTests(unittest.TestCase):
    def test_version(self):
        with mock.patch("ssh._run_ssh_version", return_value="OpenSSH_1.2\n"):
            self.assertEqual(ssh.version(), (1, 2))
```

**Do:**

```python
class SshTests(unittest.TestCase):
    def setUp(self):
        ssh.version.cache_clear()

    def test_version(self):
        with mock.patch("ssh._run_ssh_version", return_value="OpenSSH_1.2\n"):
            self.assertEqual(ssh.version(), (1, 2))
```

--------------------------------------------------------------------------------

#### T5-13: Idiomatic Standard Stream Redirection

> **Rule:** Always employ `contextlib.redirect_stderr` directly instead of
> overwriting standard stream objects globally using patch frameworks.
>
> **What:** To intercept `stderr` or `stdout` in testing, utilize the standard
> library's context managers (`contextlib.redirect_stderr`) instead of
> overriding the stream objects globally using `mock.patch`.
>
> **Applies To:** Unit testing standard output logs and error streams.
>
> **Why:** Using generic mocks to replace `sys.stderr` creates brittle tests
> with broader side effects. The standard library provides dedicated tools
> strictly designed for capturing stream text safely. Failing to adhere to this
> typically results in **Non-Idiomatic Tooling / Brittle Mocks**.

**Trap 1: Using `mock.patch` to manually inject a `StringIO` object over
`sys.stderr`.**

**Don't:**

```python
with mock.patch("sys.stderr", new=io.StringIO()) as mock_stderr:
    run_command()
```

**Do:**

```python
f = io.StringIO()
with contextlib.redirect_stderr(f):
    run_command()
```

--------------------------------------------------------------------------------

#### T5-14: Context Manager Nesting Consolidation

> **Rule:** Consolidate contiguous mock or context manager deployments into
> single-line definitions to minimize indentation footprints.
>
> **What:** Contiguous, deeply nested context managers (`with` blocks) should be
> consolidated into a single `with` statement to reduce horizontal indentation
> and structural complexity.
>
> **Applies To:** Complex test fixtures or code paths requiring multiple
> synchronized states or file handles.
>
> **Why:** Individual context managers per line resulted in excessive code
> indentation (pyramid of doom), harming readability and consuming unnecessary
> screen space. Failing to adhere to this typically results in **Excessive
> Indentation / Pyramid of Doom**.

**Trap 1: Adding a new level of indentation for every context manager invoked.**

**Don't:**

```python
with mock.patch("sys.stderr") as mock_stderr:
    with mock.patch("socket.socket") as ms:
        run_test()
```

**Do:**

```python
with mock.patch("sys.stderr") as mock_stderr, mock.patch("socket.socket") as ms:
    run_test()
```

--------------------------------------------------------------------------------

#### T5-15: Anti-Change Detector Tests

> **Rule:** Avoid exact full-string assertions when evaluating formatted logs or
> stringified error conditions to prevent brittle side-effect maintenance.
>
> **What:** When verifying error logging or outputs, tests must assert on
> flexible core substrings rather than exact line matches, and exceptions
> configured as mock side effects should use class types rather than
> instantiated string objects.
>
> **Applies To:** Unit testing string outputs, logs, and simulated mock
> failures.
>
> **Why:** Tests acting as 'change detectors' failed unnecessarily when minor
> formatting, capitalization, or prefix strings (e.g., 'WARNING' vs 'warning')
> were updated in the underlying code, despite the core logic remaining
> functional. Failing to adhere to this typically results in **Brittle Tests /
> Extraneous Boilerplate**.

**Trap 1: Asserting exact equality of string outputs including standardized
prefixes.**

**Don't:**

```python
self.assertEqual(stderr.getvalue(), "repo: warning: git trace2 logging failed: Mock error")
```

**Do:**

```python
self.assertIn("git trace2 logging failed", stderr.getvalue())
```

**Trap 2: Instantiating an exception with a dummy string for a simple
side-effect mock.**

**Don't:**

```python
mock_socket.connect.side_effect = OSError("Mock error")
```

**Do:**

```python
mock.patch("socket.socket", side_effect=OSError)
```

**Exceptions:** Tests explicitly verifying exact formatting serialization (e.g.,
JSON schema adherence).

--------------------------------------------------------------------------------

#### T5-16: Infrastructure Prebuilts via vpython

> **Rule:** Must execute continuous integration environments using `vpython`
> wrappers instead of relying on legacy source-compiling orchestration
> frameworks like `pyenv`.
>
> **What:** Leverage `vpython` for multi-version Python testing rather than
> `tox` combined with `pyenv` to utilize prebuilt binaries and minimize
> environment setup overhead.
>
> **Applies To:** Hermetic testing setups, CI pipelines, and multi-version
> coverage scripts.
>
> **Why:** Using `pyenv` and `tox` forced CI and local test runs to download and
> compile Python versions from source on the fly, adding minutes of overhead to
> every test run. Shifting to `vpython` leveraged prebuilt infrastructure
> runtimes. Failing to adhere to this typically results in **Slow CI Builds**.

**Trap 1: Relying on tools that dynamically build Python from source to test
across multiple versions.**

**Don't:**

*   Using `tox.ini` with `pyenv` to orchestrate matrix testing across Python
    versions, incurring source-compilation penalties.

**Do:**

*   Invoking tests via `vpython`, which provisions hermetic virtual environments
    rapidly using precompiled infrastructure binaries.

--------------------------------------------------------------------------------

#### T5-17: Modernized Filesystem Paths via Pathlib

> **Rule:** Always employ `pathlib` objects for mock file I/O operations rather
> than manual string handling and context managers.
>
> **What:** Test case file system operations should use the modern `pathlib`
> library rather than legacy `os.path` and manual file handles.
>
> **Applies To:** Unit tests and file system operations across the codebase.
>
> **Why:** Legacy tests relied heavily on `os.path.join` and `with open(...)`
> which led to verbose, repetitive boilerplate when constructing mock repository
> states. Failing to adhere to this typically results in **Verbose Boilerplate /
> Maintainability Overhead**.

**Trap 1: Using `os.path.join` and `with open(..., 'w')` for basic text file
creation in tests.**

**Don't:**

```python
# BAD: Verbose manual file writing
root_m = os.path.join(self.manifest_dir, "root.xml")
with open(root_m, "w") as fp:
    fp.write("<manifest>...")
```

**Do:**

```python
# GOOD: Pathlib usage for concise writes
root_m = self.manifest_dir / "root.xml"
root_m.write_text("<manifest>...")
```

--------------------------------------------------------------------------------

#### T5-18: Standardized Module-Level Mock Imports

> **Rule:** Import external test dependencies and internal domain targets as
> complete module spaces rather than cherry-picking precise classes.
>
> **What:** Test files must import `mock` as a module (`from unittest import
> mock`) and internal targets as a module (`from subcmds import wipe`), rather
> than importing specific classes directly.
>
> **Applies To:** All unit tests.
>
> **Why:** Direct class imports caused namespace pollution and deviated from the
> Google Python Style Guide, making it harder to track the origin of
> dependencies. Failing to adhere to this typically results in **Style Guide
> Violation / Namespace Pollution**.

**Trap 1: Importing specific classes or exceptions directly from test targets or
standard libraries.**

**Don't:**

```python
from unittest.mock import MagicMock
from subcmds.wipe import Wipe, WipeError

mock_obj = MagicMock()
```

**Do:**

```python
from unittest import mock
from subcmds import wipe

mock_obj = mock.MagicMock()
```

--------------------------------------------------------------------------------

#### T5-19: Pytest Adoption for New Test Modules

> **Rule:** Must restrict the creation of new `unittest.TestCase` files strictly
> unless explicitly bypassing native pytest infrastructure constraints.
>
> **What:** New test modules must be written using the `pytest` framework rather
> than the legacy `unittest` structure.
>
> **Applies To:** All newly added test files.
>
> **Why:** The project was modernizing its testing infrastructure, aiming to
> eliminate `unittest` boilerplate and leverage native `pytest` fixtures for
> global state management. Failing to adhere to this typically results in
> **Technical Debt / Legacy Test Framework Propagation**.

**Trap 1: Creating subclasses of `unittest.TestCase` and using
`self.assertEqual`.**

**Don't:**

```python
class WipeUnitTest(unittest.TestCase):
    def test_wipe(self):
        self.assertTrue(os.path.exists(path))
```

**Do:**

```python
def test_wipe(tmp_path):
    assert os.path.exists(path)
```

**Exceptions:** Unless a compelling reason exists requiring native `unittest`
mechanics.

--------------------------------------------------------------------------------

#### T5-20: High-Fidelity Test Targets over Permissive Mocks

> **Rule:** Avoid stubbing robust architectural models like `Project` or
> `Manifest` via permissive `MagicMock` allocations; instantiate genuine domain
> classes instead.
>
> **What:** Tests should instantiate and utilize real domain objects (e.g., the
> `Project` class) rather than relying heavily on generic `MagicMock` instances,
> to ensure test fidelity.
>
> **Applies To:** Unit testing, particularly for core models like `Project` or
> `Manifest`.
>
> **Why:** Overuse of `MagicMock` led to tests passing despite broken
> implementations because the mocks lacked side-effects and realistic attribute
> validation. Failing to adhere to this typically results in **False Positive
> Test Results**.

**Trap 1: Using `MagicMock` to bypass instantiating core models.**

**Don't:**

```python
# BAD: Mocks won't fail if the API changes
proj = mock.MagicMock()
proj.name = "test"
proj.DeleteWorktree.side_effect = lambda: True
```

**Do:**

```python
# GOOD: Using actual domain objects for accurate side-effects
proj = Project(manifest=mock_manifest, name="test", ...)
```

**Exceptions:** External network calls or complex, deeply decoupled subsystems
where instantiating the real object is prohibitively difficult.

--------------------------------------------------------------------------------

#### T5-21: Session-Scoped Hermetic Git Identity Injection

> **Rule:** Must inject pseudo Git commit identities as session-scoped
> environment variables rather than manually rewriting local Git configurations
> per test.
>
> **What:** Automated test suites must globally stub Git's author and committer
> identities using session-scoped environment variables to ensure execution in
> clean or unconfigured environments.
>
> **Applies To:** Pytest configuration (`tests/conftest.py`) and all tests
> executing raw Git subprocess commands.
>
> **Why:** Tests interacting with local Git repositories crashed with
> `GitCommandError` on CI runners or clean developer machines lacking a global
> `user.name` and `user.email`. Patching this locally in tests via `git config`
> calls introduced I/O overhead and redundant code. Failing to adhere to this
> typically results in **GitCommandError / Test Flakiness**.

**Trap 1: Executing `git config` inside individual test setup blocks to fake a
user identity.**

**Don't:**

```python
def test_commit(self):
    subprocess.run(["git", "config", "user.name", "Foo Bar"])
    subprocess.run(["git", "config", "user.email", "foo@bar.com"])
    # Run test logic
```

**Do:**

```python
@pytest.fixture(autouse=True, scope="session")
def setup_user_identity(monkeysession):
    """Set env variables for author and committer name and email."""
    monkeysession.setenv("GIT_AUTHOR_NAME", "Foo Bar")
    monkeysession.setenv("GIT_COMMITTER_NAME", "Foo Bar")
    monkeysession.setenv("GIT_AUTHOR_EMAIL", "foo@bar.baz")
    monkeysession.setenv("GIT_COMMITTER_EMAIL", "foo@bar.baz")
```

--------------------------------------------------------------------------------

#### T5-22: Automated Lifecycle Management for Test Filesystem Artifacts

> **Rule:** Must utilize automated `TemporaryDirectory` constructs integrated
> securely into test teardown sequences instead of performing unmanaged manual
> disk sweeps.
>
> **What:** Test fixtures must use state-managed temporary directory constructs
> (e.g., `tempfile.TemporaryDirectory`) whose lifecycle is explicitly bound to
> standard unit test teardown phases, avoiding manual unmanaged path allocation
> and raw removal.
>
> **Applies To:** All test suites performing filesystem mock operations or Git
> repository initialization (`tests/test_subcmds_forall.py`).
>
> **Why:** Tests were manually allocating paths via `tempfile.mkdtemp` and
> issuing raw `shutil.rmtree` calls. This pattern proved fragile, resulting in
> leaked directories across runs or skipped cleanup phases if a test failed
> early. Failing to adhere to this typically results in **Orphaned Artifacts /
> Resource Leaks**.

**Trap 1: Spawning detached temporary directories and manually maintaining
cleanup blocks.**

**Don't:**

```python
def setUp(self):
    self.tempdir = tempfile.mkdtemp()

def tearDown(self):
    shutil.rmtree(self.tempdir, ignore_errors=True)
```

**Do:**

```python
def setUp(self):
    self.tempdirobj = tempfile.TemporaryDirectory(prefix="forall_tests")
    self.tempdir = self.tempdirobj.name

def tearDown(self):
    self.tempdirobj.cleanup()
```

--------------------------------------------------------------------------------

#### T5-23: Idiomatic String Evaluation in Mocked Test Streams

> **Rule:** Avoid manually slicing and measuring length properties for string
> evaluations; consistently evaluate standard streams using built-in truthiness
> routines.
>
> **What:** Evaluating outputs from captured stdout or stderr in tests must
> utilize Pythonic abstractions like `splitlines()` and implicit truthiness
> evaluation, rather than raw newline splitting and explicit length checks.
>
> **Applies To:** Hermetic Test suites executing mock command line calls and
> inspecting `sys.stdout`.
>
> **Why:** Legacy test code relied on manual string manipulation like
> `split("\n")` and boolean evaluations like `len(line) > 0`. This approach was
> unidiomatic, fragile against cross-platform line endings, and bloated test
> suite verbosity. Failing to adhere to this typically results in **Fragile
> Tests / Unidiomatic Logic**.

**Trap 1: Iterating over raw string splits and manually validating line length
to count valid output strings.**

**Don't:**

```python
line_count = 0
for line in mock_stdout.getvalue().split("\n"):
    if len(line) > 0:
        line_count += 1
```

**Do:**

```python
line_count = sum(1 if x else 0 for x in mock_stdout.getvalue().splitlines())
```

--------------------------------------------------------------------------------

#### T5-24: Hermetic Isolation of Git Configuration Directories in Tests

> **Rule:** Always isolate Git initialization by injecting temporary dummy
> directories via environment overrides (`HOME` / `USERPROFILE`) to restrict
> test interference.
>
> **What:** Tests utilizing local git operations must hermetically isolate
> environment variables like `HOME` and `USERPROFILE` to prevent developers'
> global configurations from leaking into test executions.
>
> **Applies To:** Global test initialization routines (`conftest.py`, Pytest
> fixtures, class-level test setup).
>
> **Why:** Historically, if a developer's global `.gitconfig` required GPG
> signing (`commit.gpgsign=true`), a git subprocess spawned during test setup
> would unexpectedly open an interactive prompt (e.g., vim) to solicit a signing
> key, causing the test suite to deadlock permanently. Failing to adhere to this
> typically results in **Test Deadlock / State Bleed**.

**Trap 1: Relying on default system paths for the home directory during test
execution.**

**Don't:**

```python
# BAD: Allows test subprocesses to read ~/.gitconfig
subprocess.run(['git', 'tag', '--annotate'])
```

**Do:**

```python
# GOOD: Override environment variables to an isolated temp directory
@pytest.fixture(autouse=True, scope="session")
def alt_home(tmp_path_factory, monkeysession):
    var = "USERPROFILE" if platform_utils.isWindows() else "HOME"
    monkeysession.setenv(var, str(tmp_path_factory.mktemp("home")))
```

**Exceptions:** Tests that explicitly exist to validate the parsing logic of a
user's real, existing `.gitconfig` (which is highly discouraged).

--------------------------------------------------------------------------------

#### T5-25: Scope Hierarchy Enforcement in Pytest Fixtures

> **Rule:** Never propagate lower-scoped test fixtures (e.g., function-scoped
> states) into global session-scoped initialization procedures.
>
> **What:** A session-scoped Pytest fixture cannot depend on lower-scoped
> fixtures (such as a function-scoped `tmp_path`). To create temporary paths at
> the session level, `tmp_path_factory.mktemp` must be utilized.
>
> **Applies To:** Pytest fixture definitions, specifically within `conftest.py`.
>
> **Why:** A session-scoped setup mechanism attempted to use the function-scoped
> `tmp_path` fixture. This caused pytest initialization failures. Furthermore,
> reusing function-scoped directories for session-level state caused unintended
> disk thrashing as the directory was continually wiped at the teardown of every
> function. Failing to adhere to this typically results in **Scope Mismatch /
> State Masking**.

**Trap 1: Injecting `tmp_path` into a fixture decorated with
`scope="session"`.**

**Don't:**

```python
# BAD: Session fixture depending on function fixture
@pytest.fixture(scope="session")
def session_tmp_homedir(tmp_path):
    return tmp_path
```

**Do:**

```python
# GOOD: Using the factory to generate a session-level path
@pytest.fixture(scope="session")
def session_tmp_homedir(tmp_path_factory):
    return tmp_path_factory.mktemp("home")
```

--------------------------------------------------------------------------------

#### T5-26: Strict Python Version Compatibility for Third-Party Plugins

> **Rule:** Must strictly align test dependency injection configurations against
> the underlying project's absolute minimum supported Python versions.
>
> **What:** Test tooling dependencies must strictly align with the project's
> minimum supported Python version. External plugin implementation logic should
> be inlined with proper attribution if the plugin requires a newer Python
> version than the project supports.
>
> **Applies To:** Dependency management (`tox.ini`), `conftest.py`, and CI
> environments.
>
> **Why:** A developer introduced a new Pytest plugin to manage isolated home
> directories. However, the plugin required Python 3.8+, while the project
> maintained compatibility down to Python 3.6+. This mismatch caused post-submit
> CI pipeline checks to crash upon test environment installation. Failing to
> adhere to this typically results in **CI Installation Failure**.

**Trap 1: Adding modern third-party test dependencies to legacy-supported
projects without validating the minimum required Python constraints.**

**Don't:**

```ini
# BAD: tox.ini adds dependency unsupported by CI target
deps =
    pytest
    pytest-home >= 0.4
```

**Do:**

```python
# GOOD: Inline the logic and remove the external dependency
# adapted from pytest-home 0.5.1
@pytest.fixture(autouse=True, scope="session")
def session_tmp_homedir(tmp_path_factory, monkeysession):
    # implementation logic here
```

**Exceptions:** When the project's minimum supported Python version is
officially bumped to match the plugin's requirement.

--------------------------------------------------------------------------------

#### T5-27: Hermetic Isolation of Terminal UI Color Configurations

> **Rule:** Must aggressively lock default terminal coloring states when
> generating UI tests to isolate regressions from variable environment
> pipelines.
>
> **What:** Unit tests that assert on UI or logging text containing ANSI color
> codes must explicitly force the coloring state to prevent ambient git
> configurations or CI terminal limitations from altering test outcomes.
>
> **Applies To:** Unit tests interacting with the `color` or `repo_logging`
> modules.
>
> **Why:** Tests validating color outputs failed non-deterministically based on
> the ambient environment (e.g., CI runners lacking a TTY, or developers having
> `color.ui=false` in their global `.gitconfig`). Failing to adhere to this
> typically results in **Flaky Tests / Non-Deterministic Failures**.

**Trap 1: Relying on the default state of the `Coloring` class without forcing
it during setup, implicitly depending on environmental variables.**

**Don't:**

```python
def setUp(self):
    config_fixture = fixture("test.gitconfig")
    self.config = git_config.GitConfig(config_fixture)
    self.color = color.Coloring(self.config, "status")
```

**Do:**

```python
def setUp(self):
    config_fixture = fixture("test.gitconfig")
    self.config = git_config.GitConfig(config_fixture)
    color.SetDefaultColoring("always")
    self.color = color.Coloring(self.config, "status")
```

--------------------------------------------------------------------------------

#### T5-28: Abstract Intent Documentation in Unit Tests

> **Rule:** Never embed exact literal assertions or explicit structural values
> directly inside unit test docstring commentary.
>
> **What:** Test docstrings should describe the behavioral intent or structural
> coverage of the test rather than hardcoding the exact assertion values or
> low-level implementation details.
>
> **Applies To:** Python `unittest` module docstrings.
>
> **Why:** Docstrings that hardcoded exact ANSI escape sequences or config
> values became stale and misleading whenever the underlying mappings or
> formatting codes were updated. Failing to adhere to this typically results in
> **Documentation Rot / Maintenance Overhead**.

**Trap 1: Documenting exact data values being asserted directly in the test
docstring.**

**Don't:**

```python
def test_Color_Parse_first_parameter_none(self):
    """fg is black(30), bg is red(31+10=41), attr is ul(4)"""
    val = self.color._parse(None, 'black', 'red', 'ul')
    self.assertEqual('\x1b[4;30;41m', val)
```

**Do:**

```python
def test_Color_Parse_first_parameter_none(self):
    """check fg & bg & attr"""
    val = self.color._parse(None, "black", "red", "ul")
    self.assertEqual("\x1b[4;30;41m", val)
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T2 | Filesystem Atomicity & Worktree Layout - *Managing safe
    creation and atomic removal of temporary worktrees and `.git` directories
    supports reliable test state fixtures.*
*   **Downstream:** T3 | Subprocess Git Integration & Error Translation -
    *Hermetic test constraints directly dictate how standard git streams,
    configuration injections, and subprocess executions are mocked or
    intercepted.*
*   **Downstream:** T6 | CLI Argument Parsing & UX Consistency - *Strict
    terminal environment control in testing enforces deterministic verification
    of CLI autocorrect flows and standardized UI colorizations.*

## Chapter: CLI Argument Parsing & UX Consistency

**Context:** This chapter governs the lifecycle, validation, and execution of
command-line arguments, enforcing strict standardization for machine-readable
serialization, unified logging, and deterministic, thread-safe terminal
interactions.

### Summary

| Rule ID   | Principle /      | Priority | Primary Symptom /     |
:           : Constraint       :          : Trap                  :
| :-------- | :--------------- | :------- | :-------------------- |
| **T6-01** | Deterministic    | High     | Providing only        |
:           : Machine-Readable :          : aesthetically         :
:           : Output Formats   :          : formatted terminal    :
:           :                  :          : text for diagnostic   :
:           :                  :          : commands.             :
| **T6-02** | Elimination of   | Medium   | Assigning a short     |
:           : Niche Short      :          : option to a feature   :
:           : Options          :          : that isn't commonly   :
:           :                  :          : used by developers.   :
| **T6-03** | Extensible       | Medium   | Creating rigid,       |
:           : Boolean Toggle   :          : single-purpose        :
:           : Flags            :          : boolean switches for  :
:           :                  :          : granular output       :
:           :                  :          : components.           :
| **T6-04** | Context-Aware    | Medium   | Hardcoding visual     |
:           : CLI Output       :          : formatting elements   :
:           : Separators       :          : directly after a      :
:           :                  :          : primary block instead :
:           :                  :          : of conditionally      :
:           :                  :          : checking the next     :
:           :                  :          : block.                :
| **T6-05** | Output Format    | Medium   | Handling output       |
:           : Standardization  :          : formatting via raw    :
:           : via Enums        :          : string matching and   :
:           :                  :          : `print()` statements  :
:           :                  :          : without suppressing   :
:           :                  :          : the interactive       :
:           :                  :          : pager.                :
| **T6-06** | Symmetric        | Medium   | Mixing one output     |
:           : Execution        :          : format's dispatch     :
:           : Dispatching      :          : call with the inline  :
:           :                  :          : procedural logic of   :
:           :                  :          : the fallback format.  :
| **T6-07** | CLI Argument     | Medium   | Overriding a          |
:           : Simulation over  :          : configuration         :
:           : Internal State   :          : parameter directly on :
:           : Mutation         :          : the parsed namespace  :
:           :                  :          : object.               :
| **T6-08** | Deterministic    | Medium   | Iterating over a list |
:           : Sorting of       :          : of accumulated        :
:           : Parallel         :          : multi-process results :
:           : Execution        :          : without sorting.      :
:           : Results          :          :                       :
| **T6-09** | Strict Adherence | Medium   | Adding a              |
:           : to Feature       :          : `--force-jobs` CLI    :
:           : Requests         :          : bypass flag           :
:           :                  :          : simultaneously        :
:           :                  :          : alongside the new     :
:           :                  :          : `sync-j-max` manifest :
:           :                  :          : attribute.            :
| **T6-10** | Minimal Logic in | High     | Placing the entire    |
:           : Exception        :          : typo-correction       :
:           : Handlers         :          : logic, user prompts,  :
:           :                  :          : and command reloading :
:           :                  :          : inside `except        :
:           :                  :          : KeyError\:`.          :
| **T6-11** | Unified Logging  | Medium   | Outputting warnings   |
:           : Protocol via     :          : directly to the       :
:           : Standard Logger  :          : `sys.stderr` stream   :
:           :                  :          : using the built-in    :
:           :                  :          : `print` function.     :
| **T6-12** | Strict           | High     | Wrapping string-typed |
:           : Translation of   :          : configuration         :
:           : Configuration    :          : variables inside      :
:           : Booleans         :          : `int()` and catching  :
:           :                  :          : value exceptions to   :
:           :                  :          : deduce defaults.      :
| **T6-13** | Interruptibility | Critical | Placing raw time      |
:           : of Interactive   :          : suspension code       :
:           : Runtime Delays   :          : before a return       :
:           :                  :          : statement without     :
:           :                  :          : wrapping it in a trap :
:           :                  :          : for cancellation      :
:           :                  :          : overrides.            :
| **T6-14** | Strict           | Critical | Consuming CLI option  |
:           : Pre-Access       :          : flags before the      :
:           : Initialization   :          : shared initialization :
:           : of CLI Options   :          : pipeline populates    :
:           :                  :          : default properties.   :
| **T6-15** | Omission of      | Medium   | Redundantly           |
:           : Redundant        :          : configuring           :
:           : Optparse         :          : destination variables :
:           : Destinations     :          : in CLI arguments.     :
| **T6-16** | Subcommand       | Medium   | Writing               |
:           : Scoping in       :          : global-sounding       :
:           : Commit Messages  :          : commit messages for   :
:           :                  :          : isolated subcommand   :
:           :                  :          : patches.              :
| **T6-17** | Module-Scoped    | Medium   | Redundantly prefixing |
:           : Exception Naming :          : the exception name    :
:           :                  :          : with the module name  :
:           :                  :          : inside the module     :
:           :                  :          : definition.           :
| **T6-18** | Explicit         | High     | Using terms like      |
:           : Terminology in   :          : 'worktree' in help    :
:           : Destructive CLI  :          : text without explicit :
:           : Commands         :          : definition or         :
:           :                  :          : examples.             :
| **T6-19** | Fail-Fast        | Medium   | Checking for missing  |
:           : Argument         :          : positional arguments  :
:           : Validation in    :          : directly inside       :
:           : Subcommands      :          : `Execute()`.          :
| **T6-20** | Respect Global   | Medium   | Unconditionally       |
:           : Verbosity Flags  :          : printing progress     :
:           :                  :          : messages to stderr or :
:           :                  :          : stdout.               :
| **T6-21** | Thread-Safe      | Critical | Directly querying     |
:           : Terminal         :          : `sys.stderr.fileno()` :
:           : Querying during  :          : inside long-running   :
:           : IO Capture       :          : concurrent loops.     :
| **T6-22** | Global State via | Medium   | Adding environment    |
:           : Persistent       :          : variable mappings     :
:           : Configuration    :          : into command-line     :
:           : over Environment :          : parsers to support    :
:           : Variables        :          : 'headless'            :
:           :                  :          : configurations.       :
| **T6-23** | CLI Command      | Medium   | Adding project-wide   |
:           : Parity with Git  :          : or environmental      :
:           : Semantics        :          : metadata queries to   :
:           :                  :          : commands designed for :
:           :                  :          : local working-tree    :
:           :                  :          : analysis.             :
| **T6-24** | Context-Aware    | Medium   | Triggering an         |
:           : Sync Operation   :          : immediate system exit :
:           : Termination      :          : on an update failure. :
| **T6-25** | Explicit Exit    | High     | Using an empty        |
:           : Codes on CLI     :          : `return` to back out  :
:           : Cancellation     :          : of a declined CLI     :
:           :                  :          : confirmation prompt.  :
| **T6-26** | Non-Interactive  | Medium   | Hardcoding            |
:           : Safeties for     :          : interactive prompts   :
:           : Destructive      :          : without checking      :
:           : Commands         :          : configuration flags   :
:           :                  :          : for automation modes. :
| **T6-27** | Strict           | Medium   | Accepting dependent   |
:           : Interdependent   :          : modifier options      :
:           : Argument         :          : unconditionally       :
:           : Validation       :          : without checking      :
:           :                  :          : prerequisites.        :
| **T6-28** | Actionable CLI   | Medium   | Failing a sync        |
:           : Error Messages   :          : operation with a      :
:           : for              :          : descriptive but       :
:           : Synchronization  :          : non-actionable error  :
:           : Failures         :          : message.              :
| **T6-29** | Launcher Version | High     | Modifying the         |
:           : Bumping for      :          : standalone launcher   :
:           : Important        :          : script with important :
:           : Changes          :          : changes without       :
:           :                  :          : incrementing its      :
:           :                  :          : VERSION tuple.        :

--------------------------------------------------------------------------------

### Rules

#### T6-01: Deterministic Machine-Readable Output Formats

> **Rule:** Always expose strict, structured serialization options (e.g., JSON)
> for CLI tools used in automated pipelines to prevent reliance on brittle text
> parsing.
>
> **What:** CLI tools leveraged for inspection must expose strict, structured
> serialization (e.g., JSON) to negate reliance on unstable text parsing in
> CI/CD environments.
>
> **Applies To:** Command-line interface design, specifically subcommands
> utilized by build pipelines or external orchestrators.
>
> **Why:** Downstream automated pipelines were forced to retrieve configuration
> data by executing tools like `repo info` and using string matching (`grep`)
> against human-readable formatting, creating a brittle dependency susceptible
> to UI modifications. Failing to adhere to this typically results in **Pipeline
> Parsing Failure**.

**Trap 1: Providing only aesthetically formatted terminal text for diagnostic
commands.**

**Don't:**

*   Command executes and prints human-readable strings. Consumers must run `repo
    info | grep "Manifest revision"` to extract variables.

**Do:**

*   Integrate a `--format=json` command argument that bypasses human-readable
    display logic and cleanly serializes underlying data models directly to
    standard output.

**Exceptions:** Interactive-only terminal prompts that are heavily stateful and
fundamentally incompatible with automation.

--------------------------------------------------------------------------------

#### T6-02: Elimination of Niche Short Options

> **Rule:** Never assign single-character short options for niche or rarely used
> flags to preserve namespace availability.
>
> **What:** Avoid assigning single-character short options for niche or rarely
> used command-line flags to prevent namespace bloat.
>
> **Applies To:** CLI argument parsing (e.g., `optparse` or `argparse`
> definitions).
>
> **Why:** Short options were being added arbitrarily for specific data
> summaries, leading to a cluttered short-option namespace and hindering future
> expansion. Failing to adhere to this typically results in **Cluttered CLI
> UX**.

**Trap 1: Assigning a short option to a feature that isn't commonly used by
developers.**

**Don't:**

```python
p.add_option("-s", "--summary", action="store_true")
```

**Do:**

```python
p.add_option("--include-summary", action="store_true")
```

--------------------------------------------------------------------------------

#### T6-03: Extensible Boolean Toggle Flags

> **Rule:** Always implement paired positive/negative toggle flags for granular
> outputs rather than relying on rigid, single-purpose boolean switches.
>
> **What:** Conditional output sections must be controlled by paired
> positive/negative toggle flags (e.g., `--include-x` and `--no-include-x`)
> rather than single-purpose boolean flags.
>
> **Applies To:** CLI design and option definitions for output manipulation.
>
> **Why:** Rigid, single-purpose flags for rendering specific summaries limited
> extensibility and prevented developers from precisely tailoring outputs for
> scripts or automation. Failing to adhere to this typically results in **Rigid
> Output Rendering**.

**Trap 1: Creating rigid, single-purpose boolean switches for granular output
components.**

**Don't:**

```python
p.add_option("--summary", action="store_true", help="show only manifest summary")
```

**Do:**

```python
p.add_option("--include-summary", action="store_true", default=True)
p.add_option("--no-include-summary", dest="include_summary", action="store_false")
```

--------------------------------------------------------------------------------

#### T6-04: Context-Aware CLI Output Separators

> **Rule:** Must conditionally verify that succeeding content blocks will render
> before printing visual formatting elements like horizontal separators.
>
> **What:** Structural visual elements, such as horizontal separators or
> newlines, must only be printed if the succeeding content block is actually
> verified to render.
>
> **Applies To:** CLI output rendering logic.
>
> **Why:** Output formatting logic printed hardcoded line separators after
> summaries, resulting in dangling visual artifacts when subsequent project
> details were dynamically excluded by user flags. Failing to adhere to this
> typically results in **Redundant Output Noise**.

**Trap 1: Hardcoding visual formatting elements directly after a primary block
instead of conditionally checking the next block.**

**Don't:**

```python
print_summary()
print_separator()
if include_projects:
    print_projects()
```

**Do:**

```python
print_summary()
if not include_projects:
    return
print_separator()
print_projects()
```

--------------------------------------------------------------------------------

#### T6-05: Output Format Standardization via Enums

> **Rule:** Must manage and standardize target output formats using an explicit
> Python `Enum` class rather than brittle string matching.
>
> **What:** Command-line output formats (like TEXT or JSON) must be managed
> using an explicit Python Enum class and standardize formatting behaviors
> (e.g., disabling pagers for JSON, enforcing sort keys).
>
> **Applies To:** CLI data serialization and `OutputFormat` dispatching.
>
> **Why:** Unstandardized JSON serialization methods across subcommands resulted
> in inconsistent output spacing, failure to suppress interactive pagers, and
> brittle string-based format matching. Failing to adhere to this typically
> results in **Broken Machine Automation**.

**Trap 1: Handling output formatting via raw string matching and `print()`
statements without suppressing the interactive pager.**

**Don't:**

```python
if opt.format == "json":
    print(json.dumps(data))
```

**Do:**

```python
class OutputFormat(enum.Enum):
    TEXT = enum.auto()
    JSON = enum.auto()

if output_format == OutputFormat.JSON:
    sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
```

--------------------------------------------------------------------------------

#### T6-06: Symmetric Execution Dispatching

> **Rule:** Must symmetrically separate procedural logic into format-specific
> handlers rather than mixing inline logic with format conditional statements.
>
> **What:** Complex commands handling multiple output formats must keep the main
> execution function clean by symmetrically dispatching logic to format-specific
> handlers (e.g., `_ExecuteText` and `_ExecuteJson`).
>
> **Applies To:** Command entry points (e.g., the `Execute` method in subcommand
> classes).
>
> **Why:** Inline output rendering mixed with conditional format dispatching
> created monolithic execution methods that were difficult to maintain and test.
> Failing to adhere to this typically results in **Spaghetti Logic**.

**Trap 1: Mixing one output format's dispatch call with the inline procedural
logic of the fallback format.**

**Don't:**

```python
def Execute(self, opt, args):
    if opt.format == 'json':
        return self._ExecuteJson(opt, args)
    # 50 lines of inline text rendering logic...
```

**Do:**

```python
def Execute(self, opt, args):
    if opt.format == OutputFormat.JSON:
        self._ExecuteJson(opt, args)
    else:
        self._ExecuteText(opt, args)
```

--------------------------------------------------------------------------------

#### T6-07: CLI Argument Simulation over Internal State Mutation

> **Rule:** Always inject simulated execution parameters into the command-line
> `argv` arguments list rather than manually overwriting parsed attribute states
> during tests.
>
> **What:** When executing a command programmatically within a test, operational
> parameters (e.g., job counts) must be injected into the simulated `argv`
> string list rather than manually mutating the parsed options object.
>
> **Applies To:** Command testing and execution harnesses where parameters alter
> system behavior (e.g., multiprocessing threads).
>
> **Why:** Test cases were bypassing the CLI parser and manually setting
> `opts.jobs = 1` to force single-threaded execution. This prevented the test
> from exercising the command's full option-parsing and validation lifecycle.
> Failing to adhere to this typically results in **Test Invalidation / False
> Positives**.

**Trap 1: Overriding a configuration parameter directly on the parsed namespace
object.**

**Don't:**

```python
opts, args = cmd.OptionParser.parse_args(argv)
cmd.CommonValidateOptions(opts, args)
opts.jobs = 1
cmd.Execute(opts, args)
```

**Do:**

```python
opts, args = cmd.OptionParser.parse_args(argv + ["--jobs=1"])
cmd.CommonValidateOptions(opts, args)
cmd.Execute(opts, args)
```

--------------------------------------------------------------------------------

#### T6-08: Deterministic Sorting of Parallel Execution Results

> **Rule:** Must explicitly sort accumulated payload data from asynchronous
> thread loops before broadcasting standard outputs or logs.
>
> **What:** Elements collected asynchronously from a multiprocessing pool must
> be explicitly sorted before being emitted to standard output or logging
> pipelines.
>
> **Applies To:** Command-line output rendering and any loop iterating over
> aggregated parallel results.
>
> **Why:** Warning messages regarding bloated project directories were printed
> based on the order that asynchronous threads returned their payload, leading
> to flaky UX and non-deterministic command outputs. Failing to adhere to this
> typically results in **Non-Deterministic Console Output**.

**Trap 1: Iterating over a list of accumulated multi-process results without
sorting.**

**Don't:**

```python
for project_name in self._bloated_projects:
    logger.warning(f'warning: Project {project_name} is bloated.')
```

**Do:**

```python
for project_name in sorted(self._bloated_projects):
    logger.warning(f'warning: Project {project_name} is bloated.')
```

--------------------------------------------------------------------------------

#### T6-09: Strict Adherence to Feature Requests

> **Rule:** Never implement speculative bypass flags, preemptive CLI overrides,
> or configurations without a documented and verifiable user request.
>
> **What:** Avoid preemptively implementing fallback features, command-line
> overrides, or configurations without a documented user request.
>
> **Applies To:** CLI argument parsers and manifest parsing engines.
>
> **Why:** Speculative feature additions, like bypass flags for manifest limits,
> caused feature creep and bloated the CLI toolset with unused, undocumented
> edge cases. Failing to adhere to this typically results in **Feature Creep**.

**Trap 1: Adding a `--force-jobs` CLI bypass flag simultaneously alongside the
new `sync-j-max` manifest attribute.**

**Don't:**

*   Implementing an override flag in `main.py` just in case users want to bypass
    the newly added manifest restriction.

**Do:**

*   Deploying the manifest constraint directly without a CLI override, and
    documenting it in `docs/manifest-format.md`. Wait for a bug tracker request
    for an override flag.

--------------------------------------------------------------------------------

#### T6-10: Minimal Logic in Exception Handlers

> **Rule:** Must restrict `try...except` blocks entirely to targeted error
> handling and never bury structural flow control or terminal loops within them.
>
> **What:** Exception handling blocks (`try...except`) must only contain the
> specific error-handling logic and never encapsulate complex business logic,
> terminal loops, or major execution routing.
>
> **Applies To:** Command dispatcher routing and system control flows.
>
> **Why:** Burying significant CLI routing tasks—like spelling suggestions,
> autocorrection countdowns, and subprocess recursion—inside a `KeyError`
> handler obscured program logic and suppressed nested tracebacks. Failing to
> adhere to this typically results in **Opaque Routing State**.

**Trap 1: Placing the entire typo-correction logic, user prompts, and command
reloading inside `except KeyError:`.**

**Don't:**

```python
try:
    cmd = self.commands[name]()
except KeyError:
    # 50 lines of complex autocorrection logic
    return self._RunLong(...)
```

**Do:**

```python
if name not in self.commands:
    name = self._autocorrect_command_name(name)
    if not name:
        return 1
# Execute minimal command logic outside exception
cmd = self.commands[name]()
```

--------------------------------------------------------------------------------

#### T6-11: Unified Logging Protocol via Standard Logger

> **Rule:** Dispatch all console messages using the standard centralized logging
> framework. Never rely on raw `print` statements mapped directly to terminal
> error streams.
>
> **What:** All console outputs must be dispatched via the system's centralized
> `RepoLogger` mechanism, completely replacing raw terminal standard-error
> prints.
>
> **Applies To:** CLI presentation logic and application-wide console
> communications.
>
> **Why:** The use of raw `print(file=sys.stderr)` bypassed the system's unified
> logging configuration, resulting in unformatted outputs and broken terminal
> interactivity. Failing to adhere to this typically results in **Unmanaged
> Output Spillage**.

**Trap 1: Outputting warnings directly to the `sys.stderr` stream using the
built-in `print` function.**

**Don't:**

```python
print(f"WARNING: You called a command named '{name}'", file=sys.stderr)
```

**Do:**

```python
logger.warning("You called a repo command named '%s'", name)
```

**Exceptions:** Prompts that require strict, synchronously unformatted
interaction via `input()`.

--------------------------------------------------------------------------------

#### T6-12: Strict Translation of Configuration Booleans

> **Rule:** Always cast string-based Git configurations to lowercase and map
> them strictly against Git's recognized array of boolean equivalents.
>
> **What:** Parsers querying Git configuration properties must implement strict
> hardcoding to safely capture Git's expansive list of non-standard boolean
> string representations (e.g., 'yes', 'on', 'true', 'off').
>
> **Applies To:** Configuration parsers mapping user `git config` state to
> internal state variables.
>
> **Why:** Using standard integer casts on retrieved git configuration strings
> caused runtime failures when users specified string-based boolean values
> sanctioned by the official Git system. Failing to adhere to this typically
> results in **Configuration Casting Panic**.

**Trap 1: Wrapping string-typed configuration variables inside `int()` and
catching value exceptions to deduce defaults.**

**Don't:**

```python
try:
    autocorrect = int(autocorrect)
except ValueError:
    autocorrect = 0
```

**Do:**

```python
autocorrect = str(autocorrect).lower()
if autocorrect in ("0", "false", "off", "no", "show"):
    autocorrect = 0
elif autocorrect in ("1", "true", "on", "yes", "immediate"):
    autocorrect = -1
```

--------------------------------------------------------------------------------

#### T6-13: Interruptibility of Interactive Runtime Delays

> **Rule:** Must wrap artificially injected execution delays in handlers that
> correctly detect and gracefully back out of operations upon a keyboard
> interrupt signal.
>
> **What:** Any thread-blocking delay generated by the system (e.g.,
> autocorrection warning timers) must actively handle thread interrupt signals
> so users can gracefully cancel impending state mutations.
>
> **Applies To:** Thread blocks, specifically interactive or automated execution
> delays.
>
> **Why:** Forced sequential time sleeps preceding an automated command
> execution trapped users. If a user detected an erroneous correction during the
> sleep interval, initiating a keyboard interrupt would fail to abort execution,
> resulting in destructive command routing. Failing to adhere to this typically
> results in **Irrevocable Execution**.

**Trap 1: Placing raw time suspension code before a return statement without
wrapping it in a trap for cancellation overrides.**

**Don't:**

```python
time.sleep(delay)
return assumed_command
```

**Do:**

```python
try:
    time.sleep(delay)
except KeyboardInterrupt:
    return None
return assumed_command
```

--------------------------------------------------------------------------------

#### T6-14: Strict Pre-Access Initialization of CLI Options

> **Rule:** Never retrieve attributes from a parsed options namespace until the
> shared subcommand option validation layer has fully completed processing.
>
> **What:** Command-line option attributes (e.g., `copts.verbose`) must strictly
> be accessed only after the options object has fully passed through the common
> subcommand validation layer.
>
> **Applies To:** CLI entry points (`main.py`) and option routing blocks.
>
> **Why:** Accessing attributes on the configuration options object prior to
> invoking `CommonValidateOptions` (which populates global defaults) resulted in
> `AttributeError` crashes, completely breaking primary application functions
> like `repo sync`. Failing to adhere to this typically results in
> **AttributeError / Process Crash**.

**Trap 1: Consuming CLI option flags before the shared initialization pipeline
populates default properties.**

**Don't:**

```python
git_trace2_event_log.verbose = copts.verbose
cmd.CommonValidateOptions(copts, cargs)
cmd.ValidateOptions(copts, cargs)
```

**Do:**

```python
cmd.CommonValidateOptions(copts, cargs)
cmd.ValidateOptions(copts, cargs)
git_trace2_event_log.verbose = copts.verbose
```

--------------------------------------------------------------------------------

#### T6-15: Omission of Redundant Optparse Destinations

> **Rule:** Avoid manually injecting `dest=` bindings in argument declarations
> if the implicit destination perfectly mirrors the target variable name.
>
> **What:** Do not explicitly pass `dest=` arguments in CLI option definitions
> if the value identically matches `optparse`'s implicit fallback behavior
> (which strips leading dashes and replaces inner dashes with underscores).
>
> **Applies To:** Command-line argument definitions using the `optparse` library
> within `subcmds/`.
>
> **Why:** Developers repeatedly specified `dest=` overrides that exactly
> mirrored the auto-generated variable name, adding unnecessary boilerplate and
> triggering automated regression test failures. Failing to adhere to this
> typically results in **Code Bloat / Test Failure**.

**Trap 1: Redundantly configuring destination variables in CLI arguments.**

**Don't:**

```python
p.add_option(
    "--no-interleaved",
    dest="no_interleaved",
    action="store_false",
)
```

**Do:**

```python
p.add_option(
    "--no-interleaved",
    action="store_false",
)
```

--------------------------------------------------------------------------------

#### T6-16: Subcommand Scoping in Commit Messages

> **Rule:** Always prefix your commit messages with the explicit CLI subcommand
> or modular subsystem the patch directly targets.
>
> **What:** Git commit message subject lines must explicitly scope changes to
> the CLI subcommand or module they affect (e.g., `sync: ` or `project: `).
>
> **Applies To:** Commit message authoring.
>
> **Why:** Vague commit messages such as 'Default to interleaved mode'
> obfuscated history. Scoping was mandated to ensure maintainers could quickly
> trace changes within the mono-repo. Failing to adhere to this typically
> results in **Unclear Git History**.

**Trap 1: Writing global-sounding commit messages for isolated subcommand
patches.**

**Don't:**

*   Default to interleaved mode

**Do:**

*   sync: Default to interleaved mode

**Exceptions:** Changes that structurally alter the core framework or affect
multiple commands concurrently.

--------------------------------------------------------------------------------

#### T6-17: Module-Scoped Exception Naming

> **Rule:** Declare isolated module exceptions natively as `Error` instead of
> prefixing them with the resident module's name.
>
> **What:** Custom exceptions specific to a module (especially subcommands)
> should be named `Error` rather than prefixing them with the module name.
>
> **Applies To:** Module-level exception definitions, specifically within
> subcommand implementations.
>
> **Why:** Developers inconsistently named module exceptions (e.g., `WipeError`
> in `wipe.py`), violating the style guide and polluting the namespace upon
> import. Failing to adhere to this typically results in **Style Guide Violation
> / API Inconsistency**.

**Trap 1: Redundantly prefixing the exception name with the module name inside
the module definition.**

**Don't:**

```python
# inside wipe.py
class WipeError(RepoExitError):
    pass
```

**Do:**

```python
# inside wipe.py
class Error(RepoExitError):
    pass
```

--------------------------------------------------------------------------------

#### T6-18: Explicit Terminology in Destructive CLI Commands

> **Rule:** Must rigorously define nuanced Git terminology natively within the
> terminal help output if a command has destructive capabilities.
>
> **What:** Destructive commands must clearly define ambiguous terms (like
> 'worktree') in their help documentation and provide concrete usage examples.
>
> **Applies To:** CLI help text, specifically `helpDescription` properties in
> `Command` subclasses executing file deletion.
>
> **Why:** Users misunderstood destructive operations because terminology
> overlapped with internal Git jargon, increasing the risk of accidental
> repository deletions. Failing to adhere to this typically results in
> **Accidental Data Loss**.

**Trap 1: Using terms like 'worktree' in help text without explicit definition
or examples.**

**Don't:**

*   helpDescription = "The repo wipe command removes the specified projects from
    the worktree."

**Do:**

*   helpDescription = "The repo wipe command removes the specified projects from
    the worktree (the checked out source code)... \n\nExamples:\n %prog
    <project>..."

--------------------------------------------------------------------------------

#### T6-19: Fail-Fast Argument Validation in Subcommands

> **Rule:** Must perform strict threshold checks for required argument counts at
> the validation layer before the command is permitted to execute.
>
> **What:** Validation checks for mandatory command-line arguments must occur in
> the `ValidateOptions` hook rather than within the core `Execute` block.
>
> **Applies To:** All `Command` subclasses.
>
> **Why:** Performing validation in the execution body delayed error feedback,
> triggering unnecessary setup logic and violating the command lifecycle
> architecture. Failing to adhere to this typically results in **Delayed
> Execution Errors / Architectural Inconsistency**.

**Trap 1: Checking for missing positional arguments directly inside
`Execute()`.**

**Don't:**

```python
def Execute(self, opt, args):
    if not args:
        raise UsageError("no projects specified")
    # ... execution logic
```

**Do:**

```python
def ValidateOptions(self, opt, args):
    if not args:
        self.OptionParser.error("no projects specified")

def Execute(self, opt, args):
    # ... execution logic safely assumes valid args
```

--------------------------------------------------------------------------------

#### T6-20: Respect Global Verbosity Flags

> **Rule:** Always wrap non-critical progress prints or logging updates behind
> global verbosity checks.
>
> **What:** Commands must remain silent by default. Output must be guarded by
> checking the global `opt.verbose` flag, preventing log noise during standard
> execution.
>
> **Applies To:** All `Command` subclasses executing file operations or progress
> updates.
>
> **Why:** Commands were unconditionally printing internal states (e.g.,
> directory deletions), cluttering terminal output for users expecting standard
> silent behavior. Failing to adhere to this typically results in **Terminal
> Spam / UX Degradation**.

**Trap 1: Unconditionally printing progress messages to stderr or stdout.**

**Don't:**

```python
print(f"Deleting objects directory: {objdir}", file=sys.stderr)
```

**Do:**

```python
if opt.verbose:
    print(f"Deleting objects directory: {objdir}", file=sys.stderr)
```

--------------------------------------------------------------------------------

#### T6-21: Thread-Safe Terminal Querying during IO Capture

> **Rule:** Must query terminal geometry using a safely cached baseline file
> descriptor to prevent crash failures when the standard error stream is
> redirected to memory buffers.
>
> **What:** Background threads that query terminal properties (like width) must
> reference a persistently cached file descriptor of the original `sys.stderr`,
> as the global stream can be temporarily redirected to in-memory objects
> lacking file descriptors.
>
> **Applies To:** progress.py, UI monitoring loops, and subprocesses executed
> during `stderr`/`stdout` redirection.
>
> **Why:** When running parallel processes that captured output into an
> `io.StringIO()` buffer, a background progress thread attempting to dynamically
> measure the terminal width via `sys.stderr.fileno()` triggered an
> `io.UnsupportedOperation: fileno` exception, crashing the entire UI loop.
> Failing to adhere to this typically results in **Thread Crash /
> io.UnsupportedOperation**.

**Trap 1: Directly querying `sys.stderr.fileno()` inside long-running concurrent
loops.**

**Don't:**

```python
# BAD: Fails if stderr is mocked to memory
col = os.get_terminal_size(sys.stderr.fileno()).columns
```

**Do:**

```python
# GOOD: Querying a module-level cached reference mapped at boot
col = os.get_terminal_size(_STDERR.fileno()).columns
```

--------------------------------------------------------------------------------

#### T6-22: Global State via Persistent Configuration over Environment Variables

> **Rule:** Never propagate novel OS-level environment variables to modify
> executable behavior, strictly enforcing the existing `.repoconfig/config`
> framework instead.
>
> **What:** Global user or CI settings (e.g., Git-LFS defaults) must be managed
> using the explicit `.repoconfig/config` framework. Do not introduce novel
> OS-level environment variables to modify executable behavior.
>
> **Applies To:** Configuration parsers, command-line argument mapping, and
> option handlers across the CLI.
>
> **Why:** A contributor attempted to add a `REPO_GIT_LFS` environment variable
> to ease CI automation. Maintainers rejected the patch, citing that the
> proliferation of disjointed environment variables builds technical debt
> compared to maintaining a single, consistent file-based configuration layer.
> Failing to adhere to this typically results in **Configuration Fragmentation /
> Tech Debt**.

**Trap 1: Adding environment variable mappings into command-line parsers to
support 'headless' configurations.**

**Don't:**

*   Read configuration defaults from `os.environ.get("REPO_GIT_LFS")` alongside
    CLI flags.

**Do:**

*   Instruct users to provision a `~/.repoconfig/config` file in automated
    setups instead of changing process environment logic.

**Exceptions:** Legacy environment variables (e.g., `REPO_URL`) remain supported
for backward compatibility but are explicitly designated as technical debt.

--------------------------------------------------------------------------------

#### T6-23: CLI Command Parity with Git Semantics

> **Rule:** Tightly bind local CLI utility semantics and argument definitions to
> match analogous Git operations explicitly.
>
> **What:** Internal CLI command responsibilities and user-facing terminology
> must align with established Git semantics and project-wide conventions.
>
> **Applies To:** Command-line interface modules (e.g., `subcmds/status.py`,
> `subcmds/info.py`).
>
> **Why:** Global metadata (like superproject commit IDs) was mistakenly added
> to `repo status`, which cluttered the local working-tree status. Additionally,
> the term 'hash' was used instead of the standard 'revision'. Failing to adhere
> to this typically results in **UX Inconsistency / Clutter**.

**Trap 1: Adding project-wide or environmental metadata queries to commands
designed for local working-tree analysis.**

**Don't:**

*   Injecting global repository state (e.g., `--superproject-hash`) into the
    `status` command, which breaks parity with `git status`.

**Do:**

*   Relocating environmental and global metadata display to the `info` command,
    integrating it cleanly into the default summary header.

**Trap 2: Using non-standard terminology for Git object identifiers in
user-facing CLI flags.**

**Don't:**

```python
# BAD: Using 'hash' which is inconsistent with existing repo terminology
p.add_option("--superproject-hash", help="print the superproject hash")
```

**Do:**

```python
# GOOD: Using 'revision'
p.add_option("--superproject-rev", help="print the superproject revision")
```

--------------------------------------------------------------------------------

#### T6-24: Context-Aware Sync Operation Termination

> **Rule:** Must catch and defer local sync iteration failures gracefully rather
> than forcing immediate unrecoverable exits across all active streams.
>
> **What:** Non-critical update failures during local sync iterations must set
> an error flag but must only force a hard exit if the user explicitly provided
> the `--fail-fast` CLI argument.
>
> **Applies To:** All local project iteration workflows within
> `subcmds/sync.py`.
>
> **Why:** A single project failing an isolated sub-task (like a symlink update)
> would immediately trigger `sys.exit(1)`, aborting the entire pipeline for all
> other projects and ignoring standard error aggregation strategies. Failing to
> adhere to this typically results in **Premature Pipeline Termination**.

**Trap 1: Triggering an immediate system exit on an update failure.**

**Don't:**

```python
if self.UpdateCopyLinkfileList():
  print('\nerror: Local update copyfile or linkfile failed.', file=sys.stderr)
  sys.exit(1)
```

**Do:**

```python
if not self.UpdateCopyLinkfileList():
  err_event.set()
  err_update_linkfiles = True
  if opt.fail_fast:
    print('\nerror: Local update copyfile or linkfile failed.', file=sys.stderr)
    sys.exit(1)
```

--------------------------------------------------------------------------------

#### T6-25: Explicit Exit Codes on CLI Cancellation

> **Rule:** Always force the process to yield a non-zero exit code if an
> interactive confirmation prompt is declined or cancelled.
>
> **What:** Interactive CLI workflows that are cancelled or declined by the user
> must immediately return a non-zero exit code to signal termination to parent
> processes.
>
> **Applies To:** All interactive subcommands (`gc`, `sync` with prompts, etc.).
>
> **Why:** If a tool cleanly exited (returning None / 0) after a user denied a
> destructive action prompt, shell automation wrappers and CI systems falsely
> assumed the destructive cleanup successfully completed. Failing to adhere to
> this typically results in **Silent Automation Failure**.

**Trap 1: Using an empty `return` to back out of a declined CLI confirmation
prompt.**

**Don't:**

```python
ask = input("Proceed? [y/N] ")
if ask.lower() != "y":
    return
```

**Do:**

```python
ask = input("Proceed? [y/N] ")
if ask.lower() != "y":
    return 1
```

--------------------------------------------------------------------------------

#### T6-26: Non-Interactive Safeties for Destructive Commands

> **Rule:** Must implement explicit automation bypass flags for any command
> capable of irreversibly destroying system state.
>
> **What:** Any command capable of destroying state (e.g., garbage collection,
> wiping local commits) must provide both a `--dry-run` and a `--yes` (or
> `--force`) flag to support safe CI automation.
>
> **Applies To:** Command-line definitions for potentially destructive
> operations.
>
> **Why:** Tools that rely exclusively on `input()` prompts block automated
> scripts indefinitely. By explicitly enforcing non-interactive modes, scripts
> can safely trigger automated cleanups or log dry-runs without freezing.
> Failing to adhere to this typically results in **Automation Hang / CI Pipeline
> Freeze**.

**Trap 1: Hardcoding interactive prompts without checking configuration flags
for automation modes.**

**Don't:**

*   Prompting the user with `input('Proceed?')` unconditionally before executing
    a destructive delete.

**Do:**

*   Checking `if opt.dry_run:` to skip execution, or `if opt.yes:` to skip the
    confirmation prompt.

--------------------------------------------------------------------------------

#### T6-27: Strict Interdependent Argument Validation

> **Rule:** Always enforce strict prerequisites checks when parsing command-line
> flags intended to modify or inherit context from other flags.
>
> **What:** Command-line options that exist solely to modify or qualify another
> specific command-line option must be explicitly validated to raise an error if
> their prerequisite option is absent.
>
> **Applies To:** CLI argument parsing routines (`subcmds/init.py`,
> `ValidateOptions`).
>
> **Why:** A new `--manifest-upstream-branch` argument was added to qualify a
> provided commit hash. However, without strict validation, users could supply
> it independently, leading to ambiguous or unhandled configuration states.
> Failing to adhere to this typically results in **CLI Ambiguity / Unhandled
> Option State**.

**Trap 1: Accepting dependent modifier options unconditionally without checking
prerequisites.**

**Don't:**

*   Accepting `--manifest-upstream-branch` in the CLI parser and directly
    assigning it to the internal state regardless of the presence of
    `--manifest-branch`.

**Do:**

*   Explicitly checking the parsed options and raising an `OptionParser.error`
    if the modifier is present but the target `--manifest-branch` is null.

--------------------------------------------------------------------------------

#### T6-28: Actionable CLI Error Messages for Synchronization Failures

> **Rule:** Embed direct, explicit commands and flag references within terminal
> error payloads to rescue users from failing execution states.
>
> **What:** When a terminal failure occurs during CLI operations, the error
> payload must provide specific, actionable flags or manual steps for the user
> to resolve the failing state.
>
> **Applies To:** Sync command error reporting (`subcmds/sync.py`,
> `project.py`).
>
> **Why:** When a local branch had published commits but was behind upstream,
> the sync failed with a generic 'punt' message, leaving users unaware that
> passing `--rebase` could force the sync. Failing to adhere to this typically
> results in **User Friction / Dead End**.

**Trap 1: Failing a sync operation with a descriptive but non-actionable error
message.**

**Don't:**

```python
fail(LocalSyncFail(
    "branch %s is published (but not merged) and is now %d commits behind"
    % (branch.name, len(upstream_gain)),
    project=self.name,
))
```

**Do:**

```python
fail(LocalSyncFail(
    "branch %s is published (but not merged) and is now %d commits behind. "
    "Fix this manually or rerun with the --rebase option to force a rebase."
    % (branch.name, len(upstream_gain)),
    project=self.name,
))
```

--------------------------------------------------------------------------------

#### T6-29: Launcher Script Version Upgrades for Important Changes

> **Rule:** Increment the `VERSION` tuple within the standalone `repo` launcher script when making important or significant functional changes.
>
> **What:** If you modify the standalone `repo` launcher file with an important or large change (e.g., updates to Python version checks, significant logic fixes, or major argument parsing updates), you must increment the `VERSION = (X, Y)` tuple.
>
> **Applies To:** Standalone `repo` launcher script, release engineering workflows.
>
> **Why:** The repo source code entry point (`main.py`) compares the runner wrapper version to the copy of the launcher in the source tree to prompt users to upgrade. If an important launcher modification is submitted without a corresponding version bump, users executing older wrappers won't receive the required update prompts. Failing to adhere to this typically results in **Launcher Version Skew / Missing Update Warnings**.
>
> **Exceptions:** Minor or cosmetic changes (like fixing typos in comments or minor docstrings) do not require a version bump.

**Trap 1: Submitting a major or important patch to the `repo` launcher script without updating its `VERSION` definition.**

**Don't:**

```python
# Making significant changes to Python version handling logic
# but leaving VERSION unchanged:
VERSION = (2, 65)
```

**Do:**

```python
# Incrementing the minor version tuple to signal the update:
VERSION = (2, 66)
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T1 | Concurrent Synchronization & IPC - *CLI rendering relies
    on sorted, deterministic results emitted from asynchronous multiprocessing
    pools.*
*   **Downstream:** T3 | Subprocess Git Integration & Error Translation -
    *Command-line terminology and state configurations must tightly align with
    wrapped Git subprocess semantics.*

## Chapter: Repo Hooks Framework

**Context:** The Repo Hooks Framework governs the execution, parameter
validation, and lifecycle management of user-defined scripts within the
repository ecosystem. It ensures seamless integration of extensions like
`post-sync` or `pre-upload` while strictly isolating their execution failures
from core operational workflows.

### Summary

| Rule ID   | Principle /        | Priority | Primary Symptom / Trap           |
:           : Constraint         :          :                                  :
| :-------- | :----------------- | :------- | :------------------------------- |
| **T7-01** | Explicit           | Critical | Passing a new variable to        |
:           : Registration of    :          : `hook.Run()` without             :
:           : Hook Parameters in :          : whitelisting it in the           :
:           : API Contract       :          : `_API_ARGS` map.                 :
| **T7-02** | Floating-Point     | High     | Casting float calculations       |
:           : Precision for Hook :          : directly to integers before      :
:           : Telemetry Metrics  :          : passing to downstream systems.   :
| **T7-03** | Non-Blocking       | High     | Using raw `subprocess` calls to  |
:           : Post-Sync Hook     :          : run custom scripts and tying the :
:           : Integration        :          : command's exit code to the main  :
:           :                    :          : tool's exit code.                :
| **T7-04** | Dynamic CLI Option | Medium   | Bypassing standard option        |
:           : Injection for Repo :          : parsers by passing a mock object :
:           : Hooks              :          : with hardcoded values into hook  :
:           :                    :          : factory methods.                 :
| **T7-05** | Boolean Evaluation | High     | Wrapping a framework execution   |
:           : for Repo Hook      :          : method in a generic exception    :
:           : Execution Status   :          : handler.                         :
| **T7-06** | Universal Trigger  | High     | Documenting hook triggers based  |
:           : Specification for  :          : on an idealized use-case (a full :
:           : Execution          :          : checkout) rather than the        :
:           : Lifecycle          :          : literal programmatic trigger.    :
| **T7-07** | Forward-Compatible | High     | Defining a hook entrypoint with  |
:           : kwargs for Repo    :          : a strict argument list that      :
:           : Hooks Signatures   :          : cannot gracefully handle new     :
:           :                    :          : inputs.                          :

--------------------------------------------------------------------------------

### Rules

#### T7-01: Explicit Registration of Hook Parameters in API Contract

> **Rule:** Always register new metadata or arguments intended for user-defined
> lifecycle scripts within the internal `_API_ARGS` validation dictionary.
>
> **What:** Any new metadata or argument passed into user-defined lifecycle
> scripts must be explicitly defined in the hook's internal validation
> dictionary (`_API_ARGS`).
>
> **Applies To:** Repo Hooks Framework (`hooks.py` and Hook Runners).
>
> **Why:** New arguments sent to the post-sync execution context triggered
> internal exceptions because the core application strictly validates `**kwargs`
> against a registered list of supported arguments. Failing to adhere to this
> typically results in **Runtime Hook Failure**.

**Trap 1: Passing a new variable to `hook.Run()` without whitelisting it in the
`_API_ARGS` map.**

**Don't:**

```python
# In subcmds/sync.py
hook.Run(repo_topdir=self.client.topdir, sync_duration_seconds=dur)

# In hooks.py (Missing registration)
_API_ARGS = {
    'post-sync': {'repo_topdir'}
}
```

**Do:**

```python
# In hooks.py
_API_ARGS = {
    'post-sync': {'repo_topdir', 'sync_duration_seconds'}
}
```

#### T7-02: Floating-Point Precision for Hook Telemetry Metrics

> **Rule:** Must pass system telemetry and operational duration metrics to
> downstream extension hooks as precise floating-point values.
>
> **What:** System telemetry, specifically operational duration metrics, must be
> passed to downstream extension hooks as granular floating-point values. The
> executing system must not truncate or cast telemetry to integers.
>
> **Applies To:** Performance telemetry generation and hook contexts.
>
> **Why:** Internal performance timers originally cast their delta outputs to
> integers before emitting the context to the hook system. This caused a loss of
> sub-second precision, limiting telemetry usefulness. Failing to adhere to this
> typically results in **Telemetry Data Loss**.

**Trap 1: Casting float calculations directly to integers before passing to
downstream systems.**

**Don't:**

```python
sync_duration_seconds = time.time() - start_time
self._RunPostSyncHook(opt, sync_duration_seconds=int(sync_duration_seconds))
```

**Do:**

```python
sync_duration_seconds = time.time() - start_time
self._RunPostSyncHook(opt, sync_duration_seconds=sync_duration_seconds)
```

#### T7-03: Non-Blocking Post-Sync Hook Integration

> **Rule:** Never allow post-operation custom hooks to block or alter the
> success state of the core operation.
>
> **What:** Custom hooks executed strictly after an operation finishes (like
> `post-sync`) must run via the encapsulated `RepoHook` framework and be
> entirely non-blocking, so their failure does not negatively affect the core
> operation's recorded success state.
>
> **Applies To:** subcmds/sync.py and `RepoHook` integrations executing after
> repository data modifications.
>
> **Why:** Teams needed a reliable way to provision local Git `commit-msg` hooks
> even if developers bypassed `repo upload` with manual `git push`. A
> `post-sync` hook was added, but the rigid requirement was that if the user
> script failed, the actual project synchronization must still report as a
> success to avoid corrupting UX. Failing to adhere to this typically results in
> **Blocked Sync Operations**.

**Trap 1: Using raw `subprocess` calls to run custom scripts and tying the
command's exit code to the main tool's exit code.**

**Don't:**

```python
# BAD: Post-action failure corrupts the sync outcome
if subprocess.run(["run_hooks.sh"]).returncode != 0:
    raise SyncError("Hook failed")
```

**Do:**

```python
# GOOD: Managed execution safely wrapping and suppressing exceptions
hook = RepoHook("post-sync")
hook.Run() # Designed strictly to warn on failure
```

#### T7-04: Dynamic CLI Option Injection for Repo Hooks

> **Rule:** Always utilize the RepoHook option group injection framework for
> command-line integration rather than synthesizing dummy configuration objects.
>
> **What:** Command-line integration for new hooks must utilize the RepoHook
> option group injection framework rather than synthesizing dummy configuration
> objects.
>
> **Applies To:** Repo Hooks Framework; specifically subcommand definitions
> involving hook invocations (e.g., `subcmds/sync.py`).
>
> **Why:** When integrating the post-sync hook, a developer initially created a
> minimal 'DummyOpt' object to satisfy parameter checks because the sync command
> lacked native hook flags. This diverged from standard hook architecture and
> could cause attribute errors. Failing to adhere to this typically results in
> **AttributeError / Option Divergence**.

**Trap 1: Bypassing standard option parsers by passing a mock object with
hardcoded values into hook factory methods.**

**Don't:**

```python
# BAD: Using a dummy object to satisfy missing CLI arguments
class DummyOpt:
    bypass_hooks = False
    allow_all_hooks = True
    ignore_hooks = True

hook = RepoHook.FromSubcmd(opt=DummyOpt(), ...)
```

**Do:**

```python
# GOOD: Injecting the standard hook option group into the parser
RepoHook.AddOptionGroup(parser, 'post-sync')

# Later during execution, pass the actual resolved options:
hook = RepoHook.FromSubcmd(opt=actual_opt, ...)
```

#### T7-05: Boolean Evaluation for Repo Hook Execution Status

> **Rule:** Always evaluate hook execution success using the boolean return
> value of `Run()`, never by wrapping the call in external exception handlers.
>
> **What:** Execution wrappers for Repo Hooks must rely on the boolean return
> value of `Run()` to evaluate success, rather than wrapping the call in broad
> `try/except Exception` blocks.
>
> **Applies To:** Repo Hooks Framework; specifically the invocation layer for
> any hook type (`post-sync`, `pre-upload`).
>
> **Why:** A developer wrapped the hook execution in a broad Exception catch
> block. The hook framework inherently traps and standardizes exceptions
> internally; wrapping it externally duplicates logic, masks context, and leads
> to silent failure processing. Failing to adhere to this typically results in
> **Swallowed Exceptions / Logic Duplication**.

**Trap 1: Wrapping a framework execution method in a generic exception
handler.**

**Don't:**

```python
# BAD: Redundant outer try/except block swallowing state
try:
    hook.Run()
except Exception as e:
    print(f"Warning: hook failed: {e}")
```

**Do:**

```python
# GOOD: Relying on the established boolean return contract
success = hook.Run()
if not success:
    print("Warning: hook reported failure.")
```

#### T7-06: Universal Trigger Specification for Execution Lifecycle

> **Rule:** Must document the exact, literal programmatic triggers for hooks
> rather than relying on idealized use-cases like full checkouts.
>
> **What:** Hook documentation must strictly delineate the exact success states
> that trigger execution, explicitly noting conditions where operational state
> (like a local checkout) might be bypassed or skipped.
>
> **Applies To:** Repo Hooks API contracts and documentation
> (`docs/repo-hooks.md`).
>
> **Why:** Users of the new post-sync hook might assume it only runs after a
> complete workspace checkout. However, it effectively fires on any
> zero-exit-code sync operation, including network-only fetches where the local
> filesystem state remains completely untouched. Failing to adhere to this
> typically results in **State Assumption Bugs**.

**Trap 1: Documenting hook triggers based on an idealized use-case (a full
checkout) rather than the literal programmatic trigger.**

**Don't:**

*   Documenting that the hook is to install post-processing tasks specifically
    for successful full checkouts.

**Do:**

*   Documenting that the hook runs when `repo sync` completes without errors,
    explicitly warning that this does not guarantee all projects were synced or
    checked out (e.g., `repo sync -n` performs network fetches only).

#### T7-07: Forward-Compatible kwargs for Repo Hooks Signatures

> **Rule:** Always design hook script entrypoints to accept variable keyword
> arguments (`**kwargs`) to ensure forward compatibility with future framework
> expansions.
>
> **What:** All repository hook script entrypoints (`main` functions) must
> accept variable keyword arguments (`**kwargs`) to maintain forward
> compatibility with future API augmentations.
>
> **Applies To:** Repo Hooks scripts and internal examples (e.g.,
> `post-sync.py`, `pre-upload.py`).
>
> **Why:** Historically, if the `repo` tool evolved to pass new environmental
> context (like `repo_topdir`), user-defined scripts with strict function
> signatures would crash with a TypeError. Failing to adhere to this typically
> results in **TypeError / API Breakage**.

**Trap 1: Defining a hook entrypoint with a strict argument list that cannot
gracefully handle new inputs.**

**Don't:**

```python
# BAD: Strict signature that will crash on API update
def main(repo_topdir=None):
    print("Running tasks...")
```

**Do:**

```python
# GOOD: Accepts forward-compatible **kwargs
def main(repo_topdir=None, **kwargs):
    """
    Args:
      kwargs: Leave this here for forward-compatibility.
    """
    print("Running tasks...")
```

--------------------------------------------------------------------------------

### Cross-Domain Dependencies

*   **Upstream:** T6 | CLI Argument Parsing & UX Consistency - *The dynamic hook
    injection framework fundamentally relies on standardized option parsers to
    map CLI flags cleanly into hook runner contexts.*
