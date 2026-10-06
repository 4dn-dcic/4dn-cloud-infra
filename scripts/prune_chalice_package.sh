#!/usr/bin/env bash
# --------------------------------------------------------------------------------------------------
# Remove known-unneeded files from a Chalice deployment zip.
#
# The one-argument form remains the production-compatible form. It removes only deployment
# tooling packages that are not part of the Foursight Lambda runtime, plus the historical test and
# example directories. A variant may be supplied when the package deliberately contains more
# than one Foursight implementation:
#
#   prune_chalice_package.sh [--dry-run] [--report] [--variant VARIANT] ZIP
#
# Package removal is deliberately an allow-list. In particular, this script does not infer
# reachability from imports: app.py selects chalicelib_* at runtime and packages can be imported
# dynamically by Foursight. See docs/source/pruning_chalice_packages.rst for assumptions that
# must be checked before changing these rules.
# --------------------------------------------------------------------------------------------------

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
DRY_RUN=0
REPORT=0
VARIANT="all"

usage() {
    cat >&2 <<EOF
usage: $SCRIPT_NAME [--dry-run] [--report] [--variant VARIANT] path-to-chalice-zip-file

VARIANT is one of: all, cgap, fourfront, smaht (foursight-* aliases are accepted).
The existing one-argument invocation is equivalent to --variant all.
EOF
}

error() {
    echo "$SCRIPT_NAME: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --report)
            REPORT=1
            shift
            ;;
        --variant)
            (($# >= 2)) || { usage; exit 1; }
            VARIANT="$2"
            shift 2
            ;;
        --variant=*)
            VARIANT="${1#*=}"
            shift
            ;;
        --help|-h)
            usage >&2
            exit 0
            ;;
        --*)
            usage
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

if (($# != 1)); then
    usage
    exit 1
fi

case "$VARIANT" in
    all)
        ;;
    cgap|foursight-cgap)
        VARIANT="cgap"
        ;;
    fourfront|foursight|foursight-fourfront)
        VARIANT="fourfront"
        ;;
    smaht|foursight-smaht)
        VARIANT="smaht"
        ;;
    *)
        error "unknown variant '$VARIANT'"
        ;;
esac

INPUT="$1"
if [[ ! -f "$INPUT" ]]; then
    echo "$SCRIPT_NAME: file not found - $INPUT" >&2
    exit 2
fi
if [[ -L "$INPUT" ]]; then
    error "refusing to replace a symbolic-link input; provide the archive path directly"
fi

INPUT_DIR="$(cd "$(dirname -- "$INPUT")" >/dev/null && pwd -P)"
CHALICE_PACKAGE_ZIP_FILE="$INPUT_DIR/$(basename -- "$INPUT")"

# Use a known temporary root rather than trusting a caller-controlled directory. The extraction
# directory is the only path ever passed to rm -rf, and it is checked before cleanup/deletion.
TMP_ROOT="/tmp"
WORK_DIR=""
TMP_CHALICE_PACKAGE_FILE=""
TMP_LOG_FILE=""

cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        case "$WORK_DIR" in
            "$TMP_ROOT"/.chalice_package_prune.*)
                rm -rf -- "$WORK_DIR"
                ;;
            *)
                echo "$SCRIPT_NAME: refusing to clean unexpected directory: $WORK_DIR" >&2
                ;;
        esac
    fi
    if [[ -n "$TMP_CHALICE_PACKAGE_FILE" && -f "$TMP_CHALICE_PACKAGE_FILE" ]]; then
        rm -f -- "$TMP_CHALICE_PACKAGE_FILE"
    fi
}
trap cleanup EXIT HUP INT TERM

archive_size() {
    wc -c < "$1" | tr -d ' '
}

# Total bytes of regular files under a path (symlinks are not followed). Streaming every file
# through a single wc keeps this portable across BSD/GNU tools without one process per file.
tree_size() {
    find "$1" -type f -print0 | xargs -0 cat -- | wc -c | tr -d ' '
}

validate_archive() {
    local entry
    unzip -tqq "$CHALICE_PACKAGE_ZIP_FILE" >/dev/null || error "input is not a valid zip archive"

    # Do not extract absolute or parent-traversing names. This also catches names that would
    # escape the extraction directory through a nested .. component.
    while IFS= read -r entry; do
        case "$entry" in
            /*|../*|*/../*|*/..|..)
                error "unsafe path in zip archive: $entry"
                ;;
        esac
    done < <(unzip -Z1 "$CHALICE_PACKAGE_ZIP_FILE")
}

root_path() {
    local package_name="$1"
    local path
    for path in "$WORK_DIR/$package_name" "$WORK_DIR/$package_name.py"; do
        if [[ -e "$path" || -L "$path" ]]; then
            printf '%s\n' "$path"
            return 0
        fi
    done
    return 1
}

metadata_paths() {
    local distribution="$1"
    local path base
    while IFS= read -r -d '' path; do
        base="$(basename -- "$path")"
        case "$base" in
            "$distribution"-[0-9]*.dist-info|"$distribution"-[0-9]*.egg-info)
                printf '%s\0' "$path"
                ;;
        esac
    # -prune keeps this portable to both BSD and GNU find: only archive-root entries are listed.
    done < <(find "$WORK_DIR" -mindepth 1 -prune -print0)
}

remove_path() {
    local path="$1"
    local label="$2"
    local size
    size="$(tree_size "$path")"
    REMOVED_COUNT=$((REMOVED_COUNT + 1))
    REMOVED_BYTES=$((REMOVED_BYTES + size))
    REMOVED_LABELS+=("$label ($size uncompressed bytes)")
    if ((REPORT)); then
        echo "  remove: $label ($size uncompressed bytes)"
    fi
    if ((DRY_RUN == 0)); then
        case "$path" in
            "$WORK_DIR"/*)
                rm -rf -- "$path"
                ;;
            *)
                error "refusing to remove path outside extracted package: $path"
                ;;
        esac
    fi
}

# Rules are explicit package roots, not a static-import or transitive-dependency analysis. The
# distribution name is separate because Python package roots use underscores while metadata uses
# the published distribution's hyphenated name.
remove_deployment_package() {
    local distribution="$1"
    local roots="$2"
    local root path
    local removed_code=0

    for root in $roots; do
        if path="$(root_path "$root")"; then
            remove_path "$path" "$root"
            removed_code=1
        fi
    done

    # Metadata is removed only when a matching code root was found. This avoids damaging an
    # archive that happens to contain unrelated metadata or an incomplete package installation.
    if ((removed_code)); then
        while IFS= read -r -d '' path; do
            remove_path "$path" "$(basename -- "$path")"
        done < <(metadata_paths "$distribution")
    fi
}

assert_protected_packages() {
    local package_name path
    # These are runtime packages commonly shared by Foursight and its dependencies. If an input
    # archive contains one, it must still contain the same root after pruning. Missing packages
    # are not invented here so synthetic/minimal archives remain useful for testing.
    local protected_packages=(boto3 botocore dcicutils cffi requests urllib3 jmespath s3transfer chalice awscli
        awscli_customizations tibanna tibanna_ff)
    for package_name in "${protected_packages[@]}"; do
        if path="$(root_path "$package_name")"; then
            PROTECTED_PATHS+=("$path")
        fi
    done
}

check_protected_packages() {
    local path
    for path in "${PROTECTED_PATHS[@]}"; do
        [[ -e "$path" || -L "$path" ]] || error "protected package was removed: $(basename -- "$path")"
    done
}

validate_archive
WORK_DIR="$(mktemp -d "$TMP_ROOT/.chalice_package_prune.XXXXXX")"
TMP_CHALICE_PACKAGE_FILE="$TMP_ROOT/.chalice_package_prune.$$.zip"
TMP_LOG_FILE="$TMP_ROOT/.chalice_package_prune.$$.log"
case "$WORK_DIR" in
    "$TMP_ROOT"/.chalice_package_prune.*) ;;
    *) error "unexpected extraction directory: $WORK_DIR" ;;
esac

unzip -q "$CHALICE_PACKAGE_ZIP_FILE" -d "$WORK_DIR" >"$TMP_LOG_FILE" 2>&1

PROTECTED_PATHS=()
assert_protected_packages
REMOVED_LABELS=()
REMOVED_COUNT=0
REMOVED_BYTES=0
ORIGINAL_ARCHIVE_BYTES="$(archive_size "$CHALICE_PACKAGE_ZIP_FILE")"
ORIGINAL_TREE_BYTES="$(tree_size "$WORK_DIR")"

echo "Pruning chalice package ($ORIGINAL_ARCHIVE_BYTES bytes): $CHALICE_PACKAGE_ZIP_FILE"
echo "Variant: $VARIANT"
echo "Log file for this chalice prune process: $TMP_LOG_FILE"

echo "Preparing to prune/delete cruft from chalice package."
while IFS= read -r -d '' path; do
    remove_path "$path" "$(printf '%s' "$path" | sed "s#^$WORK_DIR/##")"
done < <(find "$WORK_DIR" -type d \( -name examples -o -name tests -o -name test \) -prune -print0)

# These are packages used to build/provision 4dn-cloud-infra, not by the deployed Foursight
# handler. Do not add transitive dependencies here merely because they look large: many are shared
# by Foursight and removing them is not safe without runtime evidence.
remove_deployment_package "awacs" "awacs"
remove_deployment_package "troposphere" "troposphere"

if [[ "$VARIANT" != "all" ]]; then
    selected="chalicelib_$VARIANT"
    if ! root_path "$selected" >/dev/null; then
        error "selected variant package is missing: $selected"
    fi
    for candidate in chalicelib_cgap chalicelib_fourfront chalicelib_smaht; do
        if [[ "$candidate" != "$selected" ]] && path="$(root_path "$candidate")"; then
            remove_path "$path" "$candidate (non-selected variant)"
        fi
    done
fi

check_protected_packages
# Removed paths are disjoint in a real run (each is deleted before the next is found), so the
# final size follows from the original scan without walking the whole tree again.
FINAL_TREE_BYTES="$ORIGINAL_TREE_BYTES"
if ((DRY_RUN == 0)); then
    FINAL_TREE_BYTES=$((ORIGINAL_TREE_BYTES - REMOVED_BYTES))
fi

if ((DRY_RUN)); then
    echo "Dry run: archive unchanged."
else
    # Rebuild in a separate file and verify it before replacing the input archive.
    (cd "$WORK_DIR" && zip -q -r "$TMP_CHALICE_PACKAGE_FILE" .) >"$TMP_LOG_FILE" 2>&1
    unzip -tqq "$TMP_CHALICE_PACKAGE_FILE" >/dev/null || error "rebuilt archive failed validation"
    mv -f -- "$TMP_CHALICE_PACKAGE_FILE" "$CHALICE_PACKAGE_ZIP_FILE"
fi

FINAL_ARCHIVE_BYTES="$ORIGINAL_ARCHIVE_BYTES"
if ((DRY_RUN == 0)); then
    FINAL_ARCHIVE_BYTES="$(archive_size "$CHALICE_PACKAGE_ZIP_FILE")"
fi

echo "Removed $REMOVED_COUNT item(s), $REMOVED_BYTES uncompressed bytes."
echo "Uncompressed package: $ORIGINAL_TREE_BYTES -> $FINAL_TREE_BYTES bytes."
echo "Archive: $ORIGINAL_ARCHIVE_BYTES -> $FINAL_ARCHIVE_BYTES bytes."
if ((REPORT)) && ((${#REMOVED_LABELS[@]})); then
    echo "Removal report:"
    printf '  %s\n' "${REMOVED_LABELS[@]}"
fi
if ((DRY_RUN == 0)); then
    echo "Done pruning chalice package ($FINAL_ARCHIVE_BYTES bytes): $CHALICE_PACKAGE_ZIP_FILE"
fi
