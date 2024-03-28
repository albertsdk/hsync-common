#!/usr/bin/env bash
# HSYNC Python projects version bump script.
#
# Updates the package metadata for every Python project and the shared runtime
# protocol version in hsync-common. Defaults to a real update; use --dry-run to
# preview changes without touching files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

PROJECTS=(
    "hsync-common"
    "hsync-client"
    "hsync-server"
    "hsync-desktop"
)

DRY_RUN=false
NEW_VERSION=""

show_help() {
    cat <<'EOF'
HSYNC Python Version Bump

Usage:
    hsync-common/scripts/dev/bump-python-version.sh [--dry-run] <new_version>

Examples:
    hsync-common/scripts/dev/bump-python-version.sh --dry-run 1.1.0
    hsync-common/scripts/dev/bump-python-version.sh 1.1.0

Updates:
    - hsync-common/pyproject.toml
    - hsync-client/pyproject.toml
    - hsync-server/pyproject.toml
    - hsync-desktop/pyproject.toml
    - hsync-common/hsync_common/constants.py (VERSION)

Notes:
    hsync-common.constants.VERSION is the runtime/protocol version consumed by
    client, server and desktop. Per-project constants modules re-export it, so
    they must not be edited independently.
EOF
}

log() { printf '%s\n' "$*"; }
err() { printf 'Error: %s\n' "$*" >&2; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            if [[ -n "${NEW_VERSION}" ]]; then
                err "unexpected argument: $1"
                show_help >&2
                exit 1
            fi
            NEW_VERSION="$1"
            shift
            ;;
    esac
done

if [[ -z "${NEW_VERSION}" ]]; then
    err "version argument required"
    show_help >&2
    exit 1
fi

if ! [[ "${NEW_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    err "version must be semver X.Y.Z (got: ${NEW_VERSION})"
    exit 1
fi

sed_in_place() {
    local file="$1"
    local pattern="$2"
    local replacement="$3"
    if [[ "${OSTYPE:-}" == darwin* ]]; then
        sed -E -i '' "s|${pattern}|${replacement}|" "${file}"
    else
        sed -E -i "s|${pattern}|${replacement}|" "${file}"
    fi
}

extract_pyproject_version() {
    local file="$1"
    sed -nE 's/^version[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+)"$/\1/p' "${file}" | head -n 1
}

extract_runtime_version() {
    local file="$1"
    sed -nE 's/^VERSION[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+)"$/\1/p' "${file}" | head -n 1
}

extract_common_dependency_version() {
    local file="$1"
    sed -nE 's/^[[:space:]]*"hsync-common==([0-9]+\.[0-9]+\.[0-9]+)",$/\1/p' "${file}" | head -n 1
}

update_pyproject() {
    local project="$1"
    local file="${ROOT_DIR}/${project}/pyproject.toml"
    [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }

    local current
    current="$(extract_pyproject_version "${file}")"
    [[ -n "${current}" ]] || { err "cannot read version from ${file}"; exit 1; }

    log "${project}/pyproject.toml: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${file}" \
            '^version[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"$' \
            "version = \"${NEW_VERSION}\""
    fi

    if [[ "${project}" != "hsync-common" ]]; then
        local common_dependency
        common_dependency="$(extract_common_dependency_version "${file}")"
        [[ -n "${common_dependency}" ]] || { err "cannot read hsync-common dependency from ${file}"; exit 1; }

        log "${project}/pyproject.toml hsync-common: ${common_dependency} -> ${NEW_VERSION}"
        if [[ "${DRY_RUN}" == false ]]; then
            sed_in_place "${file}" \
                '"hsync-common==[0-9]+\.[0-9]+\.[0-9]+",' \
                "\"hsync-common==${NEW_VERSION}\","
        fi
    fi
}

update_runtime_version() {
    local file="${ROOT_DIR}/hsync-common/hsync_common/constants.py"
    [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }

    local current
    current="$(extract_runtime_version "${file}")"
    [[ -n "${current}" ]] || { err "cannot read VERSION from ${file}"; exit 1; }

    log "hsync-common/hsync_common/constants.py: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${file}" \
            '^VERSION[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"$' \
            "VERSION = \"${NEW_VERSION}\""
    fi
}

main() {
    local mode=""
    [[ "${DRY_RUN}" == true ]] && mode=" (dry-run)"
    log "Bumping HSYNC Python projects to ${NEW_VERSION}${mode}"
    log ""

    for project in "${PROJECTS[@]}"; do
        update_pyproject "${project}"
    done
    update_runtime_version

    log ""
    if [[ "${DRY_RUN}" == true ]]; then
        log "Dry-run complete. No files changed."
    else
        log "Version bump complete. Review changes with: git diff"
        log "Recommended validation per project: poetry check --lock && poetry run pytest -q"
    fi
}

main
