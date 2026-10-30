#!/usr/bin/env bash
# HSYNC Python projects version bump script.
#
# Updates the package metadata for every Python project and the shared runtime
# protocol version in hsync-common. Defaults to a real update; use --dry-run to
# preview changes without touching files.
#
# Accepts a strict semver X.Y.Z or a prerelease X.Y.Z-<prerelease> (e.g.
# 1.2.0-alpha.1, 1.2.0-rc.2). Build metadata (X.Y.Z+<build>) is rejected on
# purpose: '+' is not a valid Docker image tag character and cannot appear in
# the Git refs the release workflows use.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Python projects bumped through their Poetry pyproject. ``hsync-rendezvous``
# hosts its Poetry project in the ``python/`` subdirectory (in-project virtualenv,
# ``src/`` layout) so its pyproject is addressed explicitly below.
# ``hsync-wd-os5`` is intentionally absent: it ships no Python package (its
# pyproject is tooling-only) and the packaged artifact version is the
# hsync-client version it freezes.
PROJECTS=(
    "hsync-common"
    "hsync-client"
    "hsync-server"
    "hsync-desktop"
    "hsync-rendezvous"
)

DRY_RUN=false
NEW_VERSION=""
BUMP_ANDROID=true
ANDROID_BUILD_GRADLE="${ROOT_DIR}/hsync-android/app/build.gradle.kts"

# Strict semver or semver + prerelease. The prerelease part may contain
# alphanumerics, dots and hyphens (e.g. alpha.1, beta-2, rc.3).
VERSION_RE='^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$'

show_help() {
    cat <<'EOF'
HSYNC Python Version Bump

Usage:
    hsync-common/scripts/dev/bump-python-version.sh [--dry-run] [--no-android] <new_version>

Examples:
    hsync-common/scripts/dev/bump-python-version.sh --dry-run 1.1.0
    hsync-common/scripts/dev/bump-python-version.sh 1.1.0
    hsync-common/scripts/dev/bump-python-version.sh --dry-run 1.2.0-alpha.1
    hsync-common/scripts/dev/bump-python-version.sh --no-android 1.1.0

Options:
    --dry-run     Preview changes without touching files.
    --no-android  Skip the Android versionName/versionCode bump.

Updates:
    - hsync-common/pyproject.toml
    - hsync-client/pyproject.toml
    - hsync-server/pyproject.toml
    - hsync-desktop/pyproject.toml
    - hsync-rendezvous/python/pyproject.toml
    - hsync-common/hsync_common/constants.py (HSYNC_VERSION)
    - hsync-rendezvous/python/src/hsync_rendezvous/__init__.py (__version__)
    - hsync-android/app/build.gradle.kts (versionName + versionCode), unless
      --no-android is passed.

Notes:
    hsync-common.constants.HSYNC_VERSION is the runtime/protocol version consumed
    by client, server and desktop, whose constants modules re-export it and must
    not be edited independently. hsync-rendezvous keeps a literal package
    __version__ (its project and virtualenv live under python/) and is bumped
    here too. hsync-wd-os5 is NOT listed: it ships no Python package and its
    artifact version is the hsync-client version it freezes at build time.
    Android shares the same semantic versionName and gets a monotonically
    incremented versionCode. A prerelease suffix (X.Y.Z-<prerelease>) is
    propagated verbatim to pyproject.toml, HSYNC_VERSION and Android versionName;
    the .deb build translates it to the Debian form (X.Y.Z~<prerelease>) via
    hsync-client/compile.sh.
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
        --no-android)
            BUMP_ANDROID=false
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

if ! [[ "${NEW_VERSION}" =~ ${VERSION_RE} ]]; then
    err "version must be X.Y.Z or X.Y.Z-<prerelease> (got: ${NEW_VERSION})"
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
    sed -nE 's/^version[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)"$/\1/p' "${file}" | head -n 1
}

extract_runtime_version() {
    local file="$1"
    sed -nE 's/^HSYNC_VERSION[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)"$/\1/p' "${file}" | head -n 1
}

extract_common_dependency_version() {
    local file="$1"
    sed -nE 's/^[[:space:]]*"hsync-common==([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)",$/\1/p' "${file}" | head -n 1
}

update_pyproject() {
    local project="$1"
    # hsync-rendezvous hosts its Poetry project in python/ (src layout).
    local relative="pyproject.toml"
    [[ "${project}" == "hsync-rendezvous" ]] && relative="python/pyproject.toml"
    local file="${ROOT_DIR}/${project}/${relative}"
    [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }

    local current
    current="$(extract_pyproject_version "${file}")"
    [[ -n "${current}" ]] || { err "cannot read version from ${file}"; exit 1; }

    log "${project}/${relative}: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${file}" \
            '^version[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?"$' \
            "version = \"${NEW_VERSION}\""
    fi

    if [[ "${project}" != "hsync-common" ]]; then
        local common_dependency
        common_dependency="$(extract_common_dependency_version "${file}")"
        [[ -n "${common_dependency}" ]] || { err "cannot read hsync-common dependency from ${file}"; exit 1; }

        log "${project}/${relative} hsync-common: ${common_dependency} -> ${NEW_VERSION}"
        if [[ "${DRY_RUN}" == false ]]; then
            sed_in_place "${file}" \
                '"hsync-common==[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?",' \
                "\"hsync-common==${NEW_VERSION}\","
        fi
    fi
}

update_runtime_version() {
    local file="${ROOT_DIR}/hsync-common/hsync_common/constants.py"
    [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }

    local current
    current="$(extract_runtime_version "${file}")"
    [[ -n "${current}" ]] || { err "cannot read HSYNC_VERSION from ${file}"; exit 1; }

    log "hsync-common/hsync_common/constants.py: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${file}" \
            '^HSYNC_VERSION[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?"$' \
            "HSYNC_VERSION = \"${NEW_VERSION}\""
    fi
}

update_rendezvous_package_version() {
    local file="${ROOT_DIR}/hsync-rendezvous/python/src/hsync_rendezvous/__init__.py"
    [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }

    # Package __version__ mirrors the ecosystem version but is a literal copy
    # (hsync-rendezvous is the only Python project that does not re-export
    # HSYNC_VERSION from hsync-common).
    local current
    current="$(sed -nE 's/^__version__[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)"$/\1/p' "${file}" | head -n 1)"
    [[ -n "${current}" ]] || { err "cannot read __version__ from ${file}"; exit 1; }

    log "hsync-rendezvous/__init__.py: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${file}" \
            '^__version__[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?"$' \
            "__version__ = \"${NEW_VERSION}\""
    fi
}

update_android_version() {
    local file="${ANDROID_BUILD_GRADLE}"
    [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }

    local current_name current_code next_code
    current_name="$(sed -nE 's/.*versionName[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)".*/\1/p' "${file}" | head -n 1)"
    current_code="$(sed -nE 's/.*versionCode[[:space:]]*=[[:space:]]*([0-9]+).*/\1/p' "${file}" | head -n 1)"
    [[ -n "${current_name}" ]] || { err "cannot read versionName from ${file}"; exit 1; }
    [[ -n "${current_code}" ]] || { err "cannot read versionCode from ${file}"; exit 1; }
    next_code=$((current_code + 1))

    log "hsync-android/app/build.gradle.kts versionName: ${current_name} -> ${NEW_VERSION}"
    log "hsync-android/app/build.gradle.kts versionCode: ${current_code} -> ${next_code}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${file}" \
            'versionName[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?"' \
            "versionName = \"${NEW_VERSION}\""
        sed_in_place "${file}" \
            'versionCode[[:space:]]*=[[:space:]]*[0-9]+' \
            "versionCode = ${next_code}"
    fi
}

main() {
    local mode=""
    [[ "${DRY_RUN}" == true ]] && mode=" (dry-run)"
    local scope="Python projects"
    [[ "${BUMP_ANDROID}" == true ]] && scope="Python projects + Android"
    log "Bumping HSYNC ${scope} to ${NEW_VERSION}${mode}"
    log ""

    for project in "${PROJECTS[@]}"; do
        update_pyproject "${project}"
    done
    update_runtime_version
    update_rendezvous_package_version

    if [[ "${BUMP_ANDROID}" == true ]]; then
        update_android_version
    else
        log "Skipping Android version bump (--no-android)."
    fi

    log ""
    if [[ "${DRY_RUN}" == true ]]; then
        log "Dry-run complete. No files changed."
    else
        log "Version bump complete. Review changes with: git diff"
        log "Recommended validation per project: poetry check --lock && poetry run pytest -q"
    fi
}

main
