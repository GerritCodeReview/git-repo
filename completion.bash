# Copyright 2021 The Android Open Source Project
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

# Programmable bash completion.  https://github.com/scop/bash-completion

# Complete the list of repo subcommands.
__complete_repo_list_commands() {
  local repo=${COMP_WORDS[0]}
  (
  # Handle completions if running outside of a checkout.
  if ! "${repo}" help --all 2>/dev/null; then
    repo help 2>/dev/null
  fi
  ) | sed -n '/^  /{s/  \([^ ]\+\) .\+/\1/;p}'
}

# Complete list of all branches available in all projects in the repo client
# checkout.
__complete_repo_list_branches() {
  local repo=${COMP_WORDS[0]}
  "${repo}" branches 2>/dev/null | \
    sed -n '/|/{s/[ *][Pp ] *\([^ ]\+\) .*/\1/;p}'
}

# Complete list of all projects available in the repo client checkout.
__complete_repo_list_projects() {
  local repo=${COMP_WORDS[0]}
  "${repo}" list -n 2>/dev/null
}

# Complete the repo <command> argument.
__complete_repo_command() {
  if [[ ${COMP_CWORD} -ne 1 ]]; then
    return 1
  fi

  local command=${COMP_WORDS[1]}
  COMPREPLY=($(compgen -W "$(__complete_repo_list_commands)" -- "${command}"))
  return 0
}

# Complete repo subcommands that take <branch> <projects>.
__complete_repo_command_branch_projects() {
  local current=$1
  if [[ ${COMP_CWORD} -eq 2 ]]; then
    COMPREPLY=($(compgen -W "$(__complete_repo_list_branches)" -- "${current}"))
  else
    COMPREPLY=($(compgen -W "$(__complete_repo_list_projects)" -- "${current}"))
  fi
}

# Complete repo subcommands that take only <projects>.
__complete_repo_command_projects() {
  local current=$1
  COMPREPLY=($(compgen -W "$(__complete_repo_list_projects)" -- "${current}"))
}

# Complete the repo subcommand arguments.
__complete_repo_arg() {
  if [[ ${COMP_CWORD} -le 1 ]]; then
    return 1
  fi

  local command=${COMP_WORDS[1]}
  local current=${COMP_WORDS[COMP_CWORD]}
  case ${command} in
  abandon|checkout)
    __complete_repo_command_branch_projects "${current}"
    return 0
    ;;

  branch|branches|diff|info|list|overview|prune|rebase|smartsync|stage|status|\
  sync|upload)
    __complete_repo_command_projects "${current}"
    return 0
    ;;

  help)
    if [[ ${COMP_CWORD} -eq 2 ]]; then
      COMPREPLY=(
        $(compgen -W "$(__complete_repo_list_commands)" -- "${current}")
      )
    fi
    return 0
    ;;

  start)
    if [[ ${COMP_CWORD} -gt 2 ]]; then
      COMPREPLY=(
        $(compgen -W "$(__complete_repo_list_projects)" -- "${current}")
      )
    fi
    return 0
    ;;

  *)
    return 1
    ;;
  esac
}

# Complete the repo arguments.
__complete_repo() {
  COMPREPLY=()
  __complete_repo_command && return 0
  __complete_repo_arg && return 0
  return 0
}

complete -F __complete_repo repo
