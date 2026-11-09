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
# Version being replaced, captured before the first write (final consistency check).
PREVIOUS_VERSION=""
BUMP_ANDROID=true
REFRESH_LOCK=true
ANDROID_BUILD_GRADLE="${ROOT_DIR}/hsync-android/app/build.gradle.kts"

# Strict semver or semver + prerelease. The prerelease part may contain
# alphanumerics, dots and hyphens (e.g. alpha.1, beta-2, rc.3).
VERSION_RE='^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$'

show_help() {
    cat <<'EOF'
HSYNC Python Version Bump

Usage:
    hsync-common/scripts/dev/bump-python-version.sh [--dry-run] [--no-android] [--no-lock] <new_version>

Examples:
    hsync-common/scripts/dev/bump-python-version.sh --dry-run 1.1.0
    hsync-common/scripts/dev/bump-python-version.sh 1.1.0
    hsync-common/scripts/dev/bump-python-version.sh --dry-run 1.2.0-alpha.1
    hsync-common/scripts/dev/bump-python-version.sh --no-android 1.1.0

Options:
    --dry-run     Preview changes without touching files.
    --no-android  Skip the Android versionName/versionCode bump.
    --no-lock     Skip the per-project poetry.lock refresh (see Updates).

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
    - hsync-common/hsync_common/protocol/rest/openapi.json (info.version).
    - hsync-common/llm-wiki/README.md and
      hsync-common/llm-wiki/modules/utilities.md (the HSYNC_VERSION line).
    - hsync-desktop/install.sh (DEFAULT_VERSION, the release it downloads).
    - hsync-server/packaging/deb/usr/share/man/man1/hsync-server.1,
      hsync-client/packaging/deb/usr/share/man/man1/hsync.1 and
      hsync-rendezvous/packaging/deb/usr/share/man/man1/hsync-rendezvous.1
      (the version field of .TH; the manual date is left alone).
    - <project>/poetry.lock for every listed project, regenerated with
      `poetry lock` so the recorded content hash matches the bumped
      pyproject.toml, unless --no-lock is passed.

    Every carrier above is checked again at the end: a leftover of the previous
    version makes the script exit non-zero instead of leaving a mixed tree.

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
        --no-lock)
            REFRESH_LOCK=false
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

# The release metadata that does not live in a pyproject.toml. These are exactly
# the files a manual bump forgets: they are not package metadata, so nothing
# fails loudly when they go stale — the published OpenAPI document, the man
# pages and the installer would simply advertise the previous version.
update_release_metadata() {
    local openapi="${ROOT_DIR}/hsync-common/hsync_common/protocol/rest/openapi.json"
    local wiki_readme="${ROOT_DIR}/hsync-common/llm-wiki/README.md"
    local wiki_utilities="${ROOT_DIR}/hsync-common/llm-wiki/modules/utilities.md"
    local installer="${ROOT_DIR}/hsync-desktop/install.sh"
    local man_server="${ROOT_DIR}/hsync-server/packaging/deb/usr/share/man/man1/hsync-server.1"
    local man_client="${ROOT_DIR}/hsync-client/packaging/deb/usr/share/man/man1/hsync.1"
    local man_rendezvous="${ROOT_DIR}/hsync-rendezvous/packaging/deb/usr/share/man/man1/hsync-rendezvous.1"

    local file
    for file in "${openapi}" "${wiki_readme}" "${wiki_utilities}" "${installer}" \
        "${man_server}" "${man_client}" "${man_rendezvous}"; do
        [[ -f "${file}" ]] || { err "missing file: ${file}"; exit 1; }
    done

    # ``info.version`` is the only "version" key in the document; the OpenAPI
    # specification revision lives under "openapi".
    local current
    current="$(sed -nE 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)".*/\1/p' "${openapi}" | head -n 1)"
    [[ -n "${current}" ]] || { err "cannot read info.version from ${openapi}"; exit 1; }
    log "hsync-common/openapi.json: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${openapi}" \
            '(^[[:space:]]*"version"[[:space:]]*:[[:space:]]*")[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(")' \
            "\1${NEW_VERSION}\3"
    fi

    # The wiki quotes the SSOT value; replace the quoted string only, so the
    # surrounding sentence and the source anchor stay as they are.
    for file in "${wiki_readme}" "${wiki_utilities}"; do
        current="$(sed -nE 's/.*HSYNC_VERSION = "([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)".*/\1/p' "${file}" | head -n 1)"
        [[ -n "${current}" ]] || { err "cannot read HSYNC_VERSION line from ${file}"; exit 1; }
        log "${file#"${ROOT_DIR}/"}: ${current} -> ${NEW_VERSION}"
        if [[ "${DRY_RUN}" == false ]]; then
            sed_in_place "${file}" \
                '(HSYNC_VERSION = ")[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(")' \
                "\1${NEW_VERSION}\3"
        fi
    done

    # The installer downloads the release named here, so it must match the tag
    # cut from this bump.
    current="$(sed -nE 's/.*DEFAULT_VERSION="v([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)".*/\1/p' "${installer}" | head -n 1)"
    [[ -n "${current}" ]] || { err "cannot read DEFAULT_VERSION from ${installer}"; exit 1; }
    log "hsync-desktop/install.sh: ${current} -> ${NEW_VERSION}"
    if [[ "${DRY_RUN}" == false ]]; then
        sed_in_place "${installer}" \
            '(DEFAULT_VERSION="v)[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(")' \
            "\1${NEW_VERSION}\3"
    fi

    # The man page carries the version in the .TH header; its date is the manual
    # revision date and is intentionally untouched.
    local man program
    for man in "${man_server}" "${man_client}" "${man_rendezvous}"; do
        program="$(basename "${man}" .1)"
        current="$(sed -nE "s/.*\"${program} ([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?)\" .*/\1/p" "${man}" | head -n 1)"
        [[ -n "${current}" ]] || { err "cannot read the version from ${man}"; exit 1; }
        log "${man#"${ROOT_DIR}/"}: ${current} -> ${NEW_VERSION}"
        if [[ "${DRY_RUN}" == false ]]; then
            sed_in_place "${man}" \
                "(${program} )[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?" \
                "\1${NEW_VERSION}"
        fi
    done
}

# Catch a mixed tree before it is committed: every carrier must hold the new
# version and none of them may still hold the previous one. A stale OpenAPI
# document or man page is invisible in tests, which is why this check exists.
verify_release_metadata() {
    if [[ "${DRY_RUN}" == true || "${PREVIOUS_VERSION}" == "${NEW_VERSION}" ]]; then
        return
    fi
    local carriers=(
        "${ROOT_DIR}/hsync-common/hsync_common/constants.py"
        "${ROOT_DIR}/hsync-common/hsync_common/protocol/rest/openapi.json"
        "${ROOT_DIR}/hsync-common/llm-wiki/README.md"
        "${ROOT_DIR}/hsync-common/llm-wiki/modules/utilities.md"
        "${ROOT_DIR}/hsync-desktop/install.sh"
        "${ROOT_DIR}/hsync-server/packaging/deb/usr/share/man/man1/hsync-server.1"
        "${ROOT_DIR}/hsync-client/packaging/deb/usr/share/man/man1/hsync.1"
        "${ROOT_DIR}/hsync-rendezvous/packaging/deb/usr/share/man/man1/hsync-rendezvous.1"
        "${ROOT_DIR}/hsync-rendezvous/python/src/hsync_rendezvous/__init__.py"
    )
    local file failures=0
    # Match the previous version as a whole token, not as a substring: bumping
    # 1.1.0 -> 1.1.0-beta.1 would otherwise report the new value as a leftover
    # (the new version literally contains the old one). The optional "v" covers
    # ``DEFAULT_VERSION="vX.Y.Z"``.
    local previous_token
    previous_token="(^|[^0-9A-Za-z.-])v?${PREVIOUS_VERSION//./\\.}([^0-9A-Za-z.-]|$)"
    for file in "${carriers[@]}"; do
        if [[ -n "${PREVIOUS_VERSION}" ]] && grep -qE "${previous_token}" "${file}"; then
            err "still at ${PREVIOUS_VERSION}: ${file#"${ROOT_DIR}/"}"
            failures=$((failures + 1))
        fi
        # The new value is checked as a substring: it may be prefixed ("v1.2.0")
        # or embedded in a sentence, and either way it proves the file was
        # rewritten.
        if ! grep -qF "${NEW_VERSION}" "${file}"; then
            err "does not carry ${NEW_VERSION}: ${file#"${ROOT_DIR}/"}"
            failures=$((failures + 1))
        fi
    done
    if (( failures > 0 )); then
        err "release metadata is inconsistent after the bump; fix the files above."
        exit 1
    fi
    log "Release metadata consistent at ${NEW_VERSION}."
}

# Regenerate each project's poetry.lock so its recorded content hash matches the
# bumped pyproject.toml. A stale lock makes `poetry install` abort in CI with
# "pyproject.toml changed significantly since poetry.lock was last generated".
# Requires poetry on PATH plus the sibling path dependencies (../hsync-common,
# ../hsync-server) next to each project, which the monorepo layout provides.
refresh_locks() {
    if [[ "${REFRESH_LOCK}" == false ]]; then
        log "Skipping poetry.lock refresh (--no-lock)."
        return
    fi
    if [[ "${DRY_RUN}" == true ]]; then
        log "Would refresh poetry.lock for: ${PROJECTS[*]}"
        return
    fi
    if ! command -v poetry >/dev/null 2>&1; then
        err "poetry not found on PATH; cannot refresh lock files (use --no-lock to skip)"
        exit 1
    fi

    local project dir
    for project in "${PROJECTS[@]}"; do
        dir="${ROOT_DIR}/${project}"
        # hsync-rendezvous hosts its Poetry project in python/ (src layout).
        [[ "${project}" == "hsync-rendezvous" ]] && dir="${dir}/python"
        log "${project}: refreshing poetry.lock"
        if ! (cd "${dir}" && poetry lock --no-interaction); then
            err "poetry lock failed in ${dir}"
            exit 1
        fi
    done
}

main() {
    local mode=""
    [[ "${DRY_RUN}" == true ]] && mode=" (dry-run)"
    local scope="Python projects"
    [[ "${BUMP_ANDROID}" == true ]] && scope="Python projects + Android"
    # Captured before any write: the closing check reports a carrier that still
    # holds this value.
    PREVIOUS_VERSION="$(extract_runtime_version "${ROOT_DIR}/hsync-common/hsync_common/constants.py")"

    log "Bumping HSYNC ${scope} to ${NEW_VERSION}${mode}"
    log ""

    for project in "${PROJECTS[@]}"; do
        update_pyproject "${project}"
    done
    refresh_locks
    update_runtime_version
    update_rendezvous_package_version
    update_release_metadata

    if [[ "${BUMP_ANDROID}" == true ]]; then
        update_android_version
    else
        # Android is not a Python package, so it is skipped on request — but the
        # ecosystem then ships two different versions, which is easy to miss.
        local android_current
        android_current="$(sed -nE 's/.*versionName[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "${ANDROID_BUILD_GRADLE}" | head -n 1)"
        log "Skipping Android version bump (--no-android): hsync-android stays at ${android_current:-unknown}."
    fi

    verify_release_metadata

    log ""
    if [[ "${DRY_RUN}" == true ]]; then
        log "Dry-run complete. No files changed."
    else
        log "Version bump complete. Review changes with: git diff"
        if [[ "${REFRESH_LOCK}" == true ]]; then
            log "poetry.lock refreshed for every project; commit it with the bump."
        else
            log "poetry.lock NOT refreshed (--no-lock): run 'poetry lock' in each project before pushing."
        fi
        log "Recommended validation per project: poetry check --lock && poetry run pytest -q"
    fi
}

main
