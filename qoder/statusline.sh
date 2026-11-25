#!/usr/bin/env bash
# Qoder status line: model + reasoning effort and ctx usage on the left,
# credits (used/total + bar + refresh countdown) right-aligned to the terminal
# edge. The countdown targets the next 23rd 00:00 GMT+8 (monthly quota reset).
# Receives session JSON on stdin; prints a single line.
#
# The line is laid out against the real terminal width, measured by walking the
# process ancestry to the tty the CLI runs on. The two progress bars are elastic:
# they start at eight cells and shrink when the line does not fit, the context
# bar giving way before the credits bar. If that is still not enough, the
# countdown goes first, then the context percentage, then the context numbers,
# and the right side is finally cut on a word boundary. The numbers are never
# dropped, and the line never reaches past QODER_STATUSLINE_RIGHT_MARGIN
# (default 2) columns from the right edge.
#
# Reasoning effort and the context window are session state, read from the last
# runtime-config record qodercli appends to this session's transcript at startup
# and on every /model or /effort change:
# { "type": "runtime-config", "model": <id>, "reasoningEffort": <effort>,
#   "contextWindow": <number>, "generation": { "reasoning": { "enabled": bool,
#   "effort": <effort> } } }. The per-model memory in ~/.qoder/settings.json is
# deliberately not consulted: it holds global defaults, so it reports whatever
# session last ran /effort rather than what this session is actually using.
#
# Credits tab shows account usage as used/total (e.g. "credits 7205/20000").
# The account scope is the plan quota (user_quota), the add-on quota
# (add_on_quota), the team/org resource package (org_resource_package) and
# every model-scoped dedicated resource package; used/total sums the component
# fields directly, so dedicated packages are included (unlike the CLI's
# total_remaining balance). The live `.credits` object supplied on stdin by
# qodercli is authoritative. cost.total_credits is only this session's spend,
# not a balance, and is never shown here.
# For older CLI versions or unavailable live quota data, fall back to
# ~/.qoder/quota-cache.json (the API response shape of GET /api/v2/quota/usage),
# refreshed at most every $QODER_QUOTA_TTL seconds (default 60) and used only
# while it is younger than $QODER_QUOTA_MAX_AGE seconds (default 86400), so a
# stale snapshot never reports a quota total the account no longer has.
# The refresh runs in a detached background child, so renders never block on
# the network.
# Refresh source, in order of preference:
#   1. PAT available (env QODER_PAT or first line of ~/.qoder/.pat): exchange it
#      for a short-lived token and call the API directly.
#   2. No PAT: harvest the newest full quota response logged by qodercli.
# Without any fresh account quota data the credits segment is omitted.

# read-to-EOF builtin instead of a cat fork
IFS= read -r -d '' input || true

# ${#var} counts bytes under a C/empty locale; the bars and the ↻ below are
# multibyte, so pin a UTF-8 ctype or the right-alignment math falls apart.
# Probe it: a machine without en_US.UTF-8 silently falls back to the C locale,
# where every width below would be counted in bytes.
export LC_ALL=en_US.UTF-8
_lcprobe='▓'
if [ "${#_lcprobe}" -ne 1 ]; then
  for _lc in zh_CN.UTF-8 C.UTF-8 en_US.utf8; do
    LC_ALL=$_lc; export LC_ALL
    [ "${#_lcprobe}" -eq 1 ] && break
  done
fi

if ! command -v jq >/dev/null 2>&1; then
  printf 'qoder\n'
  exit 0
fi

# is_num: true when $1 is a non-empty run of digits
is_num() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

# --- account credits scope, shared by the live stdin payload and the on-disk
# quota cache so both report the same usage.
# Account scope = plan quota (user_quota) + add-on quota (add_on_quota) +
# team/org resource package (org_resource_package) + every model-scoped
# dedicated resource package. used/total sums the component fields directly,
# so dedicated packages are included (unlike the CLI's total_remaining balance).
# Both naming styles are accepted: the live .credits object uses snake_case,
# the cached API response uses camelCase.
acct_fn='
  def num: (. // 0) | tonumber? // 0;
  def obj: if type == "object" then . else {} end;
  def acct:
    obj as $c
    | ($c.user_quota // $c.userQuota // {}) as $p
    | ($c.add_on_quota // $c.addOnQuota // {}) as $a
    | ($c.org_resource_package // $c.orgResourcePackage
        // $c.shared_quota // $c.sharedQuota // {}) as $g
    | ($c.dedicated_resource_packages // $c.dedicatedResourcePackages // []) as $d
    | {
        used: (($p.used | num) + ($a.used | num) + ($g.used | num)
               + ($d | map(.used | num) | add // 0)),
        tot: (($p.total | num) + ($a.total | num)
              + (if ($g.cap | num) > 0 then ($g.cap | num)
                 else (($g.used | num) + ($g.remaining | num)) end)
              + ($d | map((.total // ((.used | num) + (.remaining | num))) | num) | add // 0))
      };
  def credits_acct:
    obj as $c
    | ($c | acct) as $x
    | { used: $x.used, tot: $x.tot };
'

# --- parse the session JSON in one jq fork (was ~10 field-level forks). \001
# separator: IFS=tab would collapse empty fields and shift the rest.
# The credits fields carry the account usage (used/total), not the
# session spend; see acct_fn above.
main_prog="${acct_fn}"'
    [ .model.display_name // .model.id // "qoder",
      (.context_window
        | if (.used_percentage != null) and ((.context_window_size // 0) > 0)
          then ((.context_window_size * .used_percentage / 100) | round)
          else "" end),
      (.context_window.context_window_size // ""),
      (.context_window.used_percentage // ""),
      (.cost.total_credits // ""),
      (.transcript_path // ""),
      (.credits | credits_acct | "\(.used) \(.tot)"),
      ((.credits.is_quota_exceeded // false) | tostring)
    ]
    | map(tostring) | join("\u0001")'
parsed=$(printf '%s' "$input" | jq -r "$main_prog" 2>/dev/null)
# split_fields: split $1 on the \001 separator into the FLD array. bash 3.2's
# read ignores a control character in IFS and hands back the whole record, and
# its ${var%%$'\001'*} drops the glob after the control character, so the
# split is done with parameter expansion over a pattern held in a variable.
sep_char=$'\001'
sep_tail=$'\001*'
split_fields() {
  local rest=$1
  FLD=()
  while :; do
    case $rest in
      *${sep_char}*) FLD+=("${rest%%$sep_tail}"); rest="${rest#*$sep_char}" ;;
      *) FLD+=("$rest"); break ;;
    esac
    [ -z "$rest" ] && { FLD+=(""); break; }
  done
}
split_fields "$parsed"
model=${FLD[0]}; used_tokens=${FLD[1]}; ctx_size=${FLD[2]}; used_pct=${FLD[3]}
session_credits=${FLD[4]}; transcript_path=${FLD[5]}
live_credits_pair=${FLD[6]}; quota_exceeded=${FLD[7]}

# --- reasoning effort and the context window for *this session*: qodercli
# appends a runtime-config record to the transcript at startup and on every
# /model or /effort change, so the last such record is the effective config.
# One awk fork rather than a jq fork: the record is flat and machine-generated.
# LC_ALL=C keeps awk on the byte path for a scan that never needs UTF-8 ctype.
effort=""; rc_ctx=""; rc_enabled="true"
if [ -n "$transcript_path" ] && [ -r "$transcript_path" ]; then
  rc_record=$(LC_ALL=C awk '
    function val(line, key) {
      if (match(line, "\"" key "\":\"[^\"]*\""))
        return substr(line, RSTART + length(key) + 4, RLENGTH - length(key) - 5)
      if (match(line, "\"" key "\":[0-9]+"))
        return substr(line, RSTART + length(key) + 3, RLENGTH - length(key) - 3)
      return ""
    }
    /"type":"runtime-config"/ { line = $0 }
    END {
      if (line == "") exit
      printf "%s\001%s\001%s\n", val(line, "reasoningEffort"),
        (line ~ /"enabled":false/ ? "false" : "true"), val(line, "contextWindow")
    }' "$transcript_path" 2>/dev/null)
  split_fields "$rc_record"
  effort=${FLD[0]}; rc_enabled=${FLD[1]:-true}; rc_ctx=${FLD[2]}
  # reasoning explicitly turned off for this session means no effort is shown
  [ "$rc_enabled" = "false" ] && effort=""
fi

# --- context: prefer JSON fields, fall back to last usage record in transcript
if [ -z "$used_tokens" ] || [ -z "$ctx_size" ]; then
  if [ -n "$transcript_path" ] && [ -r "$transcript_path" ]; then
    last=$(grep '"usage"' "$transcript_path" 2>/dev/null | tail -n 1)
    if [ -n "$last" ]; then
      usage_pair=$(printf '%s' "$last" | jq -r '
        (.message.usage // .usage // {}) as $u
        | [(($u.input_tokens // 0) + ($u.cache_read_input_tokens // 0)
            + ($u.cache_creation_input_tokens // 0)),
           ($u.context_window_size // "")]
        | map(tostring) | join("\u0001")' 2>/dev/null)
      split_fields "$usage_pair"
      t=${FLD[0]}; s=${FLD[1]}
      [ -n "$t" ] && [ "$t" != "0" ] && [ -z "$used_tokens" ] && used_tokens=$t
      [ -n "$s" ] && [ -z "$ctx_size" ] && ctx_size=$s
    fi
  fi
fi
# final fallback: the context window recorded for this session
[ -z "$ctx_size" ] && ctx_size=$rc_ctx

# --- number formatting in pure bash (was awk forks per render).
# _deci: decimal string -> integer centi-units, truncated to 2 decimals
# ("31.96" -> 3196, "0.5" -> 50, "12" -> 1200). Unparseable -> 0.
# ponytail: exact-tie rounding differs from awk's %.1f (half-up vs half-even);
# token counts and credit values hitting exact .xx5 ties is not realistic.
_deci() {
  local x=${1:-0} ip fp d1 d2 sign=1
  [[ $x =~ ^-?[0-9]*\.?[0-9]*$ ]] || { _DECI=0; return; }
  if [ "${x:0:1}" = "-" ]; then sign=-1; x=${x:1}; fi
  ip=${x%%.*}; fp=${x#*.}
  [ "$fp" = "$x" ] && fp="" # no dot present
  d1=${fp:0:1}; d2=${fp:1:1}
  _DECI=$(( sign * (${ip:-0} * 100 + ${d1:-0} * 10 + ${d2:-0}) ))
}

# 1234567 -> 1.2M, 12345 -> 12.3k, 1000000 -> 1.0M (one decimal kept, as awk did)
fmt() {
  local n=$(( ${1:-0} + 0 )) sc u
  if [ "$n" -ge 1000000 ]; then sc=$(( (n + 50000) / 100000 )); u=M
  elif [ "$n" -ge 1000 ]; then sc=$(( (n + 50) / 100 )); u=k
  else printf '%d' "$n"; return; fi
  printf '%d.%d%s' $((sc / 10)) $((sc % 10)) "$u"
}

# credit numbers: one decimal max, drop trailing ".0" (12 -> 12, 12.34 -> 12.3, 31.96 -> 32)
fmtc() {
  _deci "${1:-0}"
  local t=$(( (_DECI + 5) / 10 )) # tenths, rounded
  if [ $((t % 10)) -eq 0 ]; then printf '%d' $((t / 10))
  else printf '%d.%d' $((t / 10)) $((t % 10)); fi
}

# dwidth: display width of $1 in terminal columns, left in DW. ${#s} counts
# characters, which is what the TUI's string-width reports for the
# ambiguous-width glyphs used below (▓ ░ · are one column there), but a CJK
# character is one character and two columns. ASCII is one column, anything
# else is charged two. printf '%d' "'c" is a builtin and yields the
# character's value (the codepoint on bash 5, the leading byte on bash 3.2);
# both compare the same way against the 128 ASCII boundary, so no fork and no
# locale juggling is needed.
dwidth() {
  local s=$1 w=0 i n c b
  n=${#s}; i=0
  while [ "$i" -lt "$n" ]; do
    c=${s:$i:1}
    printf -v b '%d' "'$c"
    [ "$b" -lt 0 ] && b=$(( b + 256 )) # bash 3.2 reports bytes as signed
    if [ "$b" -lt 128 ]; then w=$(( w + 1 )); else w=$(( w + 2 )); fi
    i=$(( i + 1 ))
  done
  DW=$w
}

# dcut: the prefix of $1 that fits in $2 columns, left in DCUT. Same width
# rule as dwidth, so a CJK model name is cut by columns and not by characters.
dcut() {
  local s=$1 lim=$2 w=0 i n c b cw
  n=${#s}; i=0; DCUT=""
  while [ "$i" -lt "$n" ]; do
    c=${s:$i:1}
    printf -v b '%d' "'$c"
    [ "$b" -lt 0 ] && b=$(( b + 256 ))
    if [ "$b" -lt 128 ]; then cw=1; else cw=2; fi
    [ $(( w + cw )) -gt "$lim" ] && break
    DCUT="${DCUT}${c}"; w=$(( w + cw )); i=$(( i + 1 ))
  done
}

# progress bar: "▓▓░░░░░░ 15%" from used/total; empty output when total is
# missing or 0 (caller then shows numbers only). Decimal inputs work via _deci.
# bar_pct and bar_cells split the same numbers apart so the renderer can size
# the bar to the space it has; both leave their result in a global instead of
# printing, which keeps the per-render fork count down.
bar_pct() { # sets BAR_PCT
  local u t p
  _deci "${1:-0}"; u=$_DECI
  _deci "${2:-0}"; t=$_DECI
  BAR_PCT=""
  [ "$t" -le 0 ] && return 0
  p=$(( (u * 100 + t / 2) / t )); [ "$p" -gt 100 ] && p=100
  BAR_PCT="$p"
}
bar_cells() { # sets BAR_CELLS
  local u t w p f s i
  _deci "${1:-0}"; u=$_DECI
  _deci "${2:-0}"; t=$_DECI
  w=${3:-8}
  BAR_CELLS=""
  [ "$w" -le 0 ] && return 0
  [ "$t" -le 0 ] && return 0
  p=$(( (u * 100 + t / 2) / t )); [ "$p" -gt 100 ] && p=100
  f=$(( (p * w + 50) / 100 )); [ "$f" -gt "$w" ] && f=$w
  s=""; i=0
  while [ "$i" -lt "$w" ]; do
    if [ "$i" -lt "$f" ]; then s="${s}▓"; else s="${s}░"; fi
    i=$(( i + 1 ))
  done
  BAR_CELLS="$s"
}
bar() { # combined "cells pct" form, the shape the format self-check compares
  local u="${1:-0}" t="${2:-0}" w="${3:-8}"
  bar_pct "$u" "$t"
  [ -n "$BAR_PCT" ] || return 0
  bar_cells "$u" "$t" "$w"
  printf '%s %d%%' "$BAR_CELLS" "$BAR_PCT"
}

# --- credits quota: account usage (used/total) incl. team (org) + dedicated ---
quota_cache="$HOME/.qoder/quota-cache.json"
due_file="$HOME/.qoder/tmp/quota-refresh.due"
quota_ttl="${QODER_QUOTA_TTL:-60}"
quota_max_age="${QODER_QUOTA_MAX_AGE:-86400}"
openapi_base="${QODER_OPENAPI_BASE:-https://openapi.qoder.sh}"

pat="${QODER_PAT:-}"
if [ -z "$pat" ] && [ -r "$HOME/.qoder/.pat" ]; then
  IFS= read -r pat < "$HOME/.qoder/.pat" 2>/dev/null # builtin; was head|tr
  pat=${pat%$'\r'}
fi

file_mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null; }

# PAT path: exchange PAT for a short-lived token, fetch quota, refresh cache.
refresh_quota_via_pat() {
  [ -n "$pat" ] || return 1
  mkdir -p "$HOME/.qoder/tmp" 2>/dev/null
  lock="$HOME/.qoder/tmp/quota-refresh.lock"
  if ! mkdir "$lock" 2>/dev/null; then
    # abandon stale locks (> 120s) so a crashed refresh cannot block forever
    lm=$(file_mtime "$lock"); [ -n "$lm" ] && [ $(( $(date +%s) - lm )) -gt 120 ] && rmdir "$lock" 2>/dev/null
    mkdir "$lock" 2>/dev/null || return 1
  fi
  ok=1
  tok=$(curl -s --max-time 4 -H 'Content-Type: application/json' \
    -d "{\"personal_token\":\"$pat\"}" \
    "$openapi_base/api/v1/jobToken/exchange" 2>/dev/null \
    | jq -r '.token // .device_token // .access_token // empty' 2>/dev/null)
  [ -n "$tok" ] || ok=0
  if [ "$ok" = 1 ]; then
    resp=$(curl -s --max-time 4 -H 'Accept: application/json' \
      -H "Authorization: Bearer $tok" "$openapi_base/api/v2/quota/usage" 2>/dev/null)
    printf '%s' "$resp" | jq -e '.user_quota // .userQuota' >/dev/null 2>&1 || ok=0
  fi
  if [ "$ok" = 1 ]; then
    tmp="$quota_cache.tmp.$$"
    printf '%s' "$resp" > "$tmp" && mv "$tmp" "$quota_cache" || ok=0
  fi
  rmdir "$lock" 2>/dev/null
  [ "$ok" = 1 ]
}

# No-PAT path: qodercli itself calls GET /api/v2/quota/usage periodically
# and logs the full response; harvest the newest one from recent run logs.
# jq validation rejects transcript lines that merely quote the marker.
# ponytail: freshness bounded by the last quota call qodercli logged; entries
# older than 24h are rejected so stale data never masquerades as fresh.
refresh_quota_from_logs() {
  cutoff=$(date -v-24H +%Y-%m-%dT%H:%M:%S 2>/dev/null \
    || date -d '24 hours ago' +%Y-%m-%dT%H:%M:%S 2>/dev/null)
  # run dir names are CLI-generated timestamps without spaces; word-splitting ok
  for f in $(ls -t "$HOME"/.qoder/logs/runs/*/qodercli.log 2>/dev/null | head -8); do
    line=$(grep '\[qoderApi\] GET [^ ]*/api/v2/quota/usage response: ' "$f" 2>/dev/null | tail -1)
    [ -n "$line" ] || continue
    ts=${line%% *}
    [ -n "$cutoff" ] && [[ "$ts" < "$cutoff" ]] && continue
    json=${line##*response: }
    printf '%s' "$json" | jq -e '.user_quota // .userQuota' >/dev/null 2>&1 || continue
    tmp="$quota_cache.tmp.$$"
    printf '%s' "$json" > "$tmp" && mv "$tmp" "$quota_cache" && return 0
  done
  return 1
}

# Account pair "used total" from a quota payload (the live .credits
# object or the cached API response): same account scope on both paths.
pair_prog="${acct_fn}"'
  credits_acct | "\(.used) \(.tot)"'

# Sidecar: "v3 <used> <total> <cache mtime>". The mtime carries the
# freshness of the snapshot so a render can reject a stale cache without
# stat-ing the cache file again. The v3 tag marks the used/total derivation;
# older v2 (remaining/total) sidecars are ignored and recomputed.
write_pair_sidecar() { # recompute the derived pair after a cache update
  local pair mt
  pair=$(jq -r "$pair_prog" "$quota_cache" 2>/dev/null)
  mt=$(file_mtime "$quota_cache")
  case $mt in ''|*[!0-9]*) mt=0 ;; esac
  printf 'v3 %s %s\n' "${pair:-0 0}" "$mt" > "$quota_cache.pair.tmp" 2>/dev/null \
    && mv "$quota_cache.pair.tmp" "$quota_cache.pair" 2>/dev/null
}

# Refresh at most once per TTL, in a detached child: renders read the cache
# only and never wait on curl/log scans. stdout/stderr go to /dev/null so the
# child does not hold the CLI's output pipe open. The mkdir lock serializes
# concurrent PAT refreshes; atomic mv keeps cache reads consistent.
# ponytail: a deadline file (epoch seconds) replaces stat-ing cache/fail
# mtimes — one builtin read per render. The parent advances it before
# spawning, so failed refreshes retry only after the TTL as well.
# Ceiling: clock jumps backward delay the refresh until the clock catches up.
maybe_refresh_quota() {
  local now due
  now=${EPOCHSECONDS:-} # bash >= 5 builtin; avoids a date fork
  [ -n "$now" ] || now=$(date +%s)
  due=""
  [ -r "$due_file" ] && IFS= read -r due < "$due_file"
  case $due in ''|*[!0-9]*) due=0 ;; esac
  [ "$now" -ge "$due" ] || return 0
  mkdir -p "$HOME/.qoder/tmp" 2>/dev/null
  printf '%s\n' $((now + quota_ttl)) > "$due_file" 2>/dev/null
  (
    if { [ -n "$pat" ] && refresh_quota_via_pat; } || refresh_quota_from_logs; then
      write_pair_sidecar
    fi
  ) >/dev/null 2>&1 </dev/null &
  return 0
}
maybe_refresh_quota

# Prefer the live account usage parsed from stdin. For older CLI versions
# (or when the quota service did not answer), fall back to the cached API
# response, but only while it is fresh: an old snapshot would report a quota
# total the account no longer has.
q_used="${live_credits_pair%% *}"
q_tot="${live_credits_pair##* }"
if [ "$q_used" = "0" ] && [ "$q_tot" = "0" ]; then q_used=""; q_tot=""; fi
if [ -z "$q_used" ] && [ -z "$q_tot" ] && [ -r "$quota_cache" ]; then
  now=${EPOCHSECONDS:-} # bash >= 5 builtin; avoids a date fork
  [ -n "$now" ] || now=$(date +%s)
  side_ok=0
  if [ -r "$quota_cache.pair" ]; then
    IFS=' ' read -r s_tag s_used s_tot s_mt < "$quota_cache.pair"
    if [ "$s_tag" = "v3" ] && is_num "$s_used" && is_num "$s_tot" && is_num "$s_mt" \
       && [ $(( now - s_mt )) -ge 0 ] && [ $(( now - s_mt )) -le "$quota_max_age" ]; then
      q_used="$s_used"; q_tot="$s_tot"; side_ok=1
    fi
  fi
  if [ "$side_ok" -eq 0 ]; then
    # sidecar missing, outdated or stale: recompute from the cache and let
    # the cache mtime decide whether the snapshot is still usable
    pair=$(jq -r "$pair_prog" "$quota_cache" 2>/dev/null)
    mt=$(file_mtime "$quota_cache")
    case $mt in ''|*[!0-9]*) mt=0 ;; esac
    if [ "$mt" -gt 0 ] && [ $(( now - mt )) -ge 0 ] \
       && [ $(( now - mt )) -le "$quota_max_age" ]; then
      q_used="${pair%% *}"; q_tot="${pair##* }"
      printf 'v3 %s %s\n' "${pair:-0 0}" "$mt" > "$quota_cache.pair.tmp" 2>/dev/null \
        && mv "$quota_cache.pair.tmp" "$quota_cache.pair" 2>/dev/null
    fi
  fi
fi

# --- right-alignment helpers ---

# Terminal width: stdin is the piped session JSON, and the CLI spawns us
# without a controlling tty — /dev/tty fails to open and tput prints the
# terminfo default 80, not the real width. So climb the parent chain to the
# nearest ancestor still attached to a real tty and query that device.
# ponytail: one targeted ps per level (~4ms, a full-table ps costs ~100ms);
# the chain resolves at the first or second level in practice. The device size
# is re-read on every render, so a resized window is picked up immediately.
# Ceiling: the chain is walked per render; a session whose ancestors carry no
# tty at all falls back to tput/COLUMNS.
term_cols() {
  local c rows line tty pid i
  read -r rows c < <(stty size 2>/dev/null </dev/tty)
  is_num "$c" && [ "$c" -gt 0 ] && { printf '%s' "$c"; return; }
  pid=$PPID
  for i in 1 2 3 4 5 6 7 8; do
    is_num "$pid" && [ "$pid" -gt 1 ] || break
    line=$(ps -o tty= -o ppid= -p "$pid" 2>/dev/null)
    [ -n "$line" ] || break
    # read, not string splitting: ps pads its columns, so the ppid would keep
    # trailing blanks and fail the is_num test, ending the climb too early.
    read -r tty pid <<<"$line"
    is_num "$pid" || pid=0
    case "$tty" in ''|'?'|'??') continue ;; esac
    [ -c "/dev/$tty" ] || continue
    read -r rows c < <(stty size <"/dev/$tty" 2>/dev/null)
    if is_num "$c" && [ "$c" -gt 0 ]; then printf '%s' "$c"; return; fi
  done
  c=$(tput cols 2>/dev/null)
  is_num "$c" && [ "$c" -gt 0 ] && { printf '%s' "$c"; return; }
  c=${COLUMNS:-80}
  is_num "$c" && [ "$c" -gt 0 ] && { printf '%s' "$c"; return; }
  printf '80'
}

# Time left until the next 23rd 00:00 GMT+8 (monthly quota refresh). Fixed
# +08:00 offset via TZ / parsed offset — never the local timezone.
# ponytail: computing it takes two date forks, but the value changes at
# minute granularity, so cache it for 30s — most renders do a builtin file
# read instead. Only BSD/GNU date flavors covered.
refresh_countdown() {
  local now y m d ty tm target diff dd hh mi exp cdt
  local cache="$HOME/.qoder/tmp/statusline-countdown"
  now=${EPOCHSECONDS:-}
  [ -n "$now" ] || now=$(date +%s)
  if [ -r "$cache" ]; then
    IFS=$'\t' read -r exp cdt < "$cache"
    case $exp in ''|*[!0-9]*) exp=0 ;; esac
    if [ "$now" -lt "$exp" ] && [ -n "$cdt" ]; then
      printf '%s' "$cdt"; return 0
    fi
  fi
  read -r now y m d <<<"$(TZ=Asia/Shanghai date '+%s %Y %m %d')"
  is_num "$now" || return 0
  y=$((10#$y)); m=$((10#$m)); d=$((10#$d)) # base 10: "08"/"09" are invalid octal
  ty=$y; tm=$m
  if [ "$d" -ge 23 ]; then # this month's refresh already happened
    tm=$((m + 1))
    if [ "$tm" -gt 12 ]; then tm=1; ty=$((y + 1)); fi
  fi
  target=$(TZ=Asia/Shanghai date -j -f '%Y-%m-%d %H:%M:%S' \
      "$(printf '%04d-%02d-23 00:00:00' "$ty" "$tm")" +%s 2>/dev/null \
    || date -d "$(printf '%04d-%02d-23 00:00:00 +0800' "$ty" "$tm")" +%s 2>/dev/null)
  is_num "$target" || return 0
  diff=$((target - now)); [ "$diff" -lt 0 ] && diff=0
  dd=$((diff / 86400)); hh=$((diff % 86400 / 3600)); mi=$((diff % 3600 / 60))
  if [ "$dd" -gt 0 ]; then cdt="${dd}d ${hh}h"; else cdt="${hh}h ${mi}m"; fi
  mkdir -p "$HOME/.qoder/tmp" 2>/dev/null
  printf '%s\t%s\n' $((now + 30)) "$cdt" > "$cache" 2>/dev/null
  printf '%s' "$cdt"
}

# --- render: model + ctx on the left; credits + countdown right-aligned to the
# terminal edge (foreground only, no backgrounds) ---
# ponytail: soft truecolor/256 palette (was bright 35/33/32) so the bar blends
# with a dark terminal instead of glaring. Ceiling: fixed colors, no theme support.
purple=$'\033[38;2;136;176;255m'; yellow=$'\033[38;5;107m'; orange=$'\033[38;2;254;175;96m'
red=$'\033[38;5;203m'
gray=$'\033[38;5;240m'; reset=$'\033[0m'
sep="${reset}${gray} · ${reset}"

cols=$(term_cols)
# The TUI draws the footer inside a box that can be narrower than the terminal
# itself, so keep two columns of slack on the right; override when the layout
# changes.
margin="${QODER_STATUSLINE_RIGHT_MARGIN:-2}"
is_num "$margin" || margin=2
avail=$(( cols - margin ))
[ "$avail" -lt 1 ] && avail=1

# --- pieces, plain text; the colour is applied once at the very end ---
seg1="${model:-qoder}"
[ -n "$effort" ] && seg1="${seg1} ${effort}"

ctx_text=""; ctx_pct=""; ctx_u=""; ctx_t=""
if [ -n "$used_tokens" ]; then
  # used_tokens is the current occupancy (derived from used_percentage, or the
  # last transcript usage record), not the session-cumulative total_input_tokens;
  # still clamp to the window so an odd percentage never renders past 100%.
  if [ -n "$ctx_size" ] && [ "$used_tokens" -gt "$ctx_size" ] 2>/dev/null; then
    disp_used=$ctx_size
  else
    disp_used=$used_tokens
  fi
  ctx_text="ctx $(fmt "$disp_used")"
  [ -n "$ctx_size" ] && ctx_text="${ctx_text}/$(fmt "$ctx_size")"
  ctx_u="$disp_used"; ctx_t="${ctx_size:-0}"
  bar_pct "$ctx_u" "$ctx_t"
  [ -n "$BAR_PCT" ] && ctx_pct="${BAR_PCT}%"
elif [ -n "$used_pct" ]; then
  is_num "$used_pct" && [ "$used_pct" -gt 100 ] && used_pct=100
  ctx_text="ctx ${used_pct}%"
fi

# Credits tab: account usage as used/total (e.g. "credits 7205/20000"). The
# bar fills with the share already used; a red segment marks an exhausted
# quota. With no fresh account quota data (live .credits absent and no usable
# cache) the segment is omitted: cost.total_credits is this session's spend,
# not a balance, and is never shown here.
cred_text=""; cred_pct=""; cred_u=""; cred_t=""
if is_num "$q_tot" && [ "$q_tot" -gt 0 ]; then
  cred_text="credits $(fmtc "$q_used")/$(fmtc "$q_tot")"
  cred_u="$q_used"; cred_t="$q_tot"
  bar_pct "$cred_u" "$cred_t"
  [ -n "$BAR_PCT" ] && cred_pct="${BAR_PCT}%"
fi
cdt=""
[ -n "$cred_text" ] && cdt=$(refresh_countdown)

# --- width budget: the bars are elastic, the numbers are not ---
# The model name is the only text that can be non-ASCII, so it is measured
# with dwidth; every other piece is ASCII or an ambiguous-width glyph the TUI
# also counts as one column, where ${#} is the display width.
dwidth "$seg1"; L0=$DW
if [ -n "$ctx_text" ]; then
  L0=$(( L0 + 3 + ${#ctx_text} ))
  [ -n "$ctx_pct" ] && L0=$(( L0 + 1 + ${#ctx_pct} ))
fi
R0=0
[ -n "$cred_text" ] && R0=${#cred_text}
[ -n "$cred_pct" ] && R0=$(( R0 + 1 + ${#cred_pct} ))
[ -n "$cdt" ] && R0=$(( R0 + 3 + ${#cdt} )) # " ↻ 3d 4h"
join=0; [ -n "$cred_text" ] && join=1
budget=$(( avail - join - L0 - R0 ))

# Bars start at eight cells and give way in a fixed order: the context bar
# first, the credits bar second. A bar that runs out of room disappears and
# only its percentage is left.
ctx_cells=0; cred_cells=0
[ -n "$ctx_pct" ] && ctx_cells=8
[ -n "$cred_pct" ] && cred_cells=8
need=$(( ctx_cells + cred_cells ))
if [ "$need" -gt "$budget" ]; then
  over=$(( need - budget ))
  if [ "$over" -ge "$ctx_cells" ]; then ctx_cells=0; else ctx_cells=$(( ctx_cells - over )); fi
  need=$(( ctx_cells + cred_cells ))
  if [ "$need" -gt "$budget" ]; then
    cred_cells=$(( budget - ctx_cells ))
    [ "$cred_cells" -lt 0 ] && cred_cells=0
  fi
fi

# --- assemble, then drop what does not fit ---
build_labels() {
  ctx_label=""
  if [ -n "$ctx_text" ]; then
    ctx_label="$ctx_text"
    if [ "$ctx_cells" -gt 0 ]; then
      bar_cells "$ctx_u" "$ctx_t" "$ctx_cells"
      ctx_label="${ctx_label} ${BAR_CELLS}"
    fi
    [ -n "$ctx_pct" ] && ctx_label="${ctx_label} ${ctx_pct}"
  fi
  left_label="$seg1"
  [ -n "$ctx_label" ] && left_label="${left_label} · ${ctx_label}"
  right_label=""
  if [ -n "$cred_text" ]; then
    right_label="$cred_text"
    if [ "$cred_cells" -gt 0 ]; then
      bar_cells "$cred_u" "$cred_t" "$cred_cells"
      right_label="${right_label} ${BAR_CELLS}"
    fi
    [ -n "$cred_pct" ] && right_label="${right_label} ${cred_pct}"
    [ -n "$cdt" ] && right_label="${right_label} ↻ ${cdt}"
  fi
}
measure() { # width of the assembled line, left in W
  dwidth "$seg1"; W=$DW
  [ -n "$ctx_label" ] && W=$(( W + 3 + ${#ctx_label} ))
  [ -n "$right_label" ] && { W=$(( W + 1 + ${#right_label} )); }
}

build_labels; measure
while [ "$W" -gt "$avail" ]; do
  # the countdown goes first, then the context percentage, then the context
  # numbers; the credits numbers are the last thing that may go
  if [ -n "$cdt" ]; then
    cdt=""
  elif [ -n "$ctx_pct" ]; then
    ctx_pct=""; ctx_cells=0
  elif [ -n "$ctx_text" ]; then
    ctx_text=""; ctx_cells=0
  else
    break
  fi
  build_labels; measure
done

# last resort: cut the right side on a word boundary so nothing spills over
if [ -n "$right_label" ] && [ "$W" -gt "$avail" ]; then
  dwidth "$seg1"; keep=$(( avail - DW - 1 ))
  [ "$keep" -lt 0 ] && keep=0
  right_label="${right_label:0:$keep}"
  # a trailing "*" after the quoted space: bash otherwise folds the closing
  # parenthesis of the case pattern into the quoted word and never matches
  case "$right_label" in
    *" "*) right_label="${right_label% *}" ;;
  esac
  measure
fi
# the model name alone can still overflow a very narrow terminal
if [ "$W" -gt "$avail" ]; then
  ctx_text=""; ctx_pct=""; ctx_cells=0
  build_labels; measure
  if [ "$W" -gt "$avail" ]; then
    dwidth "$seg1"
    if [ "$DW" -gt "$avail" ]; then dcut "$seg1" "$avail"; seg1="$DCUT"; fi
    build_labels; measure
  fi
fi

left_out="${purple}${seg1}${reset}"
[ -n "$ctx_label" ] && left_out="${left_out}${sep}${yellow}${ctx_label}${reset}"
right_out=""
if [ -n "$right_label" ]; then
  if [ "$quota_exceeded" = "true" ]; then
    right_out="${red}${right_label}${reset}"
  else
    right_out="${orange}${right_label}${reset}"
  fi
fi

if [ -n "$right_out" ]; then
  dwidth "$seg1"; lw=$DW
  [ -n "$ctx_label" ] && lw=$(( lw + 3 + ${#ctx_label} ))
  rw=${#right_label}
  pad=$(( avail - lw - rw ))
  [ "$pad" -lt 1 ] && pad=1
  printf '%s%*s%s\n' "$left_out" "$pad" '' "$right_out"
else
  printf '%s\n' "$left_out"
fi
