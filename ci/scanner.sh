#!/usr/bin/env bash
# ci/scanner.sh — CITADEL DRY scanner
#
# Used at 4 enforcement points:
#   1. PreToolUse hook (pre-write-scan.sh) — blocks before file hits disk
#   2. Client pre-commit hook (installed by bootstrap)
#   3. Client pre-push hook (Tally canonical dev box → GitHub)  [--ci]
#   4. Server pre-receive hook on bare repos — cannot be bypassed with --no-verify
#   + GitHub Actions backstop job (MASON) — public CI, unbypassable [--ci]
#
# Modes / flags:
#   ci/scanner.sh --prereceive       reads git stdin (pre-receive mode)
#   ci/scanner.sh --file <path>      scans a single file (PreToolUse mode)
#   ci/scanner.sh --selftest         regression self-check
#   ci/scanner.sh                    no args → prereceive mode (hook symlink compat)
#   ci/scanner.sh --ci ...           CLIENT/CI-safe modifier (see below)
#
# --ci modifier (composes with --prereceive / --file):
#   * Quiet PII output: a PII / real-name / institution-name match prints
#     "PII pattern match in <file>:<line>" WITHOUT the matched literal, so the
#     operator's real name / bank names never reach public Actions logs.
#     (Generic credential/secret/entropy findings print as normal — not sensitive.)
#   * PATTERN_DIR env override is honored ONLY under --ci. Without --ci the
#     hardcoded /etc/citadel/patterns is forced (cannot be neutered locally).
#   * LOG_DIR env override honored ONLY under --ci, and a missing/unwritable
#     log dir is NON-FATAL (warn + continue) so a client/CI box that cannot
#     write /var/log/aiops-prerec is never blocked. Fatal in normal modes.
#
# Exit codes:
#   0 = clean
#   1 = finding (push/write blocked)
#   2 = error   (fail-closed — git rejects push on any non-zero)
#
# Pattern files (outside vault — not agent-writable):
#   /etc/citadel/patterns/institution-patterns.txt
#   /etc/citadel/patterns/name-patterns.txt
#
# Logs: /var/log/aiops-prerec/YYYYMMDDTHHMMSSZ-scanner.log

set -uo pipefail

TS=$(date -u +"%Y%m%dT%H%M%SZ")
readonly PATTERN_DIR_DEFAULT="/etc/citadel/patterns"
readonly LOG_DIR_DEFAULT="/var/log/aiops-prerec"

CI_MODE=0
FINDINGS=0
MODE=""
TARGET_FILE=""
LOG_FILE=""   # finalized after arg parse (depends on CI_MODE)

_log() {
    local msg="[${TS}] $*"
    echo "${msg}" >&2
    [[ -n "${LOG_FILE:-}" ]] && echo "${msg}" >> "${LOG_FILE}" 2>/dev/null || true
}

_finding() {
    FINDINGS=$((FINDINGS + 1))
    _log "FINDING[${FINDINGS}]: $*"
}

_err_exit() {
    echo "[${TS}] ERROR: $*" >&2
    [[ -n "${LOG_FILE:-}" ]] && echo "[${TS}] ERROR: $*" >> "${LOG_FILE}" 2>/dev/null || true
    exit 2
}

# ---- Argument parsing (loop so --ci can compose with a mode) ----------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ci) CI_MODE=1; shift ;;
        --prereceive) MODE="prereceive"; shift ;;
        --selftest) MODE="selftest"; shift ;;
        --file)
            MODE="file"
            TARGET_FILE="${2:-}"
            [[ -z "${TARGET_FILE}" ]] && _err_exit "--file requires a path"
            shift 2 ;;
        "") shift ;;
        *) _err_exit "Unknown argument '$1'" ;;
    esac
done
[[ -z "${MODE}" ]] && MODE="prereceive"

# ---- Resolve PATTERN_DIR / LOG_DIR --------------------------------------------
# Overrides honored ONLY under --ci. Otherwise force hardcoded defaults so the
# PreToolUse / pre-receive gates can never be pointed at an empty/neutered dir.
if [[ ${CI_MODE} -eq 1 ]]; then
    PATTERN_DIR="${PATTERN_DIR:-${PATTERN_DIR_DEFAULT}}"
    LOG_DIR="${LOG_DIR:-${LOG_DIR_DEFAULT}}"
else
    PATTERN_DIR="${PATTERN_DIR_DEFAULT}"
    LOG_DIR="${LOG_DIR_DEFAULT}"
fi
readonly PATTERN_DIR LOG_DIR CI_MODE
LOG_FILE="${LOG_DIR}/${TS}-scanner.log"

# Log dir: fatal in normal modes; non-fatal under --ci (client/CI must not block).
if ! mkdir -p "${LOG_DIR}" 2>/dev/null; then
    if [[ ${CI_MODE} -eq 1 ]]; then
        echo "[${TS}] WARN: cannot create log dir ${LOG_DIR} — continuing (stderr-only logs)" >&2
        LOG_FILE=""
    else
        _err_exit "Cannot create log dir"
    fi
fi

SCANNER_SHA=$(sha256sum "$0" 2>/dev/null | awk '{print $1}' || echo "unknown")
_log "scanner.sh start — mode=${MODE} ci=${CI_MODE} sha=${SCANNER_SHA}"

# Pattern files must exist for every enforcement path (fail-closed). selftest
# builds its own temp patterns and does not depend on the system pattern dir.
if [[ "${MODE}" != "selftest" ]]; then
    [[ -f "${PATTERN_DIR}/institution-patterns.txt" ]] || _err_exit "Missing institution-patterns.txt"
    [[ -f "${PATTERN_DIR}/name-patterns.txt" ]] || _err_exit "Missing name-patterns.txt"
fi

scan_filename() {
    local filepath="$1" base; base=$(basename "${filepath}")
    case "${base}" in
        .env | .env.*) _finding "sensitive filename: ${filepath}" ;;
        id_rsa | id_dsa | id_ecdsa | id_ed25519) _finding "sensitive key file: ${filepath}" ;;
        *.pem | *.key | *.p12 | *.pfx) _finding "sensitive cert/file: ${filepath}" ;;
    esac
}

scan_text() {
    local label="$1" content="$2"
    local pattern _ln
    # Institution-name patterns. Under --ci, NEVER emit the matched literal
    # (would leak bank names into public CI logs).
    if [[ -f "${PATTERN_DIR}/institution-patterns.txt" ]]; then
        while IFS= read -r pattern; do
            [[ "${pattern}" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${pattern// /}" ]] && continue
            if printf '%s' "${content}" | grep -iqE "${pattern}"; then
                if [[ ${CI_MODE} -eq 1 ]]; then
                    _ln=$(printf '%s' "${content}" | grep -inE "${pattern}" | head -n1 | cut -d: -f1)
                    _finding "PII pattern match in ${label}:${_ln:-?}"
                else
                    _finding "institution-name match '${pattern}' in ${label}"
                fi
            fi
        done < "${PATTERN_DIR}/institution-patterns.txt"
    fi
    # Real-name patterns. Same quiet treatment under --ci.
    if [[ -f "${PATTERN_DIR}/name-patterns.txt" ]]; then
        while IFS= read -r pattern; do
            [[ "${pattern}" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${pattern// /}" ]] && continue
            if printf '%s' "${content}" | grep -iqE "${pattern}"; then
                if [[ ${CI_MODE} -eq 1 ]]; then
                    _ln=$(printf '%s' "${content}" | grep -inE "${pattern}" | head -n1 | cut -d: -f1)
                    _finding "PII pattern match in ${label}:${_ln:-?}"
                else
                    _finding "real-name match '${pattern}' in ${label}"
                fi
            fi
        done < "${PATTERN_DIR}/name-patterns.txt"
    fi
    printf '%s' "${content}" | grep -qiE '^sensitivity:[[:space:]]*(restricted|secret)[[:space:]]*$' && _finding "restricted/secret frontmatter in ${label}"
    printf '%s' "${content}" | grep -qE '(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|ghs_[A-Za-z0-9]{36}|glpat-[A-Za-z0-9_-]{20,})' && _finding "known credential pattern in ${label}"
    # b) Key=value with long opaque value (password/secret assignments)
    #    Matches a long opaque value (>20 non-space chars) assigned to a password/secret/key field.
    #
    #    Per-line analysis (NOT content-wide grep -q): a content-wide boolean
    #    cannot tell a literal-secret line apart from an env-read line, so we
    #    iterate lines, match the key=value shape, then EXCLUDE only lines whose
    #    VALUE side is a well-formed env-read / interpolation reference.
    #
    #    Exclusion is anchored to the value side (text after the first = or :)
    #    and is tight by design — fail-closed: any value that is not a clean,
    #    recognised env-read form still flags. We do NOT skip a line merely
    #    because it mentions getenv somewhere; the reference must BE the value.
    #
    #    Recognised env-read value forms (optionally wrapped in str()/String()/
    #    quotes, with optional trailing default/whitespace):
    #      Python : os.getenv(...) | os.environ[...] | os.environ.get(...)
    #      Node   : process.env.X | process.env["X"]
    #      Deno   : Deno.env.get(...)
    #      Java   : System.getenv(...) | System.getProperty(...)
    #      Ruby   : ENV[...] | ENV.fetch(...)
    #      Shell  : ${VAR} | ${VAR:-default} | $VAR
    _secret_assign_re='(password|secret|api_?key|auth_?token|private_?key|access_?key)[[:space:]]*[=:][[:space:]]*[^[:space:]]{20,}'
    # Anchored to the VALUE side: ^<optional wrappers/quotes><env-read><...>$
    _env_read_re='^[[:space:]]*(str\(|String\(|[A-Za-z_][A-Za-z0-9_.]*[[:space:]]*=[[:space:]]*)?[[:space:]]*["'\''`(]*[[:space:]]*(os\.getenv\(|os\.environ\.get\(|os\.environ\[|process\.env\.[A-Za-z_]|process\.env\[|Deno\.env\.get\(|System\.getenv\(|System\.getProperty\(|ENV\.fetch\(|ENV\[|\$\{?[A-Za-z_])'
    while IFS= read -r _line; do
        # Does this line look like a long-value secret assignment?
        printf '%s' "${_line}" | grep -iqE "${_secret_assign_re}" || continue
        # Isolate the value side (everything after the first = or :).
        _value="${_line#*[=:]}"
        # If the VALUE side is a recognised env-read/interpolation form, it is a
        # reference — not a literal credential — so do not flag it.
        if printf '%s' "${_value}" | grep -qE "${_env_read_re}"; then
            continue
        fi
        _finding "secret assignment pattern in ${label}"
        break  # One finding per file is sufficient
    done < <(printf '%s\n' "${content}")
    if printf 'test' | grep -qP '.' 2>/dev/null; then
        local candidate
        # 4c) VALUE-side exemption (mirrors the 4b env-read fix): a candidate of the
        #     shape Directive=<value> is benign config ONLY when the value side is a
        #     short numeric or duration literal (e.g. 300, 5, 30s, 5min, 5m). The test
        #     is anchored to the value (=[0-9]{1,6}<unit>?$): a base64/hex/sk-ant value
        #     contains letters and never matches, so a high-entropy value still flags
        #     even after a known directive keyword — keyword presence grants no pass.
        local _dir_dur_re='^[A-Za-z][A-Za-z0-9]*=[0-9]{1,6}(ns|us|ms|s|m|h|d|min|sec|hr)?$'
        while IFS= read -r candidate; do
            [[ ${#candidate} -lt 20 ]] && continue
            [[ "${candidate}" =~ ^-[0-9a-f]+$ ]] && continue
            [[ "${candidate}" =~ ^https?:// ]] && continue
            [[ "${candidate}" =~ ^sha[0-9]+-[A-Za-z0-9+/=]+ ]] && continue  # npm integrity hash
            [[ "${candidate:0:1}" == "/" ]] && continue                       # skip absolute paths
            printf '%s' "${candidate}" | grep -qE "${_dir_dur_re}" && continue # systemd Directive=<short numeric/duration> is benign config
            local ha=0 hl=0 hd=0
            [[ "${candidate}" =~ [A-Z] ]] && ha=1
            [[ "${candidate}" =~ [a-z] ]] && hl=1
            [[ "${candidate}" =~ [0-9] ]] && hd=1
            [[ $((ha+hl+hd)) -ge 3 && ${#candidate} -ge 24 ]] && _finding "high-entropy string (len=${#candidate}) in ${label}: ${candidate:0:8}..." && break
        done < <(printf '%s' "${content}" | grep -oP '[A-Za-z0-9+/=!@#^_-]{20,}' 2>/dev/null || true)
    fi
}

run_selftest() {
    # Regression fixtures. Control fixtures for the 4c exemption are BUILT AT
    # RUNTIME from fragments so the full secret pattern never appears as a literal
    # in this source. Integration fixtures (a–e) use a TEMP sentinel pattern dir
    # so the selftest never depends on (or emits) real /etc/citadel patterns.
    local fails=0
    local self="$0"

    # ---------- In-process unit fixtures (4c directive exemption) ----------
    _st() {
        FINDINGS=0
        scan_text "selftest" "$1"
        if [[ "$2" == "clean" && ${FINDINGS} -ne 0 ]]; then echo "SELFTEST FAIL (expected clean): $3 -> findings=${FINDINGS}" >&2; fails=$((fails+1)); fi
        if [[ "$2" == "flag"  && ${FINDINGS} -lt 1 ]]; then echo "SELFTEST FAIL (expected flag):  $3 -> findings=${FINDINGS}" >&2; fails=$((fails+1)); fi
    }
    # FP fixtures — MUST be clean (0 findings):
    _st 'StartLimitIntervalSec=300' clean 'FP StartLimitIntervalSec=300'
    _st 'StartLimitBurst=5'         clean 'FP StartLimitBurst=5'
    _st 'RestartSec=5'              clean 'FP RestartSec=5'
    # Control fixtures — MUST still flag (>=1 finding):
    local _sk; _sk="sk-""ant-$(printf 'a%.0s' $(seq 1 24))"
    _st "API_KEY=${_sk}" flag 'control sk-ant literal still flags'
    local _hi; _hi="Directive=$(printf 'aB3%.0s' $(seq 1 10))"
    _st "${_hi}" flag 'control high-entropy value after directive keyword still flags'

    # ---------- Integration fixtures (subprocess, --ci contract) ----------
    local tmproot ptmp
    tmproot=$(mktemp -d) || { echo "SELFTEST FAIL: mktemp" >&2; return 1; }
    # shellcheck disable=SC2064
    trap "rm -rf '${tmproot}'" RETURN
    ptmp="${tmproot}/patterns"
    mkdir -p "${ptmp}"
    # Sentinel patterns — match nothing real; safe to print in any context.
    printf '%s\n' 'ACMEHOLDINGS_SENTINEL' > "${ptmp}/institution-patterns.txt"
    printf '%s\n' 'ZZSENTINELNAME' > "${ptmp}/name-patterns.txt"
    local pii_file="${tmproot}/leak.txt"
    printf 'line one\nmy institution is ACMEHOLDINGS_SENTINEL here\nline three\n' > "${pii_file}"

    # (a) --ci must NOT emit the matched literal; must emit generic PII finding; rc=1
    local out rc
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${pii_file}" 2>&1); rc=$?
    [[ ${rc} -eq 1 ]] || { echo "SELFTEST FAIL (a): expected rc=1 got ${rc}" >&2; fails=$((fails+1)); }
    if printf '%s' "${out}" | grep -q 'ACMEHOLDINGS_SENTINEL'; then
        echo "SELFTEST FAIL (a): --ci leaked the matched pattern literal" >&2; fails=$((fails+1)); fi
    if ! printf '%s' "${out}" | grep -q 'PII pattern match'; then
        echo "SELFTEST FAIL (a): --ci did not emit generic PII finding" >&2; fails=$((fails+1)); fi

    # (b) PATTERN_DIR override MUST be ignored WITHOUT --ci (forces system dir).
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --file "${pii_file}" 2>&1); rc=$?
    if printf '%s' "${out}" | grep -q 'ACMEHOLDINGS_SENTINEL'; then
        echo "SELFTEST FAIL (b): PATTERN_DIR override honored without --ci" >&2; fails=$((fails+1)); fi
    if [[ ${rc} -eq 1 ]] && printf '%s' "${out}" | grep -qiE 'name match|PII pattern'; then
        echo "SELFTEST FAIL (b): sentinel matched via override without --ci" >&2; fails=$((fails+1)); fi

    # (c) Missing/unwritable log dir must be NON-FATAL under --ci (rc must not be 2).
    out=$(env PATTERN_DIR="${ptmp}" LOG_DIR="/proc/nonexistent-$$/nope" "${self}" --ci --file "${pii_file}" 2>&1); rc=$?
    [[ ${rc} -ne 2 ]] || { echo "SELFTEST FAIL (c): missing log dir fatal under --ci (rc=2)" >&2; fails=$((fails+1)); }

    # (d) New-branch client scan catches a planted finding (boundary-base path).
    local repo="${tmproot}/repo"
    mkdir -p "${repo}"
    (
        cd "${repo}" || exit 9
        git init -q
        git config user.email t@example.invalid; git config user.name tester
        git commit -q --allow-empty -m base
        git update-ref refs/remotes/origin/main HEAD      # simulate a remote-tracking base
        printf 'leak ACMEHOLDINGS_SENTINEL planted\n' > leak.txt
        git add leak.txt; git commit -q -m feature
    ) || { echo "SELFTEST FAIL (d): repo setup" >&2; fails=$((fails+1)); }
    local newoid base nb_out nb_rc bug_out
    newoid=$(cd "${repo}" && git rev-parse HEAD)
    base=$(cd "${repo}" && git rev-list --boundary "${newoid}" --not --remotes 2>/dev/null | sed -n 's/^-//p' | head -n1)
    # The FIX: base..local captures the new commit. (The buggy `--not --branches`
    # would be empty because the commit is already on a local branch.)
    bug_out=$(cd "${repo}" && git rev-list "${newoid}" --not --branches 2>/dev/null)
    [[ -z "${bug_out}" ]] || echo "SELFTEST NOTE (d): --not --branches unexpectedly non-empty" >&2
    if [[ -z "${base}" ]]; then
        echo "SELFTEST FAIL (d): could not resolve boundary base" >&2; fails=$((fails+1))
    else
        nb_out=$(cd "${repo}" && printf '%s %s %s\n' "${base}" "${newoid}" "refs/heads/feature" \
                  | env PATTERN_DIR="${ptmp}" "${self}" --ci --prereceive 2>&1); nb_rc=$?
        [[ ${nb_rc} -eq 1 ]] || { echo "SELFTEST FAIL (d): new-branch scan missed planted finding (rc=${nb_rc})" >&2; fails=$((fails+1)); }
        if printf '%s' "${nb_out}" | grep -q 'ACMEHOLDINGS_SENTINEL'; then
            echo "SELFTEST FAIL (d): --ci prereceive leaked literal" >&2; fails=$((fails+1)); fi
    fi

    # (e) Existing non-ci behavior unchanged: a planted credential flags; a clean
    #     file passes. (Run under --ci so it does not require system patterns; the
    #     credential regex is mode-independent.)
    local cred_file="${tmproot}/cred.txt" clean_file="${tmproot}/clean.txt"
    local _sk2; _sk2="sk-""ant-$(printf 'b%.0s' $(seq 1 30))"
    printf 'token=%s\n' "${_sk2}" > "${cred_file}"
    printf 'just some ordinary text\n' > "${clean_file}"
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${cred_file}" 2>&1); rc=$?
    [[ ${rc} -eq 1 ]] || { echo "SELFTEST FAIL (e): credential file not flagged (rc=${rc})" >&2; fails=$((fails+1)); }
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${clean_file}" 2>&1); rc=$?
    [[ ${rc} -eq 0 ]] || { echo "SELFTEST FAIL (e): clean file flagged (rc=${rc})" >&2; fails=$((fails+1)); }

    if [[ ${fails} -eq 0 ]]; then echo "[CITADEL] selftest PASS"; return 0; fi
    echo "[CITADEL] selftest FAILED — ${fails} case(s)" >&2; return 1
}

run_prereceive() {
    local oldrev newrev refname
    while read -r oldrev newrev refname; do
        _log "ref: ${refname}  old=${oldrev:0:8}  new=${newrev:0:8}"
        [[ "${newrev}" == "0000000000000000000000000000000000000000" ]] && _log "skip: deletion" && continue
        local commits=""
        if [[ "${oldrev}" == "0000000000000000000000000000000000000000" ]]; then
            commits=$(git rev-list "${newrev}" --not --branches 2>/dev/null || git rev-list "${newrev}" 2>/dev/null || echo "")
        else
            commits=$(git rev-list "${oldrev}..${newrev}" 2>/dev/null || echo "")
        fi
        [[ -z "${commits}" ]] && _log "no new commits" && continue
        while IFS= read -r commit; do
            [[ -z "${commit}" ]] && continue
            _log "commit: ${commit:0:8}"
            # Enumerate changed files. --root makes diff-tree emit the full tree
            # for a parentless (root/orphan) commit; no-op for normal commits.
            # Capture explicitly and fail closed if diff-tree errors (no || true).
            local files=""
            if ! files=$(git diff-tree --root --no-commit-id -r --name-only "${commit}"); then
                _err_exit "diff-tree failed for ${commit:0:8} — failing closed"
            fi
            while IFS= read -r filepath; do
                [[ -z "${filepath}" ]] && continue
                scan_filename "${filepath}"
                local content=""
                content=$(git show "${commit}:${filepath}" 2>/dev/null) || { _log "WARN: cannot read ${filepath}"; continue; }
                scan_text "${filepath}@${commit:0:8}" "${content}"
            done <<< "${files}"
        done <<< "${commits}"
    done
    _log "scan complete — findings=${FINDINGS}"
    if [[ ${FINDINGS} -gt 0 ]]; then
        _log "REJECTED: ${FINDINGS} finding(s)"
        echo "" >&2; echo "╔ CITADEL SCAN GATE: PUSH REJECTED - ${FINDINGS} finding(s). See ${LOG_FILE:-stderr}" >&2
        return 1
    fi
    _log "ACCEPTED"
    echo "[CITADEL] scan gate: ACCEPTED (sha=${SCANNER_SHA:0:12})" >&2
    return 0
}

run_file() {
    [[ -f "${TARGET_FILE}" ]] || _err_exit "File not found: ${TARGET_FILE}"
    _log "scanning file: ${TARGET_FILE}"
    scan_filename "${TARGET_FILE}"
    local content=""
    content=$(cat "${TARGET_FILE}") || _err_exit "Cannot read file: ${TARGET_FILE}"
    scan_text "${TARGET_FILE}" "${content}"
    _log "scan complete — findings=${FINDINGS}"
    [[ ${FINDINGS} -gt 0 ]] && { echo "CITADEL: write blocked - ${FINDINGS} finding(s). See ${LOG_FILE:-stderr}" >&2; return 1; }
    return 0
}

case "${MODE}" in
    prereceive) run_prereceive; exit $? ;;
    file) run_file; exit $? ;;
    selftest) run_selftest; exit $? ;;
esac
