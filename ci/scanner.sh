#!/usr/bin/env bash
# ci/scanner.sh — personal-data / secret scan gate (portable, dependency-free)
#
# Enforcement points:
#   1. Pre-write hook — blocks a sensitive write before it hits disk
#   2. Client pre-commit hook
#   3. Client pre-push hook  [--ci]
#   4. Server-side pre-receive hook — cannot be bypassed with --no-verify
#   + GitHub Actions backstop job — public CI, authoritative + unbypassable [--ci]
#
# Modes / flags:
#   ci/scanner.sh --prereceive       reads git stdin (pre-receive mode)
#   ci/scanner.sh --file <path>      scans a single file
#   ci/scanner.sh --selftest         regression self-check
#   ci/scanner.sh                    no args → prereceive mode (hook symlink compat)
#   ci/scanner.sh --ci ...           CLIENT/CI-safe modifier (see below)
#
# --ci modifier (composes with --prereceive / --file):
#   * Quiet output: a sensitive-pattern match prints "PII pattern match in
#     <file>:<line>" WITHOUT the matched literal, so no sensitive value reaches
#     public CI logs. (Generic credential/secret/entropy findings print as normal.)
#   * PATTERN_DIR / LOG_DIR env overrides are honored ONLY under --ci. In normal
#     modes they are ignored and the pattern source is fixed by the host install
#     config (see below), so the local gate cannot be neutered by the environment.
#   * A missing/unwritable log dir is NON-FATAL under --ci (warn + continue) so a
#     client/CI box that cannot write its log dir is never blocked. Fatal otherwise.
#
# Exit codes:
#   0 = clean
#   1 = finding (push/write blocked)
#   2 = error   (fail-closed — git rejects push on any non-zero)
#
# Pattern source:
#   Every *.txt file in the resolved pattern dir is loaded as a newline list of
#   regex patterns. Defaults are portable and repo-relative; a deployed host
#   supplies its real (non-public) pattern/log dirs via an install-time config
#   file that is NOT part of this repo (see the resolution block below). The
#   public source contains no host-specific absolute paths or pattern categories.
#
# Logs: <resolved-log-dir>/YYYYMMDDTHHMMSSZ-scanner.log

set -uo pipefail

TS=$(date -u +"%Y%m%dT%H%M%SZ")
# Portable, project-neutral defaults. A deployed host overrides these via the
# install-time config sourced in the resolution block below; the public source
# carries no host-specific absolute paths.
readonly PATTERN_DIR_DEFAULT="${SCANNER_PATTERN_DIR:-.ci/patterns}"
readonly LOG_DIR_DEFAULT="${SCANNER_LOG_DIR:-${TMPDIR:-/tmp}/scan-gate-logs}"
readonly INSTALL_CONF_DEFAULT="/etc/scan-gate/scanner.conf"

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
# Resolution precedence:
#   * A deployed host MAY supply its real (non-public) pattern/log dirs via an
#     install-time config file — root-owned, OUTSIDE this repo — that sets
#     INSTALL_PATTERN_DIR / INSTALL_LOG_DIR. Because it is a SOURCED file, not an
#     environment variable, it CANNOT be neutered by an env override: this
#     preserves the "the local gate cannot be pointed at an empty/neutered dir"
#     guarantee that a hardcoded path previously provided.
#   * Environment overrides (PATTERN_DIR / LOG_DIR) are honored ONLY under --ci,
#     which is explicitly best-effort/bypassable (the authoritative gate is the
#     server-side CI backstop, which injects its own pattern dir). In normal
#     modes env overrides are ignored.
#   * Otherwise fall back to the portable, repo-relative defaults.
INSTALL_PATTERN_DIR=""
INSTALL_LOG_DIR=""
if [[ ${CI_MODE} -eq 1 ]]; then
    _install_conf="${SCANNER_INSTALL_CONF:-${INSTALL_CONF_DEFAULT}}"
    # shellcheck disable=SC1090
    [[ -r "${_install_conf}" ]] && source "${_install_conf}"
    PATTERN_DIR="${PATTERN_DIR:-${INSTALL_PATTERN_DIR:-${PATTERN_DIR_DEFAULT}}}"
    LOG_DIR="${LOG_DIR:-${INSTALL_LOG_DIR:-${LOG_DIR_DEFAULT}}}"
else
    # Fixed install-conf path (NOT env-overridable) so the local gate's pattern
    # source is controlled only by root, never by the calling environment.
    # shellcheck disable=SC1090
    [[ -r "${INSTALL_CONF_DEFAULT}" ]] && source "${INSTALL_CONF_DEFAULT}"
    PATTERN_DIR="${INSTALL_PATTERN_DIR:-${PATTERN_DIR_DEFAULT}}"
    LOG_DIR="${INSTALL_LOG_DIR:-${LOG_DIR_DEFAULT}}"
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

# At least one pattern file must exist for every enforcement path (fail-closed).
# selftest builds its own temp patterns and does not depend on the host dir.
if [[ "${MODE}" != "selftest" ]]; then
    shopt -s nullglob
    _pat_files=("${PATTERN_DIR}"/*.txt)
    shopt -u nullglob
    [[ ${#_pat_files[@]} -gt 0 ]] || _err_exit "No pattern files (*.txt) in ${PATTERN_DIR}"
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
    local pattern _ln _pf
    # Sensitive-data patterns, loaded from EVERY *.txt in the pattern dir. The
    # public source names no wordlist categories. Under --ci, NEVER emit the
    # matched literal (would leak a sensitive value into public CI logs); emit a
    # generic PII finding with the line number instead.
    for _pf in "${PATTERN_DIR}"/*.txt; do
        [[ -f "${_pf}" ]] || continue
        while IFS= read -r pattern; do
            [[ "${pattern}" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${pattern// /}" ]] && continue
            if printf '%s' "${content}" | grep -iqE "${pattern}"; then
                if [[ ${CI_MODE} -eq 1 ]]; then
                    _ln=$(printf '%s' "${content}" | grep -inE "${pattern}" | head -n1 | cut -d: -f1)
                    _finding "PII pattern match in ${label}:${_ln:-?}"
                else
                    _finding "sensitive-pattern match '${pattern}' in ${label}"
                fi
            fi
        done < "${_pf}"
    done
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
    _secret_assign_re='(password|secret(_?key)?|api_?key|auth_?token|private_?key|access_?key)[[:space:]]*[=:][[:space:]]*[^[:space:]]{20,}'
    # Anchored to the VALUE side: ^<optional wrappers/quotes><env-read><...>$
    _env_read_re='^[[:space:]]*(str\(|String\(|[A-Za-z_][A-Za-z0-9_.]*[[:space:]]*=[[:space:]]*)?[[:space:]]*["'\''`(]*[[:space:]]*(os\.getenv\(|os\.environ\.get\(|os\.environ\[|process\.env\.[A-Za-z_]|process\.env\[|Deno\.env\.get\(|System\.getenv\(|System\.getProperty\(|ENV\.fetch\(|ENV\[|\$\{?[A-Za-z_])'
    # POSITIVE literal test (fail-closed on ambiguity is NOT applied here — a
    # secret finding requires a HARDCODED LITERAL right-hand side). The rule flags
    # ONLY when the value side is a quoted string literal or a bare high-entropy
    # token. Every COMPUTED / reference RHS is exempt because it holds no literal
    # secret: env reads (above), function calls `name(...)`, and bare
    # identifiers / attribute access `x`/`obj.attr`. Bare high-entropy secret
    # TOKENS remain covered by the known-credential regex and the entropy scanner
    # below, so narrowing 4b to literals does not widen any real-secret exemption.
    _quoted_literal_re='^[[:space:]]*["'\''`]'                       # value starts with a quote -> string literal
    _func_call_re='^[[:space:]]*[A-Za-z_][A-Za-z0-9_.]*[[:space:]]*\('  # name(...) -> computed, exempt
    _bare_ref_re='^[[:space:]]*[A-Za-z_][A-Za-z0-9_.]*[[:space:]]*[,;)]*[[:space:]]*$'  # ident / obj.attr -> exempt
    while IFS= read -r _line; do
        # Does this line look like a long-value secret assignment?
        printf '%s' "${_line}" | grep -iqE "${_secret_assign_re}" || continue
        # Isolate the value side (everything after the first = or :).
        _value="${_line#*[=:]}"
        # 1) env-read / interpolation reference -> not a literal -> exempt.
        printf '%s' "${_value}" | grep -qE "${_env_read_re}" && continue
        # 2) quoted string literal -> hardcoded secret -> FLAG.
        if printf '%s' "${_value}" | grep -qE "${_quoted_literal_re}"; then
            _finding "secret assignment pattern in ${label}"
            break
        fi
        # 3) function call -> computed value (e.g. hash_password(...)) -> exempt.
        printf '%s' "${_value}" | grep -qE "${_func_call_re}" && continue
        # 4) bare identifier / attribute access -> reference -> exempt.
        printf '%s' "${_value}" | grep -qE "${_bare_ref_re}" && continue
        # 5) remaining bare token: FLAG only if it is a high-entropy secret token
        #    (mixed classes and long). Numeric/short/simple tokens are exempt.
        _tok="${_value#"${_value%%[![:space:]]*}"}"   # left-trim whitespace
        _tok="${_tok%%[[:space:],;)]*}"               # first token only
        _ta=0; _tl=0; _td=0
        [[ "${_tok}" =~ [A-Z] ]] && _ta=1
        [[ "${_tok}" =~ [a-z] ]] && _tl=1
        [[ "${_tok}" =~ [0-9] ]] && _td=1
        if [[ $((_ta+_tl+_td)) -ge 2 && ${#_tok} -ge 20 ]]; then
            _finding "secret assignment pattern in ${label}"
            break  # One finding per file is sufficient
        fi
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
    # so the selftest never depends on (or emits) the host's real patterns.
    local fails=0
    # Resolve to an ABSOLUTE path: case (d) invokes "${self}" from inside a temp
    # repo (cd "${repo}"), so a relative $0 (e.g. ci/scanner.sh) would fail to
    # resolve there -> rc=127. Absolute path makes --selftest cwd-independent.
    local self
    self="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$(basename "$0")"
    [[ -f "${self}" ]] || self="$0"   # fallback if resolution fails

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

    # ---------- Secret-assignment env-read exemption (4b) ----------
    # FP fixtures — env-var READS must be CLEAN. This is the v1.4.1 main.py:101
    # false positive (owner_password = os.getenv(...)) that this fix targets.
    _st 'owner_password = os.getenv("FIRST_RUN_OWNER_PASSWORD")' clean 'FP env-read owner_password = os.getenv()'
    _st 'api_key = os.environ["X"]'    clean 'FP env-read api_key = os.environ[]'
    _st 'secret = os.environ.get("Y")' clean 'FP env-read secret = os.environ.get()'
    # FP fixtures — COMPUTED (non-literal) RHS must be CLEAN. This is the v1.4.1
    # main.py:107 false positive (hashed_password=hash_password(...)) that round-1
    # missed: the value is a function call / reference, not a hardcoded literal.
    # Built at runtime (keyword split off '=') to avoid self-tripping on scan.
    local _fc1 _fc2 _ba1
    _fc1="hashed_password""=hash_password(owner_password_value)"
    _fc2="secret"" = compute_secret_from_config(app_configuration)"
    _ba1="api_key"" = settings.integration_api_key_value_ref"
    _st "${_fc1}" clean 'FP func-call RHS hash_password()'
    _st "${_fc2}" clean 'FP func-call RHS some_func()'
    _st "${_ba1}" clean 'FP bare attribute-access RHS obj.attr'
    # Control fixtures — hardcoded literals MUST still flag. Built at runtime so the
    # keyword never sits adjacent to '=' in THIS source (prevents self-trip on scan).
    local _lit; _lit="SECRET""_KEY = \"hardcoded-literal-abc123\""
    _st "${_lit}" flag 'control SECRET_KEY quoted literal still flags'
    local _ghp; _ghp="token = \"ghp_""$(printf 'a%.0s' $(seq 1 36))\""
    _st "${_ghp}" flag 'control ghp_ quoted literal still flags'

    # ---------- Integration fixtures (subprocess, --ci contract) ----------
    local tmproot ptmp
    tmproot=$(mktemp -d) || { echo "SELFTEST FAIL: mktemp" >&2; return 1; }
    # shellcheck disable=SC2064
    trap "rm -rf '${tmproot}'" RETURN
    ptmp="${tmproot}/patterns"
    mkdir -p "${ptmp}"
    # Sentinel patterns — match nothing real; safe to print in any context.
    printf '%s\n' 'ACMEHOLDINGS_SENTINEL' > "${ptmp}/patterns-a.txt"
    printf '%s\n' 'ZZSENTINELNAME' > "${ptmp}/patterns-b.txt"
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

    if [[ ${fails} -eq 0 ]]; then echo "[scan-gate] selftest PASS"; return 0; fi
    echo "[scan-gate] selftest FAILED — ${fails} case(s)" >&2; return 1
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
        echo "" >&2; echo "╔ SCAN GATE: PUSH REJECTED - ${FINDINGS} finding(s). See ${LOG_FILE:-stderr}" >&2
        return 1
    fi
    _log "ACCEPTED"
    echo "[scan-gate] scan gate: ACCEPTED (sha=${SCANNER_SHA:0:12})" >&2
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
    [[ ${FINDINGS} -gt 0 ]] && { echo "scan-gate: write blocked - ${FINDINGS} finding(s). See ${LOG_FILE:-stderr}" >&2; return 1; }
    return 0
}

case "${MODE}" in
    prereceive) run_prereceive; exit $? ;;
    file) run_file; exit $? ;;
    selftest) run_selftest; exit $? ;;
esac
