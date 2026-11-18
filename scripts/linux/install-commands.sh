#!/usr/bin/env bash
set -euo pipefail
command_directory="$HOME/.local/bin"
for command_name in run1 run2 run3 train; do
    command_path="$command_directory/$command_name"
    if [[ -e "$command_path" && "$(<"$command_path")" != *'# model-orchestrator CLI'* ]]; then
        printf 'A different command already exists: %s\n' "$command_path" >&2
        exit 1
    fi
done
mkdir -p -- "$command_directory"
for command_name in run1 run2 run3 train; do
    command_path="$command_directory/$command_name"
    cat > "$command_path" <<'SH'
#!/usr/bin/env bash
# model-orchestrator CLI
set -euo pipefail
command_name="$(basename -- "${BASH_SOURCE[0]}")"
if [[ ! -f "$PWD/scripts/linux/$command_name.sh" ]]; then
    printf 'Run %s from the model-orchestrator project root.\n' "$command_name" >&2
    exit 1
fi
exec bash "$PWD/scripts/linux/$command_name.sh" "$@"
SH
    chmod +x -- "$command_path"
done
path_setting='export PATH="$HOME/.local/bin:$PATH"'
for startup_file in "$HOME/.profile" "$HOME/.bashrc"; do
    if [[ ! -f "$startup_file" || "$(<"$startup_file")" != *"$path_setting"* ]]; then
        printf '\n%s\n' "$path_setting" >> "$startup_file"
    fi
done
printf 'Registered commands: run1, run2, run3, train. Open a new terminal and use them from the project root.\n'
