#compdef cognios cognios-backup cognios-calendar cognios-contacts cognios-cookbook cognios-docs cognios-gallery cognios-mail cognios-mcp cognios-memory cognios-notes cognios-personal cognios-preset cognios-research cognios-sessions cognios-signature cognios-skills cognios-tasks cognios-theme cognios-webhook
# Zsh tab-completion for the cognios umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/cognios-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `cognios <tab>` completes subcommands; `cognios mail <tab>`
# completes mail subcommands; `cognios-mail <tab>` works the same.

_cognios_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _cognios_subs

_cognios_refresh() {
    _cognios_subs=()
    local dir="$(_cognios_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/cognios-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#cognios-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _cognios_subs[$sub]="$commands"
    done
}

_cognios() {
    [[ ${#_cognios_subs} -eq 0 ]] && _cognios_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "cognios" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_cognios_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_cognios_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_cognios_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # cognios-foo <tab>
    local sub="${cmd#cognios-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_cognios_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_cognios "$@"
