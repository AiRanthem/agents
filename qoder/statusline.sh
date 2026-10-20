#!/usr/bin/env bash
# Qoder status line: model + reasoning effort and ctx usage on the left,
# credits (used/total + bar + refresh countdown) right-aligned to the terminal
# edge. The countdown targets the next 23rd 00:00 GMT+8 (monthly quota reset).
# Receives session JSON on stdin; prints a single line.
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
# Credits tab shows "used/total". Total = personal quota (plan + add-on), the
# team/org resource package, and all dedicated resource packages. Prefer the
# live `.credits` object supplied on stdin by qodercli; unlike total_remaining,
# its component fields include dedicated packages and expose both used/total.
# For older CLI versions or unavailable live quota data, fall back to
# ~/.qoder/quota-cache.json (the API response shape of GET /api/v2/quota/usage),
# refreshed at most every $QODER_QUOTA_TTL seconds (default 60). The refresh
# runs in a detached background child, so renders never block on the network.
# Refresh source, in order of preference:
#   1. PAT available (env QODER_PAT or first line of ~/.qoder/.pat): exchange it
#      for a short-lived token and call the API directly.
#   2. No PAT: harvest the newest full quota response logged by qodercli.
# Without any account quota data the tab falls back to session credits only.

# read-to-EOF builtin instead of a cat fork
IFS= read -r -d '' input || true

# ${#var} counts bytes under a C/empty locale; the bars and the ↻ below are
# multibyte, so pin a UTF-8 ctype or the right-alignment math falls apart.
export LC_ALL=en_US.UTF-8

if ! command -v jq >/dev/null 2>&1; then
  printf 'qoder\n'
  exit 0
fi

# --- parse the session JSON in one jq fork (was ~10 field-level forks). \001
# separator: IFS=tab would collapse empty fields and shift the rest.
# transcript_path goes last: it may hold spaces, but read stops splitting at the
# final field.
parsed=$(printf '%s' "$input" | jq -r '
    def num: (. // 0) | tonumber? // 0;
    def quota_pair:
      (.credits // {}) as $c
      | ($c.user_quota // $c.userQuota // {}) as $p
      | ($c.add_on_quota // $c.addOnQuota // {}) as $a
      | ($c.org_resource_package // $c.orgResourcePackage // {}) as $o
      | ($c.dedicated_resource_packages // $c.dedicatedResourcePackages // []) as $d
      | (($p.used | num) + ($a.used | num) + ($o.used | num)
          + ($d | map(.used | num) | add // 0)) as $used
      | (($p.total | num) + ($a.total | num)
          + (($o.used | num) + ($o.remaining | num))
          + ($d | map((.total // ((.used | num) + (.remaining | num))) | num) | add // 0)) as $total
      | if $total > 0 then "\($used) \($total)" else "" end;
    [ .model.display_name // .model.id // "qoder",
      (.context_window
        | if (.used_percentage != null) and ((.context_window_size // 0) > 0)
          then ((.context_window_size * .used_percentage / 100) | round)
          else "" end),
      (.context_window.context_window_size // ""),
      (.context_window.used_percentage // ""),
      (.cost.total_credits // ""),
      (.transcript_path // ""),
      quota_pair ]
    | map(tostring) | join("\u0001")' 2>/dev/null)
IFS=$'\001' read -r model used_tokens ctx_size used_pct session_credits \
  transcript_path live_quota_pair <<< "$parsed"

# --- reasoning effort and the context window for *this session*: qodercli
# appends a runtime-config record to the transcript at startup and on every
# /model or /effort change, so the last such record is the effective config.
# One awk fork rather than a jq fork: the record is flat and machine-generated.
# LC_ALL=C keeps awk on the byte path for a scan that never needs UTF-8 ctype.
effort=""; rc_ctx=""; rc_enabled="true"
if [ -n "$transcript_path" ] && [ -r "$transcript_path" ]; then
  IFS=$'\001' read -r effort rc_enabled rc_ctx < <(LC_ALL=C awk '
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
  # reasoning explicitly turned off for this session means no effort is shown
  [ "$rc_enabled" = "false" ] && effort=""
fi

# --- context: prefer JSON fields, fall back to last usage record in transcript
if [ -z "$used_tokens" ] || [ -z "$ctx_size" ]; then
  if [ -n "$transcript_path" ] && [ -r "$transcript_path" ]; then
    last=$(grep '"usage"' "$transcript_path" 2>/dev/null | tail -n 1)
    if [ -n "$last" ]; then
      IFS=$'\001' read -r t s < <(printf '%s' "$last" | jq -r '
        (.message.usage // .usage // {}) as $u
        | [(($u.input_tokens // 0) + ($u.cache_read_input_tokens // 0)
            + ($u.cache_creation_input_tokens // 0)),
           ($u.context_window_size // "")]
        | map(tostring) | join("\u0001")' 2>/dev/null)
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

# progress bar: "▓▓░░░░░░ 15%" from used/total; empty output when total is
# missing or 0 (caller then shows numbers only). Decimal inputs work via _deci.
bar() {
  local u t p f s i
  _deci "${1:-0}"; u=$_DECI
  _deci "${2:-0}"; t=$_DECI
  [ "$t" -le 0 ] && return 0
  p=$(( (u * 100 + t / 2) / t )); [ "$p" -gt 100 ] && p=100
  f=$(( (p * 8 + 50) / 100 )); [ "$f" -gt 8 ] && f=8
  s=""
  for i in 0 1 2 3 4 5 6 7; do
    if [ "$i" -lt "$f" ]; then s="${s}▓"; else s="${s}░"; fi
  done
  printf '%s %d%%' "$s" "$p"
}

# --- credits quota: used/total incl. team (org) resource package ---
quota_cache="$HOME/.qoder/quota-cache.json"
due_file="$HOME/.qoder/tmp/quota-refresh.due"
quota_ttl="${QODER_QUOTA_TTL:-60}"
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

# used/total include plan, add-on, org, and every dedicated resource package.
pair_prog='
  def num: (. // 0) | tonumber? // 0;
  (.user_quota // .userQuota // {}) as $p
  | (.add_on_quota // .addOnQuota // {}) as $a
  | (.org_resource_package // .orgResourcePackage // .shared_quota // .sharedQuota // {}) as $o
  | (.dedicated_resource_packages // .dedicatedResourcePackages // []) as $d
  | (($p.used | num) + ($a.used | num) + ($o.used | num)
      + ($d | map(.used | num) | add // 0)) as $used
  | (($p.total | num) + ($a.total | num) + ($o.used | num) + ($o.remaining | num)
      + ($d | map((.total // ((.used | num) + (.remaining | num))) | num) | add // 0)) as $total
  | if $total > 0 then "\($used) \($total)" else empty end
'

write_pair_sidecar() { # recompute the derived pair after a cache update
  local pair
  pair=$(jq -r "$pair_prog" "$quota_cache" 2>/dev/null)
  printf '%s\n' "${pair:--}" > "$quota_cache.pair.tmp" 2>/dev/null \
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

# Prefer the live quota pair parsed from stdin. For older CLI versions, read
# the derived cache pair (builtins only); the jq fallback also seeds it. "-"
# means "computed, but no usable quota".
quota_pair=$live_quota_pair
if [ -z "$quota_pair" ] && [ -r "$quota_cache.pair" ]; then
  IFS= read -r quota_pair < "$quota_cache.pair"
  [ "$quota_pair" = "-" ] && quota_pair=""
elif [ -z "$quota_pair" ] && [ -r "$quota_cache" ]; then
  quota_pair=$(jq -r "$pair_prog" "$quota_cache" 2>/dev/null)
  printf '%s\n' "${quota_pair:--}" > "$quota_cache.pair.tmp" 2>/dev/null \
    && mv "$quota_cache.pair.tmp" "$quota_cache.pair" 2>/dev/null
fi

# --- right-alignment helpers ---
is_num() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

# Terminal width: stdin is the piped session JSON, and the CLI spawns us
# without a controlling tty — /dev/tty fails to open and tput prints the
# terminfo default 80, not the real width. So climb the parent chain to the
# nearest ancestor still attached to a real tty and query that device.
# ponytail: the found tty is cached (re-validated with a live stty before
# each use), so the ps climb (up to 8 forks) happens once per session, not
# per render; stty output is parsed with the read builtin, no awk fork.
# Ceiling: two sessions in different terminals thrash the cache; harmlessly
# falls back to walking every time.
term_cols() {
  local c rows line tty pid i cache
  cache="$HOME/.qoder/tmp/statusline-tty"
  if [ -r "$cache" ]; then
    IFS= read -r tty < "$cache"
    if [ -n "$tty" ] && [ -e "/dev/$tty" ]; then
      read -r rows c < <(stty size <"/dev/$tty" 2>/dev/null)
      is_num "$c" && { printf '%s' "$c"; return; }
    fi
  fi
  read -r rows c < <(stty size </dev/tty 2>/dev/null)
  is_num "$c" && { printf '%s' "$c"; return; }
  pid=$PPID
  for i in 1 2 3 4 5 6 7 8; do
    is_num "$pid" && [ "$pid" -gt 1 ] || break
    line=$(ps -o tty= -o ppid= -p "$pid" 2>/dev/null)
    [ -n "$line" ] || break
    tty=${line%% *}; pid=${line##* }
    # tty is "?"/"??" when the process has none; /dev/<tty> test skips those
    [ -e "/dev/$tty" ] || continue
    read -r rows c < <(stty size <"/dev/$tty" 2>/dev/null)
    if is_num "$c"; then
      mkdir -p "$HOME/.qoder/tmp" 2>/dev/null
      printf '%s\n' "$tty" > "$cache" 2>/dev/null
      printf '%s' "$c"; return
    fi
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
gray=$'\033[38;5;240m'; reset=$'\033[0m'
sep="${reset}${gray} · ${reset}"

out=""; olen=0
add() { # $1 = colored segment, $2 = its plain display width; " · " is 3 cols
  if [ -n "$out" ]; then out="${out}${sep}$1"; olen=$((olen + 3 + $2))
  else out="$1"; olen=$2; fi
}

seg1="${model:-qoder}"
[ -n "$effort" ] && seg1="${seg1} ${effort}"
add "${purple}${seg1}${reset}" "${#seg1}"

if [ -n "$used_tokens" ]; then
  # used_tokens is the current occupancy (derived from used_percentage, or the
  # last transcript usage record), not the session-cumulative total_input_tokens;
  # still clamp to the window so an odd percentage never renders past 100%.
  if [ -n "$ctx_size" ] && [ "$used_tokens" -gt "$ctx_size" ] 2>/dev/null; then
    disp_used=$ctx_size
  else
    disp_used=$used_tokens
  fi
  ctx_label="ctx $(fmt "$disp_used")"
  [ -n "$ctx_size" ] && ctx_label="${ctx_label}/$(fmt "$ctx_size")"
  b=$(bar "$disp_used" "${ctx_size:-0}")
  [ -n "$b" ] && ctx_label="${ctx_label} ${b}"
  add "${yellow}${ctx_label}${reset}" "${#ctx_label}"
elif [ -n "$used_pct" ]; then
  is_num "$used_pct" && [ "$used_pct" -gt 100 ] && used_pct=100
  ctx_label="ctx ${used_pct}%"
  add "${yellow}${ctx_label}${reset}" "${#ctx_label}"
fi

cred_label=""
if [ -n "$quota_pair" ]; then
  q_used="${quota_pair%% *}"; q_total="${quota_pair##* }"
  cred_label="credits $(fmtc "$q_used")/$(fmtc "$q_total")"
  b=$(bar "$q_used" "$q_total")
  [ -n "$b" ] && cred_label="${cred_label} ${b}"
elif [ -n "$session_credits" ]; then
  cred_label="credits $(fmtc "$session_credits")"
fi
if [ -n "$cred_label" ]; then
  cdt=$(refresh_countdown)
  [ -n "$cdt" ] && cred_label="${cred_label} ↻ ${cdt}"
fi

if [ -n "$cred_label" ]; then
  right="${orange}${cred_label}${reset}"
  cols=$(term_cols)
  # Right-alignment confirmed in the real TUI, so the default margin is 0;
  # override via env if the footer layout changes.
  margin="${QODER_STATUSLINE_RIGHT_MARGIN:-0}"
  is_num "$margin" || margin=0
  pad=$(( cols - margin - olen - ${#cred_label} ))
  [ "$pad" -lt 1 ] && pad=1
  printf '%s%*s%s\n' "$out" "$pad" '' "$right"
else
  printf '%s\n' "$out"
fi
