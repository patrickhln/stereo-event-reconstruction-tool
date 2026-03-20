#!/bin/bash

require_branch_root() {
    local input_path="$1"
    local branch_path

    if [[ ! -d "$input_path" ]]; then
        echo "Error: Branch path not found: $input_path" >&2
        return 1
    fi

    branch_path=$(realpath "$input_path")

    if [[ ! -d "$branch_path/raw" ]]; then
        echo "Error: Expected explicit branch root (missing raw/): $branch_path" >&2
        return 1
    fi

    printf '%s\n' "$branch_path"
}

find_session_root() {
    local input_path="$1"
    local current

    current=$(realpath "$input_path")
    while [[ "$current" != "/" ]]; do
        if [[ -f "$current/session.yaml" ]]; then
            printf '%s\n' "$current"
            return 0
        fi
        current=$(dirname "$current")
    done

    echo "Error: Could not find session root above: $input_path" >&2
    echo "Expected a parent directory containing session.yaml" >&2
    return 1
}

require_branch_in_session_subdir() {
    local branch_path="$1"
    local session_root="$2"
    local subdir="$3"
    local expected_root

    expected_root=$(realpath "$session_root/$subdir")

    if [[ "$branch_path/" != "$expected_root/"* ]]; then
        echo "Error: Branch must live under: $expected_root" >&2
        echo "You provided: $branch_path" >&2
        return 1
    fi

    printf '%s\n' "$branch_path"
}
