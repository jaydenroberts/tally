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
#   ci/scanner.sh --tree <ref>       scans EVERY blob in the tree at <ref>
#   ci/scanner.sh --history          scans every blob reachable from every ref
#   ci/scanner.sh --selftest         regression self-check
#   ci/scanner.sh                    no args → prereceive mode (hook symlink compat)
#
# Diff modes vs tree modes — they answer different questions and you need both:
#   --prereceive answers "is what this push ADDS clean". It is blind to anything
#   that predates the gate, and blind to the tag path entirely.
#   --tree answers "is this ARTIFACT clean" and is the correct gate at publish
#   time. --history answers "has anything ever been clean-missed", on a schedule,
#   against a committed baseline of accepted residual findings.
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
# Identity pin (optional, fail-CLOSED when present):
#   The install-time config MAY set INSTALL_SCANNER_SHA256=<sha256 of this file>.
#   When it is set, every ENFORCEMENT invocation (--prereceive / --file) verifies
#   its OWN sha256 against it and exits 2 on mismatch. --selftest is exempt, so a
#   candidate can still be validated before it is installed.
#
#   WHY the pin lives in the config and not in this file: a constant inside a file
#   cannot equal the hash of the file that contains it. Putting it in the
#   root-owned config also makes it unwritable by the unprivileged process that
#   writes the repo, so checking out an OLDER ci/scanner.sh cannot bring a
#   matching pin along with it — which is the entire point. Every enforcement
#   point that runs this gate execs THIS file from a
#   mutable worktree, so every one of them is covered by one check here and none
#   has to remember to verify anything.
#
#   Landing a new scanner is therefore TWO steps, IN THIS ORDER:
#     1. install the new ci/scanner.sh
#     2. root: update INSTALL_SCANNER_SHA256 in the install config
#   Between them the gate fails closed. If the gate is wedged on identity the fix
#   is a ROOT EDIT OF THE CONFIG — never an edit of this file.
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

# Standalone-entropy DENSITY thresholds (rule 4d, see _entropy_is_dense below).
# ENTROPY_DENSE_RUN_MIN — chars in ONE separator-free run that alone carries all
#   three character classes. ENTROPY_TRANS_PCT — class transitions per 100 class
#   chars across the whole candidate. Either one qualifies (OR): the run test
#   catches contiguous blobs, the transition test catches separator-peppered
#   base64url. Both are ANDed onto the pre-existing 3-class/len>=24 test, so
#   rule 4d can only REMOVE findings, never add one.
readonly ENTROPY_DENSE_RUN_MIN=16
readonly ENTROPY_TRANS_PCT=20

CI_MODE=0
FINDINGS=0
MODE=""
TARGET_FILE=""
TARGET_REF=""
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

# ---- Content matching (NEVER via a pipeline) --------------------------------
# WHY these helpers exist, and why every match in this file must go through one:
# the previous form
#     printf '%s' "${content}" | grep -qE "${pattern}"
# was a silent FAIL-OPEN. `grep -q` exits at the FIRST match; `printf` is then
# killed by SIGPIPE (status 141); `set -o pipefail` promotes 141 to the status of
# the whole pipeline; and the `if` therefore reads FALSE *because* the pattern
# matched. A real finding was discarded precisely because it matched early.
#
# Measured against the unpatched gate (sentinel on line 1, body size varied):
#   <= 61 KB   blocked correctly
#   ~61-70 KB  RACE — pipe-buffer fill vs. grep exit. The SAME bytes were
#              REJECTED on one run and ACCEPTED on the next, so a simple retry
#              after a block could push content through. This was the more
#              dangerous property of the two.
#   >= 128 KB  deterministically blind to an early match.
#
# A herestring is a REDIRECT, not a pipeline: grep reads a temp file, no process
# can receive SIGPIPE, and $? is grep's status alone. It is also ~2x faster here,
# because it forks no `printf`.
#
# Herestrings append exactly one trailing newline. That can only TERMINATE a final
# unterminated line, so it may let a match be seen that was already intended to be
# seen — it can add a finding, never remove one.
#
# `-e` guards a pattern that begins with '-' from being parsed as an option.
# Grep's rc=2 (bad regex) stays falsey exactly as it did before this change.
#
#   _match  <text> <ere>   case-SENSITIVE      _imatch <text> <ere>  case-INSENSITIVE
# Returns 0 = matched, 1 = no match, 2 = grep error.
_match()  { grep -qE  -e "$2" <<<"$1"; }
_imatch() { grep -qiE -e "$2" <<<"$1"; }

# ---- Argument parsing (loop so --ci can compose with a mode) ----------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ci) CI_MODE=1; shift ;;
        --prereceive) MODE="prereceive"; shift ;;
        --selftest) MODE="selftest"; shift ;;
        --history) MODE="history"; shift ;;
        --file)
            MODE="file"
            TARGET_FILE="${2:-}"
            [[ -z "${TARGET_FILE}" ]] && _err_exit "--file requires a path"
            shift 2 ;;
        --tree)
            MODE="tree"
            TARGET_REF="${2:-}"
            [[ -z "${TARGET_REF}" ]] && _err_exit "--tree requires a ref"
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
INSTALL_SCANNER_SHA256=""
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

# ---- IDENTITY ASSERTION (fail CLOSED) ---------------------------------------
# The gate previously asserted nothing about WHICH version of itself was running,
# and every enforcement point execs this file out of a mutable worktree. Observed
# in practice: a single workflow pushed under the NEW scanner (server-side
# pre-receive, with the fixed file checked out) and then ran its own fail-closed
# local scan under the OLD one, because an intervening branch checkout had not
# yet received the fix. Same run, two gates, no warning — the sha was already
# LOGGED at both points, it was simply never COMPARED.
#
# The pin is read from the root-owned install config (see the header). Absent pin
# = no assertion, i.e. byte-for-byte the previous behaviour, so a public clone,
# a fresh checkout and GitHub Actions are all unaffected.
#
# --selftest is exempt on purpose: it is not an enforcement path, and blocking it
# would make it impossible to validate the very replacement that fixes a skew.
_EXPECT_SHA="${INSTALL_SCANNER_SHA256//[[:space:]]/}"
_EXPECT_SHA="${_EXPECT_SHA,,}"
readonly _EXPECT_SHA
if [[ "${MODE}" != "selftest" && -n "${_EXPECT_SHA}" ]]; then
    if [[ "${SCANNER_SHA}" == "unknown" || -z "${SCANNER_SHA}" ]]; then
        _err_exit "scanner identity is pinned but sha256 of $0 could not be computed — failing closed"
    fi
    if [[ "${SCANNER_SHA}" != "${_EXPECT_SHA}" ]]; then
        _err_exit "scanner identity mismatch: running ${SCANNER_SHA:0:12} from $0, install pin expects ${_EXPECT_SHA:0:12} — failing closed (fix the INSTALL, or update the pin as root; never edit this file to pass)"
    fi
    _log "identity: OK (pinned ${_EXPECT_SHA:0:12})"
fi

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
    # Pattern files are the personal-data wordlist this gate exists to protect,
    # and the CONTENT rules provably cannot catch them: a pattern written as
    # \bName\b is preceded by the alnum 'b' of its own escape, so the
    # word-boundary form cannot match itself. Measured — a copy of the real name
    # pattern file scans clean, while the same names with the escapes stripped
    # flag immediately. So detect them by PATH instead.
    #
    # This arm is FIRST and unconditional so that no waiver added later can
    # shadow it, and it is deliberately not paired with a content scan: there is
    # no legitimate reason for this path to appear in a commit at all.
    case "${filepath}" in
        .ci/patterns/* | */.ci/patterns/*)
            _finding "scan-gate pattern file must never be committed: ${filepath}" ;;
    esac
    case "${base}" in
        .env.example | .env.sample | .env.template | .env.dist)
            # Convention-named TEMPLATE files. Placeholder values by definition,
            # and expected to be present in a public repo.
            #
            # Only the FILENAME heuristic is waived, never the content scan: every
            # caller runs scan_text over the bytes immediately after this returns,
            # so a real secret pasted into a template is still caught on content.
            # Waiving the name rule stops a near-universal OSS file from flagging
            # on every single scan, which is the pressure that gets gates
            # switched off or routed around.
            _log "skip filename rule: env template ${filepath}" ;;
        .env | .env.*) _finding "sensitive filename: ${filepath}" ;;
        id_rsa | id_dsa | id_ecdsa | id_ed25519) _finding "sensitive key file: ${filepath}" ;;
        *.pem | *.key | *.p12 | *.pfx) _finding "sensitive cert/file: ${filepath}" ;;
    esac
}

# 4d) DENSITY test for the standalone entropy rule (rule 4c below).
#
# WHY a density test and not a longer length / higher class bar: the 3-class test
# was applied to the WHOLE candidate, so a string reached 3 classes merely by
# CONCATENATING single-class parts. Dated document filenames do exactly
# that — a name like YYYY-MM-DD-<kebab words>-<priority tag> is digits plus
# dictionary words plus a tag like P-one: every segment is single-class, yet the
# whole string clears 3 classes and 24+ chars and was flagged. (Written in parts,
# not as a literal example: a contiguous specimen here would itself be a 37-char
# candidate, and the pre-write gate that blocks it is the one being fixed.)
# Real secret material is DENSE: its class mixing happens INSIDE an unbroken run,
# because every character is drawn independently from a mixed alphabet.
#
# Two measurements, ORed (either qualifies):
#   run   — longest run of NON-separator chars that by itself carries 3 classes.
#           Catches contiguous base64/hex/random tokens. The slug's longest such
#           run is ZERO chars: no segment of it holds 3 classes.
#   trans — class transitions per 100 class chars, counted WITHIN segments only.
#           Catches base64url tokens chopped short by their own '-'/'_' chars.
#           Random base64 measures ~60; the slug measures 3.
#
# ONLY '-' and '_' separate. '+', '/', '=' are base64 alphabet characters and
# never identifier separators, so they must not break a run — treating them as
# separators would shred exactly the tokens this rule exists to catch.
#
# Returns 0 (dense -> keep the finding) / 1 (structured identifier -> drop it).
_entropy_is_dense() {
    # NOTE: two statements, not one. `local a=$1 b=${#a}` expands EVERY argument
    # in the CALLER's scope before assigning any of them, so ${#s} would read an
    # unset global and abort the whole scanner under `set -u`.
    local s="$1"
    local n=${#s} i ch k prev="" t=0 nc=0 seglen=0 sa=0 sl=0 sd=0 run=0
    for ((i = 0; i < n; i++)); do
        ch="${s:i:1}"
        case "${ch}" in
            [A-Z]) k=U ;;
            [a-z]) k=L ;;
            [0-9]) k=D ;;
            -|_)   # separator: closes the run and breaks class adjacency
                   (( sa + sl + sd >= 3 && seglen > run )) && run=${seglen}
                   prev=""; seglen=0; sa=0; sl=0; sd=0; continue ;;
            *)     # + / = ! @ # ^ : classless filler, extends the run
                   seglen=$((seglen + 1)); continue ;;
        esac
        seglen=$((seglen + 1)); nc=$((nc + 1))
        [[ -n "${prev}" && "${prev}" != "${k}" ]] && t=$((t + 1))
        prev="${k}"
        case "${k}" in U) sa=1 ;; L) sl=1 ;; D) sd=1 ;; esac
    done
    (( sa + sl + sd >= 3 && seglen > run )) && run=${seglen}
    (( run >= ENTROPY_DENSE_RUN_MIN )) && return 0
    (( nc > 0 && t * 100 >= nc * ENTROPY_TRANS_PCT )) && return 0
    return 1
}

# 4e) PATH-SHAPE test for the standalone entropy rule (rule 4c below).
#
# WHY this exists, and why it is NOT the leading-'/' test one line above it: the
# candidate extraction regex EXCLUDES '.', so any path containing a dot component
# is chopped BEFORE the skip ever sees it. A path like
#   /home/<user>/<tooldir>/jobs/<id>/tmp/NOTES<dot>md
# extracts as TWO candidates -- a discarded head, and a tail beginning just after
# the dot component, which no longer starts with '/'. The absolute-path skip is
# structurally unable to see it. The same rule must also clear RELATIVE paths and
# route/index names, which never had a leading '/' to begin with.
#
# Widening the extraction class to include '.' was rejected: longer candidates can
# newly reach the len>=24 bar or newly acquire a third class, which would ADD
# findings. The repair belongs in the skip, which can only ever remove them.
#
# Not a slash COUNT. A "contains >=N slashes" heuristic misfires on ordinary
# base64 (a random 24-char token carries 3+ '/' about 1.6% of the time). This is a
# structural test: split on '/', and require EVERY component to be a plausible
# filename component on TWO independent axes.
#
#   (a) LEXICAL -- each '-'/'_'-joined sub-word must be one of the three shapes a
#       real name part takes: lower/digit word (build, jobs, b1ad829f, v2, 2026),
#       optionally with a camelCase tail (importWizard); PascalCase
#       (ImportWizard); or an acronym/tag (NOTES, README, P1, C). Random base64
#       fails this: an interleaved run like P6im0yQrUEUBtY is none of the three,
#       because an uppercase letter must be followed by lower/digit to open a word
#       and 'UE' is not.
#   (b) ENTROPIC -- no single component may itself qualify as a standalone finding
#       (3 classes AND len>=24 AND dense). This is the backstop for the lexical
#       axis: a short mixed group repeated (aB3 x8) does satisfy the camelCase
#       shape, so axis (a) alone would pass it. Axis (b) fails it on its own
#       merits.
#
# Both axes must hold for every component, and at least two components are
# required. Any single failing component means the candidate is NOT a path and is
# scanned normally -- so this can only ever REMOVE findings, never add one.
#
# Note the ANDed relationship with rule 4d: 4d judges a slashless token, 4e judges
# a slashed one, and 4e delegates its per-component entropy question straight back
# to _entropy_is_dense. Neither weakens the other; a component that IS secret
# material keeps the whole candidate in scope.
#
# Returns 0 (path-shaped -> drop the finding) / 1 (not a path -> keep scanning).
_looks_like_path() {
    local s="$1"
    [[ "${s}" == */* ]] || return 1
    local -a _comp=() _sw=()
    local c w ncomp=0 i j
    # Index loops, NOT `for c in "${_comp[@]}"`: the unquoted-with-default form
    # needed to stay set -u safe on older bash would also be glob-expanded, and an
    # index loop is safe on every bash without either compromise.
    IFS='/' read -r -a _comp <<< "${s}"
    for ((i = 0; i < ${#_comp[@]}; i++)); do
        c="${_comp[i]}"
        [[ -z "${c}" ]] && continue                     # leading or doubled '/'
        [[ "${c}" =~ [A-Za-z0-9] ]] || return 1         # punctuation-only: not a name
        ncomp=$((ncomp + 1))
        # (a) LEXICAL axis
        IFS='-_' read -r -a _sw <<< "${c}"
        for ((j = 0; j < ${#_sw[@]}; j++)); do
            w="${_sw[j]}"
            [[ -z "${w}" ]] && continue
            [[ "${w}" =~ ^[a-z0-9]+([A-Z][a-z0-9]+)*$ ]] && continue   # word / camelCase
            [[ "${w}" =~ ^([A-Z][a-z0-9]+)+$ ]] && continue            # PascalCase
            [[ "${w}" =~ ^[A-Z0-9]+$ ]] && continue                    # ACRONYM / TAG
            return 1
        done
        # (b) ENTROPIC axis -- reuses the rule's OWN bar, unmodified.
        local ca=0 cl=0 cd=0
        [[ "${c}" =~ [A-Z] ]] && ca=1
        [[ "${c}" =~ [a-z] ]] && cl=1
        [[ "${c}" =~ [0-9] ]] && cd=1
        if (( ca + cl + cd >= 3 )) && (( ${#c} >= 24 )) && _entropy_is_dense "${c}"; then
            return 1
        fi
    done
    (( ncomp >= 2 ))
}

scan_text() {
    local label="$1" content="$2"
    local pattern _ln _pf _pat_eff _hex_cred_re
    # Sensitive-data patterns, loaded from EVERY *.txt in the pattern dir. The
    # public source names no wordlist categories. Under --ci, NEVER emit the
    # matched literal (would leak a sensitive value into public CI logs); emit a
    # generic PII finding with the line number instead.
    for _pf in "${PATTERN_DIR}"/*.txt; do
        [[ -f "${_pf}" ]] || continue
        while IFS= read -r pattern; do
            [[ "${pattern}" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${pattern// /}" ]] && continue
            # APOSTROPHE-SAFE LEADING WORD BOUNDARY.
            # ERE `\b` is a transition between a word char and a NON-word char, and
            # an apostrophe is a non-word char. A verb contracted with an apostrophe
            # therefore exposes its trailing fragment as a standalone word token, and
            # every short `\b`-anchored pattern in the pattern dir matches that
            # fragment case-insensitively. This is a pure gate defect: the blocked
            # text contains no instance of the thing the pattern names. It rejected
            # a routine prose document twice, and it fires on ANY
            # apostrophe-contracted verb in ANY prose.
            #
            # Fixed at the GATE, not by rewording content (standing
            # decision) and not by editing one pattern: all 28 active patterns are
            # `\b`-anchored, so this is a class defect, not an instance of one.
            #
            # The transform conjoins `(^|[^[:alnum:]'])` onto a pattern that ALREADY
            # begins with `\b`+alnum. That can only ever REMOVE matches, and it can
            # remove exactly one kind: `\b` is satisfied when the preceding character
            # is a NON-word char or start-of-line; `[^[:alnum:]']` accepts every
            # non-word char EXCEPT the apostrophe (and `_`, which can never satisfy
            # `\b` before a word char anyway). The set difference is therefore
            # precisely {preceded by an apostrophe} and nothing else.
            #
            # ONLY the LEADING boundary is narrowed. A trailing apostrophe boundary
            # (NAME's) is a POSSESSIVE — the token really is the word, and that match
            # must be kept. A leading one is a SUFFIX FRAGMENT and never is.
            #
            # Patterns not of the form `\b`+alnum are passed through UNCHANGED: on
            # those, prefixing would demand a preceding non-word char that `\b` had
            # not already guaranteed, and that WOULD lose real detection.
            #
            # ASCII apostrophe only. U+2019 is deliberately NOT in the class: in a C
            # locale its bytes would be matched individually inside the bracket
            # expression and could exclude unrelated multibyte characters, losing
            # real detection. See the open finding filed with this change.
            _pat_eff="${pattern}"
            [[ "${pattern}" == '\b'[A-Za-z0-9]* ]] && _pat_eff="(^|[^[:alnum:]'])${pattern}"
            if _imatch "${content}" "${_pat_eff}"; then
                if [[ ${CI_MODE} -eq 1 ]]; then
                    _ln=$(grep -inE -e "${_pat_eff}" <<<"${content}" | head -n1 | cut -d: -f1)
                    _finding "PII pattern match in ${label}:${_ln:-?}"
                else
                    _finding "sensitive-pattern match '${pattern}' in ${label}"
                fi
            fi
        done < "${_pf}"
    done
    _imatch "${content}" '^sensitivity:[[:space:]]*(restricted|secret)[[:space:]]*$' && _finding "restricted/secret frontmatter in ${label}"
    _match "${content}" '(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|ghs_[A-Za-z0-9]{36}|glpat-[A-Za-z0-9_-]{20,})' && _finding "known credential pattern in ${label}"
    # 4f) CONTEXT-ANCHORED single-class HEX credential.
    #
    # The gap: a 40- or 64-char LOWERCASE-hex token scans clean. It carries only
    # two character classes, so rule 4c (3 classes AND len>=24) cannot see it, and
    # many real session keys and API tokens are exactly that shape.
    #
    # A STANDALONE long-hex rule was measured over a real corpus and REJECTED:
    # every long-hex run it matched was a git object id, a null/deadbeef test
    # fixture, or a documented sha256 integrity fingerprint — including this
    # scanner's own, which is recorded IN PROSE in the project's documentation.
    # It produced no true positives at all. A standalone rule would therefore make
    # it impossible to write down the identity of the gate itself, which is the
    # defect immediately above this one, in exchange for no detection. The base
    # rate does not support a content-only long-hex signal.
    #
    # What DOES belong in scope is hex with CREDENTIAL CONTEXT, which a git sha
    # never has. Rule 4b already covers the keyword-ASSIGNMENT forms
    # (api_key=<hex>, auth_token: <hex>, secret_key = "<hex>") — verified against
    # the live gate, because lower+digit is two classes and clears 4b's >=2-class
    # bar. This rule closes the three measured shapes 4b misses: an HTTP bearer
    # credential (value separated by SPACE, so 4b's [^space]{20,} cannot reach
    # it), a hyphenated header key (4b matches api_?key, never api-key), and
    # session/access/refresh identifiers (absent from 4b's keyword list).
    #
    # Measured FP rate of THIS rule over the same corpus: zero.
    # Anchored on context, so it is structurally incapable of firing
    # on a bare object id, digest or fingerprint.
    _hex_cred_re='(bearer[[:space:]]+|(x-)?api[_-]?key[[:space:]]*[:=][[:space:]]*["'"'"']?|(access|refresh|session)[_-]?(token|key|id)[[:space:]]*[:=][[:space:]]*["'"'"']?)[0-9a-f]{32,}'
    _imatch "${content}" "${_hex_cred_re}" && _finding "hex credential in ${label}"
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
        _imatch "${_line}" "${_secret_assign_re}" || continue
        # Isolate the value side (everything after the first = or :).
        _value="${_line#*[=:]}"
        # 1) env-read / interpolation reference -> not a literal -> exempt.
        _match "${_value}" "${_env_read_re}" && continue
        # 2) quoted string literal -> hardcoded secret -> FLAG.
        if _match "${_value}" "${_quoted_literal_re}"; then
            _finding "secret assignment pattern in ${label}"
            break
        fi
        # 3) function call -> computed value (e.g. hash_password(...)) -> exempt.
        _match "${_value}" "${_func_call_re}" && continue
        # 4) High-entropy bare-token FLAG runs BEFORE the bare-ref exemption: a
        #    value that is long AND mixed-class (>=2 classes, >=20 chars) is treated
        #    as an embedded literal secret and flagged even though it would also
        #    match the bare-identifier shape. Running the entropy test first closes
        #    the gap where an unquoted low-entropy-but-still-qualifying secret value
        #    (e.g. secret_key: <20+ char mixed token>) was silently exempted.
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
        # 5) bare identifier / attribute access that did NOT meet the entropy bar
        #    -> genuine code reference (obj.attr / lone low-entropy ident) -> exempt.
        _match "${_value}" "${_bare_ref_re}" && continue
    done < <(printf '%s\n' "${content}")
    if grep -qP '.' <<<'test' 2>/dev/null; then
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
            # 4e) PATH-SHAPE skip. The line above only catches a candidate that STILL
            #     begins with '/'; extraction chops at '.', and relative route names
            #     never had one. See _looks_like_path.
            _looks_like_path "${candidate}" && continue
            _match "${candidate}" "${_dir_dur_re}" && continue # systemd Directive=<short numeric/duration> is benign config
            local ha=0 hl=0 hd=0
            [[ "${candidate}" =~ [A-Z] ]] && ha=1
            [[ "${candidate}" =~ [a-z] ]] && hl=1
            [[ "${candidate}" =~ [0-9] ]] && hd=1
            [[ $((ha+hl+hd)) -ge 3 && ${#candidate} -ge 24 ]] || continue
            # 4d) DENSITY gate. 3 classes spread across single-class segments is a
            #     structured identifier (date-prefixed filename slug, kebab/snake
            #     name), not secret material — drop it and keep scanning the rest
            #     of the file rather than breaking out on a non-finding.
            _entropy_is_dense "${candidate}" || continue
            _finding "high-entropy string (len=${#candidate}) in ${label}: ${candidate:0:8}..."
            break
        done < <(grep -oP '[A-Za-z0-9+/=!@#^_-]{20,}' <<<"${content}" 2>/dev/null || true)
    fi
}

# Parse ONE `diff-tree --raw` record and scan its post-image blob.
#   $1 = commit oid (for messages and the cat-file rev)
#   $2 = raw record line
# Extracted from run_prereceive so --selftest can drive malformed records
# directly (git will not emit them on demand). Mutates FINDINGS via scan_*, so
# run_prereceive must call it IN-PROCESS; the selftest calls it in a subshell
# where it only asserts the fail-closed rc.
scan_diff_record() {
    local commit="$1" rawline="$2"
    local dstmode filepath meta rest nparent i
    # Path = everything after the FIRST tab. Unparseable record: no tab at all, a
    # still-C-quoted path (control chars / embedded quotes survive
    # quotePath=false), or a residual tab (unexpected multi-path record). Never
    # skip — fail closed.
    filepath="${rawline#*$'\t'}"
    if [[ "${filepath}" == "${rawline}" || "${filepath}" == '"'* || "${filepath}" == *$'\t'* ]]; then
        _err_exit "unparseable diff-tree record in ${commit:0:8} — failing closed"
    fi
    # Count leading ":" = number of parents (1 for a non-merge or a --root
    # listing, N for an N-parent merge). The metadata then holds N+1 modes, N+1
    # shas and 1 status = 2N+3 whitespace fields. Verify that invariant BEFORE
    # indexing: the case-statement "*) _err_exit" backstop below does NOT fail
    # closed on a misparse, because a misparse landing on a legal-looking 000000
    # hits the deletion arm and returns — a SILENT SKIP. Not hypothetical: on a
    # modify/delete resurrect merge (::100644 000000 100644 … MA) the old
    # single-":" parser read field 2 = 000000 and skipped real merge content.
    meta="${rawline%%$'\t'*}"; rest="${meta}"; nparent=0
    while [[ "${rest}" == :* ]]; do rest="${rest#:}"; nparent=$((nparent + 1)); done
    local -a _f=(); read -r -a _f <<< "${rest}"
    if (( nparent < 1 )) || (( ${#_f[@]} != 2 * nparent + 3 )); then
        _err_exit "unparseable diff-tree record in ${commit:0:8} — failing closed"
    fi
    # dstmode = the (nparent+1)-th mode field, i.e. skip nparent src modes.
    dstmode="${rest}"
    for ((i = 0; i < nparent; i++)); do dstmode="${dstmode#* }"; done
    dstmode="${dstmode%% *}"
    [[ "${dstmode}" =~ ^[0-7]{6}$ ]] \
        || _err_exit "unparseable dst mode in ${commit:0:8} — failing closed"
    scan_filename "${filepath}"
    case "${dstmode}" in
        000000) return 0 ;;                 # deletion: no post-image to scan
        160000)                             # gitlink (submodule / registered
            # worktree). The target is a commit object, not this repo's content,
            # and need not exist here at all. Skipped by mode on purpose — NOT via
            # the unreadable-path fallback, which made the scan depend on whether
            # the object happened to be present.
            _log "skip: gitlink ${filepath}"
            return 0 ;;
        100644 | 100755 | 120000) ;;        # blob / exec blob / symlink -> scan
        *) _err_exit "unexpected mode ${dstmode} for ${filepath} in ${commit:0:8} — failing closed" ;;
    esac
    local content=""
    # Plumbing `cat-file blob`, NOT porcelain `git show`: `show` stats the
    # worktree to disambiguate rev:path and FAILS once rev+path exceeds ~255 bytes
    # (reachable from ci/pre-push, which runs this same --prereceive path inside a
    # working tree), and it returns rc=0 while printing a directory listing when
    # the path is a TREE. Both are wrong for a gate. cat-file returns raw blob
    # bytes or a non-zero rc, period.
    content=$(git cat-file blob "${commit}:${filepath}" 2>/dev/null) \
        || _err_exit "cannot read blob ${filepath} in ${commit:0:8} — failing closed"
    scan_text "${filepath}@${commit:0:8}" "${content}"
    return 0
}

run_selftest() {
    # Recursion guard. Case (r4) invokes this script AS A CHILD with --selftest
    # for one purpose: to prove the identity pin does NOT gate selftest mode. The
    # pin is asserted at top level, BEFORE mode dispatch, so a child that reaches
    # this line has proved the exemption. It must not re-run the whole suite
    # (that would recurse without bound). This variable can influence NOTHING but
    # selftest mode, which gates nothing.
    if [[ -n "${SCANNER_SELFTEST_CHILD:-}" ]]; then
        echo "[scan-gate] selftest child: reached — identity pin not enforced in selftest mode"
        return 0
    fi
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

    # Identity-pin skew (see the header). While validating a CANDIDATE copy on a
    # host that already pins the INSTALLED scanner, every non-ci subprocess below
    # must fail closed on identity — that is the feature working. Case (b) is the
    # only subprocess case that deliberately runs WITHOUT --ci, so detect the skew
    # up front and SKIP that case loudly rather than let it pass vacuously.
    local _pin_skew=0 _inst_pin="" _self_sha
    _self_sha="$(sha256sum "${self}" 2>/dev/null | awk '{print $1}')"
    if [[ -r "${INSTALL_CONF_DEFAULT}" ]]; then
        _inst_pin="$( (INSTALL_SCANNER_SHA256=""; . "${INSTALL_CONF_DEFAULT}"; printf '%s' "${INSTALL_SCANNER_SHA256:-}") 2>/dev/null )"
    fi
    [[ -n "${_inst_pin}" && "${_inst_pin}" != "${_self_sha}" ]] && _pin_skew=1

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

    # ---------- Standalone-entropy DENSITY narrowing (4d) ----------
    # FP fixtures — a dated kebab-slug filename convention
    # (YYYY-MM-DD-<kebab-slug>) reaches 3 classes and >=24 chars by concatenating
    # single-class segments, and was blocking legitimate documents that cite
    # another document by name. All MUST be clean. Built at runtime so no literal
    # itself becomes a scannable slug in this source.
    local _sl1 _sl2 _sl3
    _sl1="2026-07-29-scanner-merge-""blindspot-P1"
    _sl2="2026-07-30-""SECURITY-merge-scan-fix"
    _sl3="2026-07-27-""scan-gate-FP-standing-decision"
    _st "See ${_sl1}.md for detail." clean 'FP document slug with P1 tag'
    _st "See ${_sl2}.md for detail." clean 'FP document slug with all-caps word'
    _st "See ${_sl3}.md for detail." clean 'FP document slug with FP tag'
    # Control fixtures — separator-bearing HIGH-DENSITY tokens MUST still flag, or
    # the narrowing has cut into real base64url/token detection. _de2 is the true
    # discriminator: every run is 9 chars (below ENTROPY_DENSE_RUN_MIN), so only
    # the transition-density arm can catch it.
    local _de1 _de2
    _de1="$(printf 'aB3%.0s' $(seq 1 12))"                     # 36ch, one dense run
    _de2="$(printf 'aB3%.0s' $(seq 1 3))-$(printf 'xY7%.0s' $(seq 1 3))-$(printf 'qW4%.0s' $(seq 1 3))"
    _st "token is ${_de1} here" flag 'control contiguous mixed token still flags'
    _st "token is ${_de2} here" flag 'control hyphen-separated dense token still flags (density arm)'

    # ---------- Standalone-entropy PATH-SHAPE narrowing (4e) ----------
    # FP fixtures — path- and route-shaped candidates. Both are ASSEMBLED FROM
    # FRAGMENTS: every literal run below is under the 20-char extraction floor, so
    # no fixture in this source is itself a scannable candidate.
    local _pa1 _pa2 _pa3 _pa4
    # (1) The leading '/' is NOT in the candidate the rule sees. Extraction stops
    #     at the dot, so this path arrives as a tail starting after the dot
    #     component, and the absolute-path skip one line above 4e cannot match it.
    #     This fixture fails against any build whose only path defence is that
    #     leading-'/' test.
    _pa1="/home/user/.""cache/jobs/""b1ad829f/tmp/""NOTES.md"
    # (2) RELATIVE route/index name — never had a leading '/' at all.
    _pa2="handoff-v2/""production/pages/""ImportWizard"
    _st "job log at ${_pa1} today"   clean 'FP dot-chopped absolute job path'
    _st "route ${_pa2} is the index" clean 'FP relative route/index name'
    # Control fixtures — NEAREST TRUE POSITIVES. Both MUST still flag.
    # (3) A 24-char standard-base64 secret (18 bytes of entropy) whose '/' chars
    #     happen to fall at path-like offsets. It carries TWO slashes, so a naive
    #     slash-count heuristic clears it; 4e keeps it because P6im0yQrUEUBtY is
    #     not a name-shaped sub-word (an uppercase letter must open a word, and
    #     'UE' does not).
    _pa3="ijufvlp/""P6im0yQrUEUBtY""/C"
    # (4) EVERY sub-word here IS name-shaped (it parses as camelCase), so the
    #     lexical axis alone would clear it. Only the per-component entropy axis
    #     keeps it. This fixture is what makes 4e's second axis non-vacuous.
    _pa4="x/$(printf 'aB3%.0s' $(seq 1 8))"
    _st "bare token ${_pa3} in prose" flag 'control slashed base64 secret still flags'
    _st "bare token ${_pa4} in prose" flag 'control dense path component still flags (entropy axis)'

    # ---------- CONTEXT-ANCHORED HEX credential (4f) ----------
    # FP fixtures — BARE single-class hex MUST stay clean. These are the shapes
    # measured across the 825-blob corpus (git object ids, null/deadbeef fixtures,
    # documented sha256 fingerprints incl. this gate's own). A standalone long-hex
    # rule would flag every one of them; 4f must not. Built at runtime so no
    # fixture literal is itself a scannable token in this source.
    local _hx40 _hx64
    _hx40="$(printf 'a1b2c3d4e5%.0s' $(seq 1 4))"
    _hx64="$(printf 'a1b2c3d4e5%.0s' $(seq 1 6))1234"
    _st "commit ${_hx40} landed on main"        clean 'FP bare 40-char lowercase hex (git object id)'
    _st "scanner sha256 ${_hx64} is current"    clean 'FP bare 64-char lowercase hex (integrity fingerprint)'
    _st "artifact_sha256: ${_hx64}"             clean 'FP documented sha256 manifest value'
    # Control fixtures — the three shapes rule 4b provably MISSES. All MUST flag.
    # Keywords are split off their separator so no contiguous credential-shaped
    # literal exists in THIS source.
    local _hc1 _hc2 _hc3
    _hc1="Authorization: Bear""er ${_hx40}"
    _hc2="X-API""-Key: ${_hx40}"
    _hc3="session""_id=${_hx64}"
    _st "${_hc1}" flag 'control bearer + lowercase hex flags (space-separated value: 4b cannot reach it)'
    _st "${_hc2}" flag 'control x-api-key + lowercase hex flags (hyphenated key: 4b matches api_?key only)'
    _st "${_hc3}" flag 'control session_id + lowercase hex flags (keyword absent from 4b list)'
    # Control — the forms 4b ALREADY covers must keep flagging (no regression).
    local _hc4; _hc4="api""_key=${_hx40}"
    _st "${_hc4}" flag 'control api_key + lowercase hex still flags via 4b'

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
    # REGRESSION (rule-4b bare-ref short-circuit): an UNQUOTED value that is long
    # AND mixed-class matched the bare-identifier shape and was silently exempted
    # before the entropy test ran. It must now FLAG. Values are built at runtime via
    # printf (and the keyword split off its ':'/'=') so neither the secret keyword
    # nor a high-entropy literal appears contiguously in THIS source. _bt1 is the
    # true discriminator: 21-char/2-class sits below the entropy backstop, so only
    # the reordered rule-4b catches it (old code exempted it via bare-ref).
    local _bt1 _bt2
    _bt1="secret""_key: $(printf 'hunter2%.0s' $(seq 1 3))"   # 21-char, 2-class -> FLAG
    _bt2="api""_key=$(printf 'Xy7%.0s' $(seq 1 8))"           # 24-char, 3-class -> FLAG
    _st "${_bt1}" flag 'regression unquoted low-entropy mixed secret_key value now flags'
    _st "${_bt2}" flag 'regression unquoted mixed api_key value now flags'
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
    # Every --ci subprocess below must be immune to a REAL installed identity pin,
    # because the file under test is normally a candidate copy. Case (r) overrides
    # this per-invocation to test the pin itself. Honored only under --ci by
    # design, so case (b)'s no-ci contract is untouched.
    : > "${tmproot}/empty.conf"
    export SCANNER_INSTALL_CONF="${tmproot}/empty.conf"
    # Sentinel patterns — match nothing real; safe to print in any context.
    printf '%s\n' 'ACMEHOLDINGS_SENTINEL' > "${ptmp}/patterns-a.txt"
    printf '%s\n' 'ZZSENTINELNAME' > "${ptmp}/patterns-b.txt"
    local pii_file="${tmproot}/leak.txt"
    printf 'line one\nmy institution is ACMEHOLDINGS_SENTINEL here\nline three\n' > "${pii_file}"

    # (a) --ci must NOT emit the matched literal; must emit generic PII finding; rc=1
    local out rc
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${pii_file}" 2>&1); rc=$?
    [[ ${rc} -eq 1 ]] || { echo "SELFTEST FAIL (a): expected rc=1 got ${rc}" >&2; fails=$((fails+1)); }
    if _match "${out}" 'ACMEHOLDINGS_SENTINEL'; then
        echo "SELFTEST FAIL (a): --ci leaked the matched pattern literal" >&2; fails=$((fails+1)); fi
    if ! _match "${out}" 'PII pattern match'; then
        echo "SELFTEST FAIL (a): --ci did not emit generic PII finding" >&2; fails=$((fails+1)); fi

    # (b) PATTERN_DIR override MUST be ignored WITHOUT --ci (forces system dir).
    if [[ ${_pin_skew} -eq 1 ]]; then
        echo "SELFTEST SKIP (b): installed identity pin (${_inst_pin:0:12}) != this file (${_self_sha:0:12}); the non-ci path fails closed on identity by design, so this case cannot be evaluated on a candidate copy" >&2
    else
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --file "${pii_file}" 2>&1); rc=$?
    [[ ${rc} -ne 2 ]] || { echo "SELFTEST FAIL (b): non-ci scan failed closed unexpectedly (rc=2): ${out}" >&2; fails=$((fails+1)); }
    if _match "${out}" 'ACMEHOLDINGS_SENTINEL'; then
        echo "SELFTEST FAIL (b): PATTERN_DIR override honored without --ci" >&2; fails=$((fails+1)); fi
    if [[ ${rc} -eq 1 ]] && _imatch "${out}" 'name match|PII pattern'; then
        echo "SELFTEST FAIL (b): sentinel matched via override without --ci" >&2; fails=$((fails+1)); fi
    fi

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
        if _match "${nb_out}" 'ACMEHOLDINGS_SENTINEL'; then
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

    # (f) Tree-entry classification: a gitlink is skipped BY MODE (not via an
    #     unreadable-path fallback), a deletion is skipped, and a non-ASCII path is
    #     still scanned. Pre-fix, `--name-only` handed back a C-quoted path, `git
    #     show` failed, and the file was silently skipped — a scan BYPASS.
    local grepo="${tmproot}/glrepo" gbase gnew g_out g_rc
    mkdir -p "${grepo}"
    (
        cd "${grepo}" || exit 9
        git init -q
        git config user.email t@example.invalid; git config user.name tester
        printf 'base\n' > keep.txt; printf 'doomed\n' > doomed.txt
        git add -A; git commit -q -m base
    ) || { echo "SELFTEST FAIL (f): repo setup" >&2; fails=$((fails+1)); }
    gbase=$(cd "${grepo}" && git rev-parse HEAD)
    (
        cd "${grepo}" || exit 9
        git rm -q doomed.txt                                  # deletion  -> mode 000000
        printf 'leak ACMEHOLDINGS_SENTINEL here\n' > $'caf\xc3\xa9.txt'   # non-ASCII path
        printf 'ordinary\n' > plain.txt
        git add -A
        # gitlink with a PRESENT target object, and one with an ABSENT target.
        git update-index --add --cacheinfo "160000,${gbase},wt/present"
        git update-index --add --cacheinfo "160000,deadbeefdeadbeefdeadbeefdeadbeefdeadbeef,wt/absent"
        git commit -q -m feature
    ) || { echo "SELFTEST FAIL (f): fixture commit" >&2; fails=$((fails+1)); }
    gnew=$(cd "${grepo}" && git rev-parse HEAD)
    g_out=$(cd "${grepo}" && printf '%s %s %s\n' "${gbase}" "${gnew}" "refs/heads/feature" \
             | env PATTERN_DIR="${ptmp}" "${self}" --ci --prereceive 2>&1); g_rc=$?
    [[ ${g_rc} -ne 2 ]] || { echo "SELFTEST FAIL (f): classification failed closed on a valid tree (rc=2)" >&2; fails=$((fails+1)); }
    [[ ${g_rc} -eq 1 ]] || { echo "SELFTEST FAIL (f): non-ASCII path not scanned — bypass (rc=${g_rc})" >&2; fails=$((fails+1)); }
    _match "${g_out}" 'skip: gitlink wt/absent' \
        || { echo "SELFTEST FAIL (f): absent-target gitlink not skipped by mode" >&2; fails=$((fails+1)); }
    _match "${g_out}" 'skip: gitlink wt/present' \
        || { echo "SELFTEST FAIL (f): present-target gitlink scanned as commit text" >&2; fails=$((fails+1)); }
    if _match "${g_out}" 'WARN: cannot read'; then
        echo "SELFTEST FAIL (f): unreadable-path fallback still reached" >&2; fails=$((fails+1)); fi


    # ---------- (g)-(n) MERGE-COMMIT enumeration (P1) --------------------------
    # `git diff-tree -r <merge>` emits NOTHING without -c, so BEFORE this fix no
    # merge commit had ever been content-scanned — and any workflow that merges a
    # branch into main routinely produces exactly the case where a hand-resolved
    # conflict introduces content present in NO parent.
    # Fixtures are built with commit-tree + GIT_INDEX_FILE + update-index
    # --cacheinfo, NOT worktree merges: a gitlink merge aborts in a worktree with
    # "'sub' does not have a commit checked out" (same reason as case (f)).
    local mrepo="${tmproot}/mrepo" m_out m_rc _TAB=$'\t'
    mkdir -p "${mrepo}"
    (
        cd "${mrepo}" || exit 9
        git init -q .
        git config user.email t@example.invalid; git config user.name tester
        B0=$(printf 'base\n'  | git hash-object -w --stdin)
        BX=$(printf 'sideA\n' | git hash-object -w --stdin)
        BY=$(printf 'sideB\n' | git hash-object -w --stdin)
        BL=$(printf 'conflict resolution mentions ACMEHOLDINGS_SENTINEL\n' | git hash-object -w --stdin)
        export GIT_INDEX_FILE="${mrepo}/.stidx"
        _ix() { rm -f "${GIT_INDEX_FILE}"; }
        _ix; git update-index --add --cacheinfo "100644,${B0},f.txt" --cacheinfo "100644,${B0},g.txt"
        C0=$(git commit-tree "$(git write-tree)" -m base)
        _ix; git update-index --add --cacheinfo "100644,${BX},f.txt" --cacheinfo "100644,${B0},g.txt"
        P1=$(git commit-tree "$(git write-tree)" -p "${C0}" -m p1)
        _ix; git update-index --add --cacheinfo "100644,${BY},f.txt" --cacheinfo "100644,${B0},g.txt"
        P2=$(git commit-tree "$(git write-tree)" -p "${C0}" -m p2)
        _ix; git update-index --add --cacheinfo "100644,${B0},f.txt" --cacheinfo "100644,${BY},g.txt"
        P3=$(git commit-tree "$(git write-tree)" -p "${C0}" -m p3)
        _ix; git update-index --add --cacheinfo "100644,${B0},g.txt"
        PDEL=$(git commit-tree "$(git write-tree)" -p "${C0}" -m p-del)
        # (g) hand-resolved merge: f differs from BOTH parents and CARRIES A LEAK.
        _ix; git update-index --add --cacheinfo "100644,${BL},f.txt" --cacheinfo "100644,${B0},g.txt"
        MRES=$(git commit-tree "$(git write-tree)" -p "${P1}" -p "${P2}" -m merge-resolved)
        # (h) delete-resolved: both parents had DIFFERENT f, merge DELETES it ->
        #     "::100644 100644 000000 … DD". The single-":" parser read field 2 =
        #     100644, then cat-file blob on a deleted path failed -> rc=2 on EVERY
        #     push, unclearable by any forward commit.
        _ix; git update-index --add --cacheinfo "100644,${B0},g.txt"
        MDD=$(git commit-tree "$(git write-tree)" -p "${P1}" -p "${P2}" -m merge-delete-resolved)
        # (i) modify/delete RESURRECT: p1 modified f, p2 deleted f, merge keeps f
        #     with NEW content -> "::100644 000000 100644 … MA". The single-":"
        #     parser read field 2 = 000000, hit the deletion arm and SKIPPED it —
        #     a silent bypass, the inverse failure of (h).
        _ix; git update-index --add --cacheinfo "100644,${BL},f.txt" --cacheinfo "100644,${B0},g.txt"
        MMA=$(git commit-tree "$(git write-tree)" -p "${P1}" -p "${PDEL}" -m merge-resurrect)
        # (j) OCTOPUS: 3 parents -> ":::" prefix, 4 modes + 4 shas + 1 status.
        _ix; git update-index --add --cacheinfo "100644,${BL},f.txt" --cacheinfo "100644,${BX},g.txt"
        MOCT=$(git commit-tree "$(git write-tree)" -p "${P1}" -p "${P2}" -p "${P3}" -m octopus)
        # (k) gitlink INTRODUCED by a merge -> dstmode 160000, must skip BY MODE.
        _ix; git update-index --add --cacheinfo "100644,${B0},g.txt" --cacheinfo "160000,${C0},sub"
        MGL=$(git commit-tree "$(git write-tree)" -p "${P1}" -p "${P2}" -m merge-gitlink)
        # (l) PARENTLESS commit: -c ALONE emits nothing for it, so --root must stay.
        _ix; git update-index --add --cacheinfo "100644,${BL},orphan.txt"
        MORP=$(git commit-tree "$(git write-tree)" -m orphan-root)
        printf '%s %s %s %s %s %s %s\n' "${P1}" "${MRES}" "${MDD}" "${MMA}" "${MOCT}" "${MGL}" "${MORP}" \
            > "${mrepo}/shas"
    ) || { echo "SELFTEST FAIL (g): merge fixture build" >&2; fails=$((fails+1)); }
    local M_P1 M_RES M_DD M_MA M_OCT M_GL M_ORP
    read -r M_P1 M_RES M_DD M_MA M_OCT M_GL M_ORP < "${mrepo}/shas" 2>/dev/null \
        || { echo "SELFTEST FAIL (g): fixture shas unreadable" >&2; fails=$((fails+1)); }
    _mscan() {  # $1=oldrev $2=newrev -> sets m_out / m_rc
        m_out=$(cd "${mrepo}" && printf '%s %s %s\n' "$1" "$2" "refs/heads/t" \
                 | env PATTERN_DIR="${ptmp}" "${self}" --ci --prereceive 2>&1); m_rc=$?
    }
    # (g) merge content present in NO parent MUST be scanned. Pre-fix: rc=0 (bypass).
    _mscan "${M_P1}" "${M_RES}"
    [[ ${m_rc} -eq 1 ]] || { echo "SELFTEST FAIL (g): hand-resolved merge content not scanned (rc=${m_rc}) — merge bypass" >&2; fails=$((fails+1)); }
    # (h) delete-resolved merge must NOT fail closed. Pre-fix: rc=2 (wedged repo).
    _mscan "${M_P1}" "${M_DD}"
    [[ ${m_rc} -ne 2 ]] || { echo "SELFTEST FAIL (h): delete-resolved merge failed closed (rc=2)" >&2; fails=$((fails+1)); }
    # (i) resurrect merge MUST flag. Pre-fix: silent skip via a 000000 misparse.
    _mscan "${M_P1}" "${M_MA}"
    [[ ${m_rc} -eq 1 ]] || { echo "SELFTEST FAIL (i): modify/delete resurrect not scanned (rc=${m_rc}) — silent skip" >&2; fails=$((fails+1)); }
    # (j) octopus (3-parent, 2N+3 = 9 fields) parses and flags.
    _mscan "${M_P1}" "${M_OCT}"
    [[ ${m_rc} -eq 1 ]] || { echo "SELFTEST FAIL (j): octopus merge not scanned (rc=${m_rc})" >&2; fails=$((fails+1)); }
    # (k) gitlink added BY a merge is skipped by mode, not by a read failure.
    _mscan "${M_P1}" "${M_GL}"
    [[ ${m_rc} -ne 2 ]] || { echo "SELFTEST FAIL (k): merge-introduced gitlink failed closed (rc=2)" >&2; fails=$((fails+1)); }
    _match "${m_out}" 'skip: gitlink sub' \
        || { echo "SELFTEST FAIL (k): merge-introduced gitlink not skipped by mode" >&2; fails=$((fails+1)); }
    # (l) parentless commit still enumerated under "-c --root" (guards --root).
    _mscan "0000000000000000000000000000000000000000" "${M_ORP}"
    [[ ${m_rc} -eq 1 ]] || { echo "SELFTEST FAIL (l): parentless commit not enumerated under -c --root (rc=${m_rc})" >&2; fails=$((fails+1)); }

    # (m) MALFORMED records MUST fail closed (rc=2). git will not emit these on
    #     demand, so scan_diff_record is driven directly in a SUBSHELL (_err_exit
    #     exits 2). This is the regression test for the 2N+3 field-count invariant:
    #     the "*) _err_exit" backstop alone does NOT fail closed, because a misparse
    #     landing on a legal-looking 000000 hits the deletion arm and returns 0 — a
    #     silent skip (exactly the (i) failure mode).
    local _bad _brc
    while IFS= read -r _bad; do
        [[ -z "${_bad}" ]] && continue
        ( scan_diff_record "deadbeefdeadbeef" "${_bad}" ) >/dev/null 2>&1; _brc=$?
        [[ ${_brc} -eq 2 ]] || { echo "SELFTEST FAIL (m): malformed record did not fail closed (rc=${_brc}): ${_bad}" >&2; fails=$((fails+1)); }
    done <<EOF
:100644 100644 aaaa bbbb M${_TAB}too-few-fields.txt
::100644 100644 000000 aaaa bbbb DD${_TAB}merge-too-few.txt
:::100644 100644 100644 100644 a b c d MMM${_TAB}octopus-too-few.txt
:100644 100644 aaaa bbbb cccc dddd M${_TAB}too-many-fields.txt
100644 100644 aaaa bbbb cccc M${_TAB}no-leading-colon.txt
:10064x 100644 aaaa bbbb cccc M${_TAB}non-octal-mode.txt
:100644 100644 aaaa bbbb cccc M no-tab-separator.txt
:100644 100644 aaaa bbbb cccc M${_TAB}"c-quoted-caf\303\251.txt"
:100644 100644 aaaa bbbb cccc M${_TAB}resid${_TAB}ual-tab.txt
:100644 100777 aaaa bbbb cccc M${_TAB}unexpected-mode.txt
EOF
    # (n) WELL-FORMED records must NOT fail closed and must classify by dst mode.
    #     Deletions carry no post-image, so these must return cleanly WITHOUT a
    #     cat-file read (the (h) failure was exactly a read of a deleted path).
    ( scan_diff_record "deadbeefdeadbeef" ":100644 000000 aaaa 0000000 D${_TAB}gone.txt" ) >/dev/null 2>&1
    [[ $? -ne 2 ]] || { echo "SELFTEST FAIL (n): well-formed deletion failed closed" >&2; fails=$((fails+1)); }
    ( scan_diff_record "deadbeefdeadbeef" "::100644 100644 000000 a b c DD${_TAB}gone2.txt" ) >/dev/null 2>&1
    [[ $? -ne 2 ]] || { echo "SELFTEST FAIL (n): well-formed merge deletion failed closed" >&2; fails=$((fails+1)); }
    ( scan_diff_record "deadbeefdeadbeef" "::100644 100644 160000 a b c MM${_TAB}sub" ) >/dev/null 2>&1
    [[ $? -ne 2 ]] || { echo "SELFTEST FAIL (n): well-formed merge gitlink failed closed" >&2; fails=$((fails+1)); }

    # ---------- (o) SIGPIPE FAIL-OPEN regression guard (P0) --------------------
    # The gate previously matched content with `printf '%s' "$c" | grep -q "$p"`.
    # `grep -q` exits at the FIRST match, `printf` dies of SIGPIPE (141), pipefail
    # promotes 141 to the pipeline status, and the `if` reads FALSE *because* the
    # pattern matched. Above ~128 KB the gate was deterministically blind to an
    # early match; in the ~61-70 KB band the verdict was a RACE, so the same bytes
    # could be REJECTED once and ACCEPTED on retry.
    #
    # These cases assert the gate still sees a match on LINE 1 of a body far larger
    # than the 64 KB pipe buffer. They FAIL against any build that reintroduces the
    # pipeline. Filler is built in pure bash (no /dev/zero, tr or fold dependency).
    local _pad="" _big="" _mid="" _i
    printf -v _pad '%*s' 200 ''
    _pad="${_pad// /x}"
    for ((_i = 0; _i < 1000; _i++)); do _big+="${_pad}"$'\n'; done   # ~201 KB, multi-line
    for ((_i = 0; _i < 340; _i++)); do _mid+="${_pad}"$'\n'; done   # ~68 KB, the race band

    # (o1) PII pattern-file match (the loop over PATTERN_DIR) on line 1 of ~201 KB.
    local _of="${tmproot}/large-early-pii.txt"
    printf 'ACMEHOLDINGS_SENTINEL\n%s' "${_big}" > "${_of}"
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${_of}" 2>&1); rc=$?
    [[ ${rc} -eq 1 ]] || { echo "SELFTEST FAIL (o1): early PII match in a >128KB body not reported (rc=${rc}) — SIGPIPE fail-open" >&2; fails=$((fails+1)); }

    # (o2) known-credential regex on line 1 of ~201 KB (independent of PATTERN_DIR).
    local _skL; _skL="sk-""ant-$(printf 'd%.0s' $(seq 1 30))"
    local _ocf="${tmproot}/large-early-cred.txt"
    printf 'token=%s\n%s' "${_skL}" "${_big}" > "${_ocf}"
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${_ocf}" 2>&1); rc=$?
    [[ ${rc} -eq 1 ]] || { echo "SELFTEST FAIL (o2): early credential match in a >128KB body not reported (rc=${rc}) — SIGPIPE fail-open" >&2; fails=$((fails+1)); }

    # (o3) restricted/secret frontmatter on line 1 of ~201 KB.
    local _off="${tmproot}/large-early-fm.txt"
    printf 'sensitivity: restricted\n%s' "${_big}" > "${_off}"
    out=$(env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${_off}" 2>&1); rc=$?
    [[ ${rc} -eq 1 ]] || { echo "SELFTEST FAIL (o3): early frontmatter match in a >128KB body not reported (rc=${rc}) — SIGPIPE fail-open" >&2; fails=$((fails+1)); }

    # (o4) RACE band. 5 identical runs at ~68 KB must ALL reject. On the unpatched
    #      gate this band was nondeterministic, which is the worse property: a retry
    #      after a block could push the same bytes through.
    local _orf="${tmproot}/race-band.txt" _rbi _rbfail=0
    printf 'ACMEHOLDINGS_SENTINEL\n%s' "${_mid}" > "${_orf}"
    for ((_rbi = 0; _rbi < 5; _rbi++)); do
        env PATTERN_DIR="${ptmp}" "${self}" --ci --file "${_orf}" >/dev/null 2>&1; rc=$?
        [[ ${rc} -eq 1 ]] || _rbfail=$((_rbfail + 1))
    done
    [[ ${_rbfail} -eq 0 ]] || { echo "SELFTEST FAIL (o4): ${_rbfail}/5 runs accepted an early match in the ~68KB race band — nondeterministic fail-open" >&2; fails=$((fails+1)); }

    # ---------- (p) LINT: the pipeline match form must never come back ----------
    # Structural guard, not a behavioural one: case (o) catches the defect only at
    # the sites it exercises, but the bug is a SHAPE that was present at 20 sites.
    # This fails the selftest if `printf ... | grep` reappears ANYWHERE in executable
    # source. Comment lines are exempt so the helper above can keep documenting the
    # broken form. The regex is assembled from fragments so it never matches itself.
    local _lre _lhit=0 _lline
    _lre='print''f[^|]*\| *grep'
    while IFS= read -r _lline; do
        [[ -z "${_lline}" ]] && continue
        [[ "${_lline}" =~ ^[0-9]+:[[:space:]]*# ]] && continue    # comment: exempt
        _lhit=$((_lhit + 1))
        echo "SELFTEST FAIL (p): pipeline match form reintroduced -> ${_lline}" >&2
    done < <(grep -nE -e "${_lre}" "${self}" 2>/dev/null || true)
    [[ ${_lhit} -eq 0 ]] || fails=$((fails + _lhit))

    # ---------- (q) APOSTROPHE WORD-BOUNDARY FP (leading boundary) -------------
    # A contracted verb exposes its trailing fragment as a standalone word token,
    # and `\b` accepts the apostrophe as the boundary. Driven entirely through a
    # SENTINEL pattern dir so this regression test needs no real pattern and no
    # real triggering token in this source. Case (q3) is the load-bearing control:
    # it proves only the LEADING boundary was narrowed, so a possessive and a
    # start-of-line hit both still match.
    local qp="${tmproot}/qpat"
    mkdir -p "${qp}"
    printf '%s\n' '\bZQX\b' > "${qp}/patterns-q.txt"
    local q_fp="${tmproot}/q-fp.txt" q_tp="${tmproot}/q-tp.txt" q_pos="${tmproot}/q-pos.txt" q_rc
    printf 'the agent was exec%szqx the worktree file today\n' "'" > "${q_fp}"
    printf 'my institution is ZQX and nothing else\n'              > "${q_tp}"
    printf 'ZQX at the start of a line\nand ZQX%ss holdings too\n' "'" > "${q_pos}"
    env PATTERN_DIR="${qp}" "${self}" --ci --file "${q_fp}" >/dev/null 2>&1; q_rc=$?
    [[ ${q_rc} -eq 0 ]] || { echo "SELFTEST FAIL (q1): contraction tail matched a \\b-anchored pattern (rc=${q_rc}) — apostrophe word-boundary FP" >&2; fails=$((fails+1)); }
    env PATTERN_DIR="${qp}" "${self}" --ci --file "${q_tp}" >/dev/null 2>&1; q_rc=$?
    [[ ${q_rc} -eq 1 ]] || { echo "SELFTEST FAIL (q2): ordinary \\b-anchored match LOST (rc=${q_rc}) — narrowing cut real detection" >&2; fails=$((fails+1)); }
    env PATTERN_DIR="${qp}" "${self}" --ci --file "${q_pos}" >/dev/null 2>&1; q_rc=$?
    [[ ${q_rc} -eq 1 ]] || { echo "SELFTEST FAIL (q3): start-of-line / possessive match LOST (rc=${q_rc}) — trailing boundary must NOT be narrowed" >&2; fails=$((fails+1)); }

    # ---------- (r) SCANNER IDENTITY PIN (fail closed) ------------------------
    # The 2026-08-04 wrong-gate scan: one invocation, two scanner versions, both
    # logged, never compared. A WRONG pin must be rc=2 (fail closed) in an
    # enforcement mode; a CORRECT pin and an ABSENT pin must both leave behaviour
    # byte-identical to the unpinned gate.
    local r_good="${tmproot}/pin-good.conf" r_bad="${tmproot}/pin-bad.conf" r_none="${tmproot}/pin-none.conf" r_rc
    printf 'INSTALL_SCANNER_SHA256=%s\n' "${_self_sha}" > "${r_good}"
    printf 'INSTALL_SCANNER_SHA256=%s\n' "$(printf '0%.0s' $(seq 1 64))" > "${r_bad}"
    : > "${r_none}"
    out=$(env SCANNER_INSTALL_CONF="${r_bad}" PATTERN_DIR="${ptmp}" "${self}" --ci --file "${pii_file}" 2>&1); r_rc=$?
    [[ ${r_rc} -eq 2 ]] || { echo "SELFTEST FAIL (r1): wrong identity pin did NOT fail closed (rc=${r_rc})" >&2; fails=$((fails+1)); }
    _match "${out}" 'scanner identity mismatch' \
        || { echo "SELFTEST FAIL (r1): identity mismatch not reported" >&2; fails=$((fails+1)); }
    out=$(env SCANNER_INSTALL_CONF="${r_good}" PATTERN_DIR="${ptmp}" "${self}" --ci --file "${pii_file}" 2>&1); r_rc=$?
    [[ ${r_rc} -eq 1 ]] || { echo "SELFTEST FAIL (r2): correct identity pin changed the verdict (rc=${r_rc})" >&2; fails=$((fails+1)); }
    out=$(env SCANNER_INSTALL_CONF="${r_none}" PATTERN_DIR="${ptmp}" "${self}" --ci --file "${pii_file}" 2>&1); r_rc=$?
    [[ ${r_rc} -eq 1 ]] || { echo "SELFTEST FAIL (r3): ABSENT identity pin changed behaviour (rc=${r_rc}) — the pin must be opt-in" >&2; fails=$((fails+1)); }
    # (r4) the pin must NOT gate --selftest itself, or a skew becomes unfixable:
    #      the only way to validate the replacement scanner is to run its selftest.
    out=$(env SCANNER_SELFTEST_CHILD=1 SCANNER_INSTALL_CONF="${r_bad}" "${self}" --selftest 2>&1); r_rc=$?
    [[ ${r_rc} -eq 0 ]] || { echo "SELFTEST FAIL (r4): wrong pin blocked --selftest (rc=${r_rc}) — a skew would be unrecoverable" >&2; fails=$((fails+1)); }
    _match "${out}" 'selftest child: reached' \
        || { echo "SELFTEST FAIL (r4): selftest child did not reach dispatch under a wrong pin" >&2; fails=$((fails+1)); }

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
            # A commit oid is REQUIRED here. `diff-tree` handed a TREE oid exits 0
            # with EMPTY stdout (it prints "object <t> is a tree, not a commit" to
            # stderr only), so rc alone cannot tell "nothing to scan" apart from
            # "nothing was examined". Assert the type before trusting empty output.
            git cat-file -e "${commit}^{commit}" 2>/dev/null \
                || _err_exit "not a commit object: ${commit:0:8} — failing closed"
            # Enumerate changed files WITH their post-image mode.
            #   -c      COMBINED diff for MERGE commits. Without it diff-tree emits
            #           NOTHING for a merge, so no merge content was ever scanned —
            #           and a merge is exactly where a hand-resolved conflict
            #           introduces content that exists in no parent, present in
            #           neither side. On a NON-merge, -c emits
            #           the ordinary single-":" shape unchanged, so one command and
            #           one parser cover both cases.
            #           -c (not -m) is deliberate: a combined diff lists only paths
            #           differing from ALL parents, and content identical to a parent
            #           was already scanned when that parent was pushed (induction).
            #   --root  full tree for a parentless (root/orphan) commit. STILL
            #           REQUIRED alongside -c: verified that -c ALONE emits nothing
            #           for a parentless commit, which would be a silent bypass.
            #           The composed "-c --root" on a parentless commit emits the
            #           ordinary single-":" full-tree listing at rc=0 (verified).
            #           -c/-m precedence is NOT in play — -m is never passed.
            #   --raw   :<srcmode>… <dstmode> <srcsha>… <dstsha> <status>\t<path>
            #           with ONE leading ":" per parent.
            # core.quotePath=false keeps a non-ASCII path literal.
            # Rename/copy detection is NOT enabled (plumbing ignores diff.renames
            # and we pass no -M/-C), so a record carries exactly one path field.
            # Capture explicitly and fail closed if diff-tree errors (no || true).
            local files=""
            if ! files=$(git -c core.quotePath=false diff-tree -c --root --no-commit-id -r --raw "${commit}"); then
                _err_exit "diff-tree failed for ${commit:0:8} — failing closed"
            fi
            local rawline nrec=0
            while IFS= read -r rawline; do
                [[ -z "${rawline}" ]] && continue
                nrec=$((nrec + 1))
                scan_diff_record "${commit}" "${rawline}"
            done <<< "${files}"
            # Record count is logged so an EMPTY enumeration is auditable after the
            # fact. Empty is legitimate for a merge whose tree matches a parent on
            # every path (combined-diff semantics), but it must never be
            # indistinguishable in the log from a commit that was never examined.
            _log "records: ${commit:0:8} n=${nrec}"
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

# Scan EVERY blob in the tree at a ref — the gate a diff can never provide.
#
# WHY this mode exists: a diff-based gate only sees what a push CHANGED. Content
# that entered before the gate was installed is invisible to it permanently, and
# `docker-publish.yml` fires on `push: tags: v*.*.*`, which no PR diff scan covers
# at all — so a tag can carry an unexamined tree straight into a published image.
# That is not hypothetical here: tag v1.1.1 published a full personal profile that
# every diff scan since has been structurally unable to see. A tree scan at the
# tag is the only thing that answers "what is actually IN this artifact".
run_tree() {
    local ref="${TARGET_REF}"
    git rev-parse --verify --quiet "${ref}^{tree}" >/dev/null \
        || _err_exit "not a tree-ish: ${ref} — failing closed"
    _log "scanning full tree at ref: ${ref}"
    local nblob=0 rec
    # -z gives NUL-terminated records with paths NOT C-quoted, so a non-ASCII or
    # embedded-quote path arrives literal and the quotePath hazard handled in
    # scan_diff_record cannot arise. Read the oid straight out of the record
    # rather than re-resolving "<ref>:<path>" — cat-file cannot disambiguate that
    # form once rev+path exceeds ~255 bytes.
    while IFS= read -r -d '' rec; do
        local meta path mode otype oid content
        meta="${rec%%$'\t'*}"; path="${rec#*$'\t'}"
        [[ "${path}" == "${rec}" ]] \
            && _err_exit "unparseable ls-tree record under ${ref} — failing closed"
        read -r mode otype oid <<< "${meta}"
        case "${mode}" in
            160000) _log "skip: gitlink ${path}"; continue ;;
            100644 | 100755 | 120000) ;;
            *) _err_exit "unexpected mode ${mode} for ${path} under ${ref} — failing closed" ;;
        esac
        [[ "${otype}" == "blob" ]] \
            || _err_exit "unexpected object type ${otype} for ${path} — failing closed"
        nblob=$((nblob + 1))
        scan_filename "${path}"
        content=$(git cat-file blob "${oid}" 2>/dev/null) \
            || _err_exit "cannot read blob ${oid:0:8} (${path}) — failing closed"
        scan_text "${path}" "${content}"
    done < <(git ls-tree -r -z "${ref}")
    # A zero-blob enumeration means the scan examined nothing. That must never be
    # indistinguishable from a clean result — it is the exact shape of the bug
    # this mode exists to fix.
    (( nblob == 0 )) && _err_exit "tree ${ref} enumerated ZERO blobs — failing closed"
    _log "tree scan complete — ref=${ref} blobs=${nblob} findings=${FINDINGS}"
    if [[ ${FINDINGS} -gt 0 ]]; then
        echo "" >&2
        echo "╔ SCAN GATE: TREE REJECTED at ${ref} - ${FINDINGS} finding(s). See ${LOG_FILE:-stderr}" >&2
        return 1
    fi
    echo "[scan-gate] tree ${ref}: ACCEPTED (${nblob} blobs, sha=${SCANNER_SHA:0:12})" >&2
    return 0
}

# Sweep every blob reachable from every ref — the periodic backstop.
#
# BASELINE, and why it is not a bypass: this repo's history contains findings that
# are already public and have been accepted as residual, because the remediation
# for them (a full history rewrite) was assessed as more damaging than the
# exposure. Without a baseline this sweep is red forever, and a check that is
# always red is a check nobody reads — the failure mode is worse than not running
# it. So known-accepted blobs are listed BY OID in the baseline file and reported
# as accepted rather than as findings; anything not on that list fails the run.
# The baseline is committed, so adding to it is a reviewable diff that the PR gate
# itself scans. It records what we have decided to live with, and nothing else.
run_history() {
    local baseline="${SCANNER_HISTORY_BASELINE:-.ci/history-baseline.txt}"
    local -A _accepted=()
    if [[ -r "${baseline}" ]]; then
        local bline boid
        while IFS= read -r bline || [[ -n "${bline}" ]]; do
            bline="${bline%%#*}"; bline="${bline//[[:space:]]/}"
            [[ -z "${bline}" ]] && continue
            [[ "${bline}" =~ ^[0-9a-f]{40}$ ]] \
                || _err_exit "malformed baseline entry '${bline:0:16}' in ${baseline} — failing closed"
            boid="${bline}"; _accepted["${boid}"]=1
        done < "${baseline}"
        _log "history baseline: ${#_accepted[@]} accepted blob(s) from ${baseline}"
    else
        _log "history baseline: none at ${baseline} — every finding is new"
    fi

    _log "scanning FULL HISTORY — every blob reachable from every ref"
    local nblob=0 nskip=0 oid otype path content before
    while read -r oid otype path; do
        [[ "${otype}" == "blob" ]] || continue
        if [[ -n "${_accepted[${oid}]:-}" ]]; then
            nskip=$((nskip + 1))
            _log "accepted (baseline): ${oid:0:8} ${path:-<unnamed>}"
            continue
        fi
        nblob=$((nblob + 1))
        # Label carries the oid: a blob can sit at many paths across history, and
        # a finding is only actionable if you can name the object it is in.
        local label="${path:-<unnamed>}@${oid:0:8}"
        scan_filename "${path:-unnamed}"
        content=$(git cat-file blob "${oid}" 2>/dev/null) \
            || _err_exit "cannot read blob ${oid:0:8} — failing closed"
        before=${FINDINGS}
        scan_text "${label}" "${content}"
        (( FINDINGS > before )) && echo "HISTORY-FINDING ${oid} ${path:-<unnamed>}" >&2
    done < <(git rev-list --objects --all \
             | git cat-file --batch-check='%(objectname) %(objecttype) %(rest)')
    (( nblob == 0 && nskip == 0 )) \
        && _err_exit "history enumerated ZERO blobs — failing closed"
    _log "history sweep complete — scanned=${nblob} baselined=${nskip} findings=${FINDINGS}"
    if [[ ${FINDINGS} -gt 0 ]]; then
        echo "" >&2
        echo "╔ SCAN GATE: HISTORY SWEEP - ${FINDINGS} NEW finding(s) not on the baseline. See ${LOG_FILE:-stderr}" >&2
        return 1
    fi
    echo "[scan-gate] history sweep: CLEAN (${nblob} scanned, ${nskip} baselined)" >&2
    return 0
}

case "${MODE}" in
    prereceive) run_prereceive; exit $? ;;
    file) run_file; exit $? ;;
    tree) run_tree; exit $? ;;
    history) run_history; exit $? ;;
    selftest) run_selftest; exit $? ;;
esac
