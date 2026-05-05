#compdef _repo repo

# Copyright (C) 2021 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

_repo() {
    local context state line
    typeset -A opt_args

    local -a subcommands
    subcommands=(
        'abandon:Abandon a development branch'
        'branches:View current topic branches'
        'checkout:Checkout a branch'
        'cherry-pick:Cherry-pick a change'
        'diff:Show changes between commit and working tree'
        'diffmanifests:Show differences between two manifests'
        'download:Download and find a change'
        'forall:Run a shell command in each project'
        'gc:Garbage collect'
        'grep:Print lines matching a pattern'
        'help:Display help about a command'
        'info:Get info about the manifest'
        'init:Initialize a repo client'
        'list:List projects and their names'
        'manifest:Manifest management'
        'overview:Display overview of topic branches'
        'prune:Prune topic branches'
        'rebase:Rebase local branches'
        'selfupdate:Update repo'
        'smartsync:Update working tree to latest known good revision'
        'stage:Stage file(s) for commit'
        'start:Start a new branch for development'
        'status:Show the working tree status'
        'sync:Update working tree'
        'upload:Upload changes to the review server'
        'version:Display version'
        'wipe:Wipe uncommitted changes'
    )

    local -a global_opts
    global_opts=(
        '(-h --help)'{-h,--help}'[Show help message]'
        '--help-all[Show help message for all commands]'
        '(-p --paginate)'{-p,--paginate}'[Pipe all output into less]'
        '--no-pager[Do not pipe output into a pager]'
        '--color=[Control color output]:color:(always never auto)'
        '--trace[Trace git command execution]'
        '--trace-to-stderr[Trace git command execution to stderr]'
        '--trace-python[Trace python execution]'
        '--time[Time execute of command]'
        '--version[Show version]'
        '--show-toplevel[Show top level of workspace]'
        '--event-log=[File to log events to]:file:_files'
        '--git-trace2-event-log=[File to log git trace2 events to]:file:_files'
        '--submanifest-path=[Path to submanifest]:path:_files'
    )

    _arguments -C \
        $global_opts \
        '1: :->cmds' \
        '*:: :->subcmds'

    case $state in
        cmds)
            _describe -t commands 'repo command' subcommands
            ;;
        subcmds)
            local cmd=$words[1]
            curcontext="${curcontext%:*}-$cmd:"
            
            local -a common_opts
            common_opts=(
                '(-h --help)'{-h,--help}'[Show help message]'
                '(-v --verbose)'{-v,--verbose}'[Show verbose messages]'
                '(-q --quiet)'{-q,--quiet}'[Show only errors]'
                '(-j --jobs)'{-j,--jobs=}'[Number of jobs to run in parallel]:jobs:'
                '--outer-manifest[Use outer manifest]'
                '--no-outer-manifest[Do not use outer manifest]'
                '--this-manifest-only[Only use this manifest]'
                '--no-this-manifest-only[Do not only use this manifest]'
                '--all-manifests[Use all manifests]'
            )

            case $cmd in
                abandon)
                    _arguments \
                        $common_opts \
                        '--all[Abandon all branches]' \
                        '1: :->branch' \
                        '*: :->project'
                    ;;
                branches)
                    _arguments \
                        $common_opts \
                        '*: :->project'
                    ;;
                checkout)
                    _arguments \
                        $common_opts \
                        '1: :->branch' \
                        '*: :->project'
                    ;;
                cherry-pick)
                    _arguments \
                        $common_opts \
                        '1: :_message "sha1"'
                    ;;
                diff)
                    _arguments \
                        $common_opts \
                        '(-u --absolute)'{-u,--absolute}'[Show absolute paths]' \
                        '*: :->project'
                    ;;
                diffmanifests)
                    _arguments \
                        '--raw[Show raw diff]' \
                        '--no-color[Do not show color]' \
                        '--pretty-format=[Pretty format]:format:' \
                        '1: :_files -g "*.xml"' \
                        '2: :_files -g "*.xml"'
                    ;;
                download)
                    _arguments \
                        $common_opts \
                        '(-b --branch)'{-b,--branch=}'[One or more branches to check]:branch:' \
                        '(-c --cherry-pick)'{-c,--cherry-pick}'[Cherry-pick the change]' \
                        '(-x --record-origin)'{-x,--record-origin}'[Record origin of cherry-pick]' \
                        '(-r --revert)'{-r,--revert}'[Revert the change]' \
                        '(-f --ff-only)'{-f,--ff-only}'[Force fast-forward]' \
                        '*: :_message "change[/patchset]"'
                    ;;
                forall)
                    _arguments \
                        $common_opts \
                        '(-r --regex)'{-r,--regex}'[Execute command only on projects matching regex]' \
                        '(-i --inverse-regex)'{-i,--inverse-regex}'[Execute command only on projects not matching regex]' \
                        '(-g --groups)'{-g,--groups=}'[Execute command only on projects matching groups]:groups:' \
                        '(-c --command)'{-c,--command}'[Command to execute]' \
                        '(-e --abort-on-errors)'{-e,--abort-on-errors}'[Abort on errors]' \
                        '--ignore-missing[Ignore missing projects]' \
                        '--interactive[Run interactively]' \
                        '-p[Show project headers]' \
                        '*: :->project'
                    ;;
                gc)
                    _arguments \
                        $common_opts \
                        '(-n --dry-run)'{-n,--dry-run}'[Dry run]' \
                        '(-y --yes)'{-y,--yes}'[Answer yes to all prompts]' \
                        '--repack[Repack objects]'
                    ;;
                grep)
                    _arguments \
                        $common_opts \
                        '--cached[Search cached files]' \
                        '(-r --revision)'{-r,--revision=}'[Search in revision]:revision:' \
                        '-e[Pattern]' \
                        '(-i --ignore-case)'{-i,--ignore-case}'[Ignore case]' \
                        '(-a --text)'{-a,--text}'[Treat all files as text]' \
                        '-I[Do not match binary files]' \
                        '(-w --word-regexp)'{-w,--word-regexp}'[Match word boundaries]' \
                        '(-v --invert-match)'{-v,--invert-match}'[Invert match]' \
                        '(-G --basic-regexp)'{-G,--basic-regexp}'[Basic regexp]' \
                        '(-E --extended-regexp)'{-E,--extended-regexp}'[Extended regexp]' \
                        '(-F --fixed-strings)'{-F,--fixed-strings}'[Fixed strings]' \
                        '--all-match[All match]' \
                        '--and[And]' \
                        '--or[Or]' \
                        '--not[Not]' \
                        '-([Open paren]' \
                        '-)[Close paren]' \
                        '-n[Line number]' \
                        '-C[Context]:lines:' \
                        '-B[Before context]:lines:' \
                        '-A[After context]:lines:' \
                        '-l[Name only]' \
                        '--name-only[Name only]' \
                        '--files-with-matches[Files with matches]' \
                        '-L[Files without match]' \
                        '--files-without-match[Files without match]' \
                        '1: :->pattern' \
                        '*: :->project'
                    ;;
                help)
                    _arguments \
                        '(-a --all)'{-a,--all}'[Show all commands]' \
                        '--help-all[Show help message for all commands]' \
                        '1: :->help_cmds'
                    ;;
                info)
                    _arguments \
                        $common_opts \
                        '(-d --diff)'{-d,--diff}'[Show diff]' \
                        '(-o --overview)'{-o,--overview}'[Show overview]' \
                        '(-c --current-branch)'{-c,--current-branch}'[Show current branch]' \
                        '--no-current-branch[Do not show current branch]' \
                        '(-l --local-only)'{-l,--local-only}'[Local only]' \
                        '*: :->project'
                    ;;
                init)
                    _arguments \
                        '(-u --manifest-url)'{-u,--manifest-url=}'[Manifest URL]:url:' \
                        '(-b --manifest-branch)'{-b,--manifest-branch=}'[Manifest branch]:branch:' \
                        '--manifest-upstream-branch=[Manifest upstream branch]:branch:' \
                        '(-m --manifest-name)'{-m,--manifest-name=}'[Manifest name]:file:_files -g "*.xml"' \
                        '(-g --groups)'{-g,--groups=}'[Restrict manifest projects to groups]:groups:' \
                        '(-p --platform)'{-p,--platform=}'[Restrict manifest projects to platform]:platform:' \
                        '--submodules[Sync submodules]' \
                        '--standalone-manifest[Standalone manifest]' \
                        '--manifest-depth=[Manifest depth]:depth:' \
                        '(-c --current-branch)'{-c,--current-branch}'[Sync current branch only]' \
                        '--no-current-branch[Do not sync current branch only]' \
                        '--tags[Sync tags]' \
                        '--no-tags[Do not sync tags]' \
                        '--mirror[Mirror]' \
                        '--archive[Archive]' \
                        '--worktree[Worktree]' \
                        '--reference=[Reference repository]:repository:_files -/' \
                        '--dissociate[Dissociate from reference]' \
                        '--depth=[Depth]:depth:' \
                        '--partial-clone[Partial clone]' \
                        '--no-partial-clone[Do not partial clone]' \
                        '--partial-clone-exclude=[Exclude from partial clone]:projects:' \
                        '--clone-filter=[Clone filter]:filter:' \
                        '--use-superproject[Use superproject]' \
                        '--no-use-superproject[Do not use superproject]' \
                        '--clone-bundle[Use clone bundle]' \
                        '--no-clone-bundle[Do not use clone bundle]' \
                        '--git-lfs[Use git lfs]' \
                        '--no-git-lfs[Do not use git lfs]' \
                        '--repo-url=[Repo URL]:url:' \
                        '--repo-rev=[Repo revision]:revision:' \
                        '--no-repo-verify[Do not verify repo]' \
                        '--config-name[Use config name]'
                    ;;
                list)
                    _arguments \
                        $common_opts \
                        '(-r --regex)'{-r,--regex}'[Filter by regex]' \
                        '(-g --groups)'{-g,--groups=}'[Filter by groups]:groups:' \
                        '(-a --all)'{-a,--all}'[Show all projects]' \
                        '(-n --name-only)'{-n,--name-only}'[Show only names]' \
                        '(-p --path-only)'{-p,--path-only}'[Show only paths]' \
                        '(-f --fullpath)'{-f,--fullpath}'[Show full paths]' \
                        '--relative-to=[Show paths relative to]:path:_files -/' \
                        '*: :->project'
                    ;;
                manifest)
                    _arguments \
                        '(-r --revision-as-HEAD)'{-r,--revision-as-HEAD}'[Save revisions as current HEAD]' \
                        '(-m --manifest-name)'{-m,--manifest-name=}'[Manifest name]:file:_files -g "*.xml"' \
                        '--suppress-upstream-revision[Suppress upstream revision]' \
                        '--suppress-dest-branch[Suppress dest branch]' \
                        '--format=[Output format]:format:(xml json)' \
                        '--pretty[Pretty print]' \
                        '--no-local-manifests[Ignore local manifests]' \
                        '(-o --output-file)'{-o,--output-file=}'[Output file]:file:_files'
                    ;;
                overview)
                    _arguments \
                        $common_opts \
                        '(-c --current-branch)'{-c,--current-branch}'[Show current branch]' \
                        '--no-current-branch[Do not show current branch]' \
                        '*: :->project'
                    ;;
                prune)
                    _arguments \
                        $common_opts \
                        '*: :->project'
                    ;;
                rebase)
                    _arguments \
                        $common_opts \
                        '--fail-fast[Fail fast]' \
                        '(-f --force-rebase)'{-f,--force-rebase}'[Force rebase]' \
                        '--no-ff[No fast forward]' \
                        '--autosquash[Autosquash]' \
                        '--whitespace=[Whitespace option]:option:' \
                        '--auto-stash[Auto stash]' \
                        '(-m --onto-manifest)'{-m,--onto-manifest}'[Rebase onto manifest]' \
                        '(-i --interactive)'{-i,--interactive}'[Interactive rebase]' \
                        '*: :->project'
                    ;;
                selfupdate)
                    _arguments \
                        '--no-repo-verify[Do not verify repo]'
                    ;;
                smartsync|sync)
                    _arguments \
                        $common_opts \
                        '--jobs-network=[Number of network jobs]:jobs:' \
                        '--jobs-checkout=[Number of checkout jobs]:jobs:' \
                        '(-f --force-broken)'{-f,--force-broken}'[Continue sync even if a project fails]' \
                        '--fail-fast[Fail fast]' \
                        '--force-sync[Overwrite existing git directories]' \
                        '--force-checkout[Force checkout]' \
                        '--force-remove-dirty[Force remove dirty]' \
                        '--rebase[Rebase local branches]' \
                        '(-l --local-only)'{-l,--local-only}'[Only use local files]' \
                        '--no-manifest-update[Do not update manifest]' \
                        '--nmu[Do not update manifest]' \
                        '--interleaved[Interleave output]' \
                        '--no-interleaved[Do not interleave output]' \
                        '(-n --network-only)'{-n,--network-only}'[Only fetch]' \
                        '(-d --detach)'{-d,--detach}'[Detach HEAD]' \
                        '(-c --current-branch)'{-c,--current-branch}'[Fetch only current branch]' \
                        '--no-current-branch[Do not fetch only current branch]' \
                        '(-m --manifest-name)'{-m,--manifest-name=}'[Manifest name]:file:_files -g "*.xml"' \
                        '--clone-bundle[Use clone bundle]' \
                        '--no-clone-bundle[Do not use clone bundle]' \
                        '(-u --manifest-server-username)'{-u,--manifest-server-username=}'[Username for manifest server]:username:' \
                        '(-p --manifest-server-password)'{-p,--manifest-server-password=}'[Password for manifest server]:password:' \
                        '--fetch-submodules[Fetch submodules]' \
                        '--use-superproject[Use superproject]' \
                        '--no-use-superproject[Do not use superproject]' \
                        '--tags[Sync tags]' \
                        '--no-tags[Do not sync tags]' \
                        '--optimized-fetch[Optimized fetch]' \
                        '--retry-fetches=[Retry fetches]:count:' \
                        '--prune[Prune]' \
                        '--no-prune[Do not prune]' \
                        '--auto-gc[Run auto gc]' \
                        '--no-auto-gc[Do not run auto gc]' \
                        '(-s --smart-sync)'{-s,--smart-sync}'[Smart sync]' \
                        '(-t --smart-tag)'{-t,--smart-tag=}'[Smart tag]:tag:' \
                        '--no-repo-verify[Do not verify repo]' \
                        '--no-verify[Do not verify]' \
                        '--verify[Verify]' \
                        '--ignore-hooks[Ignore hooks]' \
                        '*: :->project'
                    ;;
                stage)
                    _arguments \
                        $common_opts \
                        '(-i --interactive)'{-i,--interactive}'[Interactive staging]' \
                        '*: :->project'
                    ;;
                start)
                    _arguments \
                        $common_opts \
                        '--all[Start branch in all projects]' \
                        '(-r --rev --revision)'{-r,--rev=,--revision=}'[Revision]:revision:' \
                        '--head[Head]' \
                        '--HEAD[Head]' \
                        '1: :->newbranch' \
                        '*: :->project'
                    ;;
                status)
                    _arguments \
                        $common_opts \
                        '(-o --orphans)'{-o,--orphans}'[Show orphans]' \
                        '*: :->project'
                    ;;
                upload)
                    _arguments \
                        $common_opts \
                        '(-t --topic-branch)'{-t,--topic-branch}'[Topic branch]' \
                        '--topic=[Topic]:topic:' \
                        '--hashtag=[Hashtag]:hashtag:' \
                        '--ht=[Hashtag]:hashtag:' \
                        '--hashtag-branch[Hashtag branch]' \
                        '--htb[Hashtag branch]' \
                        '(-l --label)'{-l,--label=}'[Label]:label:' \
                        '--pd=[Patchset description]:description:' \
                        '--patchset-description=[Patchset description]:description:' \
                        '--re=[Reviewers]:reviewers:' \
                        '--reviewers=[Reviewers]:reviewers:' \
                        '--cc=[CC]:cc:' \
                        '--br=[Branch]:branch:' \
                        '--branch=[Branch]:branch:' \
                        '(-c --current-branch)'{-c,--current-branch}'[Upload current branch]' \
                        '--no-current-branch[Do not upload current branch]' \
                        '--ne[No emails]' \
                        '--no-emails[No emails]' \
                        '(-p --private)'{-p,--private}'[Private]' \
                        '(-w --wip)'{-w,--wip}'[Work in progress]' \
                        '(-r --ready)'{-r,--ready}'[Ready]' \
                        '(-o --push-option)'{-o,--push-option=}'[Push option]:option:' \
                        '(-D --destination --dest)'{-D,--destination=,--dest=}'[Destination]:destination:' \
                        '(-n --dry-run)'{-n,--dry-run}'[Dry run]' \
                        '(-y --yes)'{-y,--yes}'[Answer yes to all prompts]' \
                        '--ignore-untracked-files[Ignore untracked files]' \
                        '--no-ignore-untracked-files[Do not ignore untracked files]' \
                        '--no-cert-checks[Do not check certificates]' \
                        '--no-verify[Do not verify]' \
                        '--verify[Verify]' \
                        '--ignore-hooks[Ignore hooks]' \
                        '*: :->project'
                    ;;
                version)
                    _arguments $common_opts
                    ;;
                wipe)
                    _arguments \
                        $common_opts \
                        '(-f --force)'{-f,--force}'[Force wipe]' \
                        '--force-uncommitted[Force uncommitted]' \
                        '--force-shared[Force shared]' \
                        '*: :->project'
                    ;;
            esac

            # Handle states for positional arguments
            case $state in
                branch)
                    [[ $PREFIX != -* ]] && _repo_branches
                    ;;
                project)
                    [[ $PREFIX != -* ]] && _repo_projects
                    ;;
                pattern)
                    _message 'pattern'
                    ;;
                newbranch)
                    _message 'new branch name'
                    ;;
                help_cmds)
                    _describe -t commands 'repo command' subcommands
                    ;;
            esac
            ;;
    esac
}

_repo_branches() {
    local -a branches
    branches=(${(f)"$(_call_program branches repo branches 2>/dev/null | sed -e 's/^[ *]*//' | awk '{print $1}')"})
    _describe -t branches 'branch' branches
}

_repo_projects() {
    local -a projects
    projects=(${(f)"$(_call_program projects repo list -n 2>/dev/null)"})
    _describe -t projects 'project' projects
}

_repo "$@"

