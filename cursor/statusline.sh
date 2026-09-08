#!/usr/bin/env bash
# Cursor CLI status line — model, context usage, daily token totals, and billing.
#
# Performance notes:
# - Hot path must stay well under CLI timeoutMs (default 2000ms). New updates kill
#   in-flight runs, so every extra subprocess risks a blank/stale status line.
# - Parse stdin / billing cache / daily token file with one jq each.
# - Prefer pure bash for formatting; never block render on network I/O.
#
# Billing cache (~/.cursor/statusline-billing-cache.json):
# - API at most once per CACHE_TTL seconds (120s); otherwise cache is reused.
# - Refresh always runs detached in the background.
#
# Daily token cache (~/.cursor/statusline-daily-tokens.json):
# - Best-effort cumulative In / Cache / Out / Tot for the current billing day.
# - Day boundary: 06:00 Asia/Shanghai (Beijing); single file, no history kept.
# - Per-session watermarks inside the file avoid double-counting across sessions.
# - Writes only when a new usage is accepted; unchanged refreshes are read-only.

set -euo pipefail
# Statusline must always produce stdout when possible; disable -e for the body.
set +e

input=$(cat)
NOW=$(date +%s)

# --- One-shot stdin parse ---
eval "$(printf '%s' "$input" | jq -r '
  def sh: tostring | @sh;
  [
    "WIDTH=\((.render_width_chars // 80) | sh)",
    "MODEL=\((.model.display_name // "Unknown") | sh)",
    "PARAMS=\((.model.param_summary // "") | sh)",
    "PCT=\(((.context_window.used_percentage // 0) | floor) | sh)",
    "CTX_SIZE=\((.context_window.context_window_size // "") | sh)",
    "SESSION_ID=\((.session_id // "") | sh)",
    "TOTAL_OUTPUT_RAW=\((.context_window.total_output_tokens // "") | sh)",
    "USAGE_JSON=\((.context_window.current_usage // null) | tojson | sh)"
  ] | join("\n")
' 2>/dev/null)" || true

WIDTH=${WIDTH:-80}
MODEL=${MODEL:-Unknown}
PARAMS=${PARAMS:-}
PCT=${PCT:-0}
CTX_SIZE=${CTX_SIZE:-}
SESSION_ID=${SESSION_ID:-}
TOTAL_OUTPUT_RAW=${TOTAL_OUTPUT_RAW:-}
USAGE_JSON=${USAGE_JSON:-null}
[ "$USAGE_JSON" = "null" ] && USAGE_JSON=""

# --- Pure-bash formatters (avoid awk/sed on the hot path) ---

format_tokens() {
  local n=${1:-0}
  case "$n" in
    ''|null|*[!0-9]*) n=0 ;;
  esac
  if (( n >= 1000000 )); then
    local whole=$((n / 1000000)) frac=$(( (n % 1000000) / 100000 ))
    if (( frac == 0 )); then printf '%dM' "$whole"; else printf '%d.%dM' "$whole" "$frac"; fi
  elif (( n >= 1000 )); then
    local whole=$((n / 1000)) frac=$(( (n % 1000) / 100 ))
    if (( frac == 0 )); then printf '%dk' "$whole"; else printf '%d.%dk' "$whole" "$frac"; fi
  else
    printf '%s' "$n"
  fi
}

format_ctx_window() {
  local formatted
  formatted=$(format_tokens "$1")
  [ -z "$formatted" ] && return
  # Strip trailing .0 before unit (e.g. 200.0k -> 200k)
  case "$formatted" in
    *.0k) printf '%s' "${formatted%.0k}k" ;;
    *.0M) printf '%s' "${formatted%.0M}M" ;;
    *) printf '%s' "$formatted" ;;
  esac
}

format_usd_cents() {
  local cents=$1
  case "$cents" in ''|null) return ;; esac
  case "$cents" in *[!0-9-]*) return ;; esac
  local sign="" abs=$cents
  if (( cents < 0 )); then sign="-"; abs=$((-cents)); fi
  printf '%s$%d.%02d' "$sign" $((abs / 100)) $((abs % 100))
}

format_pct() {
  local p=$1
  case "$p" in ''|null) return ;; esac
  # Keep two decimals via integer math when possible; fall back to printf.
  awk -v p="$p" 'BEGIN { printf "%.2f%%", p }' 2>/dev/null
}

# Format remaining time until billingCycleEnd (unix ms) as "refreshes in 5d14h".
format_refresh_in() {
  local end_ms=$1
  local now_s=$2
  local end_s rem d h m

  case "$end_ms" in ''|null|*[!0-9]*) return ;; esac
  # end_ms is unix ms as digits; bash arithmetic truncates.
  end_s=$(( end_ms / 1000 ))
  rem=$((end_s - now_s))
  if (( rem <= 0 )); then
    printf 'refreshes soon'
    return
  fi
  d=$((rem / 86400))
  h=$(((rem % 86400) / 3600))
  m=$(((rem % 3600) / 60))
  if (( d > 0 )); then
    printf 'refreshes in %dd%dh' "$d" "$h"
  elif (( h > 0 )); then
    printf 'refreshes in %dh%dm' "$h" "$m"
  else
    printf 'refreshes in %dm' "$m"
  fi
}

normalize_param_summary() {
  local s=$1
  s=${s#(}
  s=${s%)}
  # trim
  s=${s#"${s%%[![:space:]]*}"}
  s=${s%"${s##*[![:space:]]}"}
  printf '%s' "$s"
}

strip_ctx_size_label() {
  local s=$1
  # Rare path (model name cleanup); sed is fine here vs fragile bash regex.
  s=$(printf '%s' "$s" | sed -E 's/(^|[[:space:]])[0-9]+(\.[0-9]+)?[kKmM]([[:space:]]|$)/ /g')
  s=${s#"${s%%[![:space:]]*}"}
  s=${s%"${s##*[![:space:]]}"}
  while [[ "$s" == *"  "* ]]; do s=${s//  / }; done
  printf '%s' "$s"
}

model_includes_params() {
  local model=$1 params=$2
  local normalized
  [ -z "$params" ] && return 0
  normalized=$(normalize_param_summary "$params")
  normalized=$(strip_ctx_size_label "$normalized")
  [ -z "$normalized" ] && return 0
  case "$model" in
    *"$normalized"*) return 0 ;;
  esac
  return 1
}

# Only the ANSI codes this script emits need stripping.
visible_len() {
  local s=$1
  s=${s//$'\033[36m'/}
  s=${s//$'\033[90m'/}
  s=${s//$'\033[0m'/}
  printf '%s' "${#s}"
}

print_lr() {
  local left="$1" right="$2" width="${3:-$WIDTH}"
  local left_len right_len pad

  [ -z "$right" ] && printf '%s\n' "$left" && return
  [ -z "$left" ] && printf '%*s%s\n' "$width" "" "$right" && return

  left_len=$(visible_len "$left")
  right_len=$(visible_len "$right")
  pad=$((width - left_len - right_len))
  (( pad < 1 )) && pad=1
  printf '%s%*s%s\n' "$left" "$pad" "" "$right"
}

# --- Daily token accumulation (single file, today only) ---

DAILY_FILE="${HOME}/.cursor/statusline-daily-tokens.json"
DAILY_LOCK_DIR="${HOME}/.cursor/statusline-daily-tokens.lock"
TODAY=""
CUM_IN=0
CUM_CACHE_READ=0
CUM_CACHE_WRITE=0
CUM_OUT=0
LAST_TOTAL_OUTPUT=-1
LAST_USAGE_FP=""
HAS_FLOCK=""

session_id_ok() {
  local sid=$1
  [ -n "$sid" ] || return 1
  case "$sid" in
    *..*|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
  [ "${#sid}" -ge 1 ] && [ "${#sid}" -le 128 ]
}

ensure_flock_probe() {
  if [ -z "$HAS_FLOCK" ]; then
    if command -v flock >/dev/null 2>&1; then
      HAS_FLOCK=1
    else
      HAS_FLOCK=0
    fi
  fi
}

acquire_daily_lock() {
  DAILY_LOCK_KIND=""
  ensure_flock_probe
  if [ "$HAS_FLOCK" = "1" ]; then
    # shellcheck disable=SC3023
    exec 9>"${DAILY_LOCK_DIR}.flock" 2>/dev/null || return 1
    if flock -n 9 2>/dev/null; then
      DAILY_LOCK_KIND=flock
      return 0
    fi
    exec 9>&- 2>/dev/null
    return 1
  fi
  if mkdir "$DAILY_LOCK_DIR" 2>/dev/null; then
    DAILY_LOCK_KIND=mkdir
    return 0
  fi
  # Stale mkdir lock from a killed statusline invocation.
  if [ -d "$DAILY_LOCK_DIR" ]; then
    local lock_age lock_mtime
    lock_mtime=$(stat -f %m "$DAILY_LOCK_DIR" 2>/dev/null || echo "$NOW")
    lock_age=$((NOW - lock_mtime))
    if (( lock_age > 5 )); then
      rmdir "$DAILY_LOCK_DIR" 2>/dev/null || true
      if mkdir "$DAILY_LOCK_DIR" 2>/dev/null; then
        DAILY_LOCK_KIND=mkdir
        return 0
      fi
    fi
  fi
  return 1
}

release_daily_lock() {
  case "${DAILY_LOCK_KIND:-}" in
    flock)
      exec 9>&- 2>/dev/null
      ;;
    mkdir)
      rmdir "$DAILY_LOCK_DIR" 2>/dev/null || true
      ;;
  esac
  DAILY_LOCK_KIND=""
}

reset_daily_totals() {
  CUM_IN=0
  CUM_CACHE_READ=0
  CUM_CACHE_WRITE=0
  CUM_OUT=0
  LAST_TOTAL_OUTPUT=-1
  LAST_USAGE_FP=""
}

# "Today" key: Beijing date after shifting back 6 hours, so the day rolls at 06:00 CST.
daily_day_key() {
  # e.g. 05:59 → previous calendar day; 06:00 → current calendar day.
  TZ=Asia/Shanghai date -v-6H +%Y-%m-%d
}

# If file.day != today, totals reset to 0 (new day) but session watermarks are
# still loaded so a spanning session is not double-counted.
read_daily_file() {
  local file=$1 sid=$2 today=$3
  reset_daily_totals
  [ -f "$file" ] || return 1

  local assigns
  assigns=$(jq -r --arg sid "$sid" --arg today "$today" '
    def sh: tostring | @sh;
    if type != "object" then empty
    elif (.version // 0) != 1 then empty
    else
      (if (.day // "") == $today then 1 else 0 end) as $same_day
      | (.sessions[$sid] // {}) as $s
      | [
          "CUM_IN=\((if $same_day == 1 then (.cum_in // 0) else 0 end) | sh)",
          "CUM_CACHE_READ=\((if $same_day == 1 then (.cum_cache_read // 0) else 0 end) | sh)",
          "CUM_CACHE_WRITE=\((if $same_day == 1 then (.cum_cache_write // 0) else 0 end) | sh)",
          "CUM_OUT=\((if $same_day == 1 then (.cum_out // 0) else 0 end) | sh)",
          "LAST_TOTAL_OUTPUT=\(($s.last_total_output // -1) | sh)",
          "LAST_USAGE_FP=\(($s.last_usage_fp // "") | sh)"
        ] | join("\n")
    end
  ' "$file" 2>/dev/null) || return 1
  [ -n "$assigns" ] || return 1
  eval "$assigns"
  return 0
}

write_daily_file() {
  local file=$1 sid=$2 today=$3 now=$4
  local tmp="${file}.tmp.$$"
  # New calendar day: drop previous sessions map (only today's watermarks kept).
  # Same day: merge this session's watermark into existing sessions.
  local jq_prog='
    (if type == "object" and (.day // "") == $day then (.sessions // {}) else {} end) as $prev
    | {
        version: 1,
        day: $day,
        updated_at: $updated_at,
        cum_in: $cum_in,
        cum_cache_read: $cum_cache_read,
        cum_cache_write: $cum_cache_write,
        cum_out: $cum_out,
        sessions: ($prev + {
          ($sid): {
            last_total_output: $last_total_output,
            last_usage_fp: $last_usage_fp
          }
        })
      }
  '
  if [ -f "$file" ]; then
    jq \
      --arg sid "$sid" \
      --arg day "$today" \
      --argjson updated_at "$now" \
      --argjson cum_in "$CUM_IN" \
      --argjson cum_cache_read "$CUM_CACHE_READ" \
      --argjson cum_cache_write "$CUM_CACHE_WRITE" \
      --argjson cum_out "$CUM_OUT" \
      --argjson last_total_output "$LAST_TOTAL_OUTPUT" \
      --arg last_usage_fp "$LAST_USAGE_FP" \
      "$jq_prog" "$file" > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  else
    jq -n \
      --arg sid "$sid" \
      --arg day "$today" \
      --argjson updated_at "$now" \
      --argjson cum_in "$CUM_IN" \
      --argjson cum_cache_read "$CUM_CACHE_READ" \
      --argjson cum_cache_write "$CUM_CACHE_WRITE" \
      --argjson cum_out "$CUM_OUT" \
      --argjson last_total_output "$LAST_TOTAL_OUTPUT" \
      --arg last_usage_fp "$LAST_USAGE_FP" \
      "$jq_prog" > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  fi
  mv -f "$tmp" "$file"
}

# Decide whether to add current_usage; sets SHOULD_ADD=1/0.
# total_output_raw empty/null → fingerprint-only mode.
should_add_usage() {
  local total_raw=$1 fp=$2 last_total=$3 last_fp=$4
  SHOULD_ADD=0
  WATERMARK_MODE=none

  if [ -z "$total_raw" ] || [ "$total_raw" = "null" ]; then
    WATERMARK_MODE=null
    if [ "$fp" != "$last_fp" ]; then
      SHOULD_ADD=1
    fi
    return 0
  fi

  local total=${total_raw%%.*}
  case "$total" in ''|*[!0-9]*) return 1 ;; esac
  WATERMARK_MODE=numeric
  NEW_TOTAL_OUTPUT=$total

  if (( last_total < 0 )); then
    SHOULD_ADD=1
    return 0
  fi
  if (( total > last_total )); then
    SHOULD_ADD=1
    return 0
  fi
  if (( total < last_total )); then
    # Watermark epoch reset: keep cum_*, accept this usage.
    SHOULD_ADD=1
    return 0
  fi
  # total == last_total
  if [ "$fp" != "$last_fp" ]; then
    SHOULD_ADD=1
  fi
}

accumulate_daily_tokens() {
  local sid=$1 usage_json=$2 total_raw=$3 now=$4
  reset_daily_totals
  TODAY=$(daily_day_key)

  session_id_ok "$sid" || return 1

  if [ -f "$DAILY_FILE" ]; then
    if ! read_daily_file "$DAILY_FILE" "$sid" "$TODAY"; then
      # Corrupt file: show nothing, never overwrite with a zeroed rebuild.
      reset_daily_totals
      return 0
    fi
  fi

  if [ -z "$usage_json" ] || [ "$usage_json" = "null" ]; then
    return 0
  fi

  local u_in u_out u_cr u_cw fp
  # One jq for usage fields.
  eval "$(printf '%s' "$usage_json" | jq -r '
    def sh: tostring | @sh;
    [
      "u_in=\((.input_tokens // 0) | sh)",
      "u_out=\((.output_tokens // 0) | sh)",
      "u_cr=\((.cache_read_input_tokens // 0) | sh)",
      "u_cw=\((.cache_creation_input_tokens // 0) | sh)"
    ] | join("\n")
  ' 2>/dev/null)" || return 0
  fp="${u_in}|${u_cr}|${u_cw}|${u_out}"

  should_add_usage "$total_raw" "$fp" "${LAST_TOTAL_OUTPUT:--1}" "${LAST_USAGE_FP:-}" || return 0
  [ "${SHOULD_ADD:-0}" -eq 1 ] || return 0

  if ! acquire_daily_lock; then
    # Another invocation holds the lock; keep previously loaded display values.
    return 0
  fi

  # Re-read under lock to avoid double-count.
  if [ -f "$DAILY_FILE" ]; then
    if ! read_daily_file "$DAILY_FILE" "$sid" "$TODAY"; then
      release_daily_lock
      reset_daily_totals
      return 0
    fi
  else
    reset_daily_totals
  fi

  should_add_usage "$total_raw" "$fp" "${LAST_TOTAL_OUTPUT:--1}" "${LAST_USAGE_FP:-}" || {
    release_daily_lock
    return 0
  }
  if [ "${SHOULD_ADD:-0}" -ne 1 ]; then
    release_daily_lock
    return 0
  fi

  CUM_IN=$((CUM_IN + u_in))
  CUM_CACHE_READ=$((CUM_CACHE_READ + u_cr))
  CUM_CACHE_WRITE=$((CUM_CACHE_WRITE + u_cw))
  CUM_OUT=$((CUM_OUT + u_out))
  LAST_USAGE_FP=$fp
  if [ "${WATERMARK_MODE}" = "numeric" ]; then
    LAST_TOTAL_OUTPUT=$NEW_TOTAL_OUTPUT
  fi

  write_daily_file "$DAILY_FILE" "$sid" "$TODAY" "$now" || true
  release_daily_lock
}

format_daily_token_right() {
  local in=$1 cr=$2 cw=$3 out=$4
  local tot cache_txt right
  tot=$((in + cr + cw + out))
  if (( tot <= 0 )); then
    return
  fi
  cache_txt=$(format_tokens "$cr")
  if (( cw > 0 )); then
    cache_txt="${cache_txt}+$(format_tokens "$cw")"
  fi
  right=$(printf 'In %s · Cache %s · Out %s · Tot %s' \
    "$(format_tokens "$in")" "$cache_txt" "$(format_tokens "$out")" "$(format_tokens "$tot")")
  printf '\033[90m%s\033[0m' "$right"
}

# --- Billing (never block the render path on network) ---

CACHE_FILE="${HOME}/.cursor/statusline-billing-cache.json"
CACHE_TTL=120
SPEND=""
REMAINING=""
LIMIT=""
AUTO_PCT=""
API_PCT=""
AUTO_SPEND=""
API_SPEND=""
AUTO_LIMIT=""
API_LIMIT=""
BILLING_CYCLE_END=""
BILLING_UPDATED_AT=0

# One jq for the whole billing cache.
read_billing_cache() {
  [ -f "$CACHE_FILE" ] || return 1
  local assigns
  assigns=$(jq -r '
    def shempty:
      if . == null then "\"\"" else (tostring | @sh) end;
    if type != "object" then empty
    else
      [
        "BILLING_UPDATED_AT=\((.updated_at // 0) | tostring | @sh)",
        "SPEND=\(.spend | shempty)",
        "REMAINING=\(.remaining | shempty)",
        "LIMIT=\(.limit | shempty)",
        "AUTO_PCT=\(.auto_pct | shempty)",
        "API_PCT=\(.api_pct | shempty)",
        "AUTO_SPEND=\(.auto_spend | shempty)",
        "API_SPEND=\(.api_spend | shempty)",
        "AUTO_LIMIT=\(.auto_limit | shempty)",
        "API_LIMIT=\(.api_limit | shempty)",
        "BILLING_CYCLE_END=\(.billing_cycle_end | shempty)"
      ] | join("\n")
    end
  ' "$CACHE_FILE" 2>/dev/null) || return 1
  [ -n "$assigns" ] || return 1
  eval "$assigns"
  [ -n "$SPEND" ] && [ -n "$LIMIT" ]
}

cache_is_fresh() {
  [ -n "${BILLING_UPDATED_AT:-}" ] || return 1
  case "$BILLING_UPDATED_AT" in ''|*[!0-9]*) return 1 ;; esac
  (( NOW - BILLING_UPDATED_AT < CACHE_TTL ))
}

# Detached refresh: survives parent AbortController kill (new session).
# Invoked as: statusline.sh --refresh-billing
refresh_billing_main() {
  local token resp
  token=$(security find-generic-password -s "cursor-access-token" -a "cursor-user" -w 2>/dev/null) || return 1
  [ -n "$token" ] || return 1

  resp=$(curl -sS -m 2 -X POST \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -H "Connect-Protocol-Version: 1" \
    -d '{}' \
    "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage" 2>/dev/null) || return 1

  local spend remaining limit auto_pct api_pct auto_spend api_spend auto_limit api_limit cycle_end
  eval "$(printf '%s' "$resp" | jq -r '
    def sh: tostring | @sh;
    [
      "spend=\((.planUsage.includedSpend // "") | sh)",
      "remaining=\((.planUsage.remaining // "") | sh)",
      "limit=\((.planUsage.limit // "") | sh)",
      "auto_pct=\((.planUsage.autoPercentUsed // "") | sh)",
      "api_pct=\((.planUsage.apiPercentUsed // "") | sh)",
      "auto_spend=\((.planUsage.autoSpend // "") | sh)",
      "api_spend=\((.planUsage.apiSpend // "") | sh)",
      "auto_limit=\((.planUsage.autoLimit // "") | sh)",
      "api_limit=\((.planUsage.apiLimit // "") | sh)",
      "cycle_end=\((.billingCycleEnd // "") | sh)"
    ] | join("\n")
  ' 2>/dev/null)" || return 1

  [ -n "$spend" ] && [ -n "$limit" ] || return 1

  local now
  now=$(date +%s)
  mkdir -p "$(dirname "$CACHE_FILE")"
  local tmp="${CACHE_FILE}.tmp.$$"
  jq -n \
    --argjson updated_at "$now" \
    --argjson spend "$spend" \
    --argjson remaining "${remaining:-0}" \
    --argjson limit "$limit" \
    --arg auto_pct "${auto_pct}" \
    --arg api_pct "${api_pct}" \
    --arg auto_spend "${auto_spend}" \
    --arg api_spend "${api_spend}" \
    --arg auto_limit "${auto_limit}" \
    --arg api_limit "${api_limit}" \
    --arg billing_cycle_end "${cycle_end}" \
    '{
      updated_at: $updated_at,
      spend: $spend,
      remaining: $remaining,
      limit: $limit,
      auto_pct: (if $auto_pct == "" then null else ($auto_pct | tonumber) end),
      api_pct: (if $api_pct == "" then null else ($api_pct | tonumber) end),
      auto_spend: (if $auto_spend == "" then null else ($auto_spend | tonumber) end),
      api_spend: (if $api_spend == "" then null else ($api_spend | tonumber) end),
      auto_limit: (if $auto_limit == "" then null else ($auto_limit | tonumber) end),
      api_limit: (if $api_limit == "" then null else ($api_limit | tonumber) end),
      billing_cycle_end: (if $billing_cycle_end == "" then null else $billing_cycle_end end)
    }' > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  mv -f "$tmp" "$CACHE_FILE"
}

start_billing_refresh_bg() {
  # Avoid stampede: skip if a refresh started recently.
  local lock="${CACHE_FILE}.refreshing"
  local lock_mtime
  if [ -d "$lock" ]; then
    lock_mtime=$(stat -f %m "$lock" 2>/dev/null || echo 0)
    if (( NOW - lock_mtime < 30 )); then
      return 0
    fi
    rmdir "$lock" 2>/dev/null || true
  fi
  mkdir "$lock" 2>/dev/null || return 0

  # setsid detaches from CLI process group so AbortController cannot kill refresh.
  if command -v setsid >/dev/null 2>&1; then
    setsid "$0" --refresh-billing </dev/null >/dev/null 2>&1 &
  else
    # macOS often lacks setsid; nohup + disown is the next best option.
    nohup "$0" --refresh-billing </dev/null >/dev/null 2>&1 &
    disown $! 2>/dev/null || true
  fi
}

if [ "${1:-}" = "--refresh-billing" ]; then
  refresh_billing_main
  rc=$?
  rmdir "${CACHE_FILE}.refreshing" 2>/dev/null || true
  exit "$rc"
fi

if read_billing_cache; then
  cache_is_fresh || start_billing_refresh_bg
else
  # No cache yet: render without billing, refresh in background.
  start_billing_refresh_bg
fi

# Daily cumulative tokens (before line 2 render).
accumulate_daily_tokens "$SESSION_ID" "$USAGE_JSON" "$TOTAL_OUTPUT_RAW" "$NOW" >/dev/null 2>&1 || true

# Line 1: model + params | refreshes in XdYh (right)
MODEL=$(strip_ctx_size_label "$MODEL")
LINE1_LEFT=$(printf '\033[36m%s\033[0m' "$MODEL")
if [ -n "$PARAMS" ] && ! model_includes_params "$MODEL" "$PARAMS"; then
  LINE1_LEFT="$LINE1_LEFT $(printf '\033[36m%s\033[0m' "$(strip_ctx_size_label "$(normalize_param_summary "$PARAMS")")")"
fi

REFRESH_RIGHT=""
REFRESH_TEXT=$(format_refresh_in "${BILLING_CYCLE_END:-}" "$NOW")
[ -n "$REFRESH_TEXT" ] && REFRESH_RIGHT=$(printf '\033[90m%s\033[0m' "$REFRESH_TEXT")
print_lr "$LINE1_LEFT" "$REFRESH_RIGHT"

# Line 2: context usage bar | In / Cache / Out / Tot (daily cumulative)
BAR_WIDTH=12
PCT_NUM=${PCT:-0}
case "$PCT_NUM" in ''|*[!0-9]*) PCT_NUM=0 ;; esac
FILLED=$((PCT_NUM * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
(( FILLED > 0 )) && printf -v FILL "%${FILLED}s" && BAR="${FILL// /▓}"
(( EMPTY > 0 )) && printf -v PAD "%${EMPTY}s" && BAR="${BAR}${PAD// /░}"

CTX_LEFT=$(printf '\033[90mctx\033[0m %s' "$BAR")
if [ -n "$PCT" ] && [ "$PCT" != "0" ]; then
  CTX_LEFT="$CTX_LEFT $PCT%"
  case "$CTX_SIZE" in
    ''|null) ;;
    *[!0-9]*) ;;
    *)
      if (( CTX_SIZE > 0 )); then
        CTX_LEFT="$CTX_LEFT · $(format_ctx_window "$CTX_SIZE")"
      fi
      ;;
  esac
fi

TOK_RIGHT=$(format_daily_token_right "$CUM_IN" "$CUM_CACHE_READ" "$CUM_CACHE_WRITE" "$CUM_OUT")
print_lr "$CTX_LEFT" "$TOK_RIGHT"

# Line 3: billing — Cursor Models on left, Other Models pool on right
if [ -n "${SPEND:-}" ] && [ -n "${LIMIT:-}" ]; then
  # Rough estimate (Other Models has no separate dollar fields):
  #   Other Models ≈ apiPercentUsed% × plan limit
  #   Cursor Models ≈ includedSpend − Other Models estimate
  API_EST_CENTS=""
  FP_EST_CENTS=""
  case "${API_PCT:-}" in
    ''|null) ;;
    *)
      if (( LIMIT > 0 )); then
        API_EST_CENTS=$(awk -v pct="$API_PCT" -v lim="$LIMIT" 'BEGIN { printf "%.0f", pct * lim / 100 }')
        FP_EST_CENTS=$(awk -v spend="$SPEND" -v api="$API_EST_CENTS" 'BEGIN { v = spend - api; if (v < 0) v = 0; printf "%.0f", v }')
      fi
      ;;
  esac

  BILLING_LEFT=""
  case "${AUTO_PCT:-}" in
    ''|null)
      if [ -n "${AUTO_SPEND:-}" ] && [ "$AUTO_SPEND" != "null" ] && [ -n "${AUTO_LIMIT:-}" ] && [ "$AUTO_LIMIT" != "null" ]; then
        BILLING_LEFT=$(printf '\033[90mCursor Models\033[0m %s/%s' "$(format_usd_cents "$AUTO_SPEND")" "$(format_usd_cents "$AUTO_LIMIT")")
      fi
      ;;
    *)
      BILLING_LEFT=$(printf '\033[90mCursor Models\033[0m %s' "$(format_pct "$AUTO_PCT")")
      if [ -n "$FP_EST_CENTS" ]; then
        BILLING_LEFT="$BILLING_LEFT $(printf '\033[90m≈\033[0m') $(format_usd_cents "$FP_EST_CENTS")"
      fi
      ;;
  esac

  BILLING_RIGHT=""
  case "${API_PCT:-}" in
    ''|null)
      if [ -n "${API_SPEND:-}" ] && [ "$API_SPEND" != "null" ] && [ -n "${API_LIMIT:-}" ] && [ "$API_LIMIT" != "null" ]; then
        case "$API_LIMIT" in *[!0-9]*) ;; *)
          if (( API_LIMIT > 0 )); then
            BILLING_RIGHT=$(printf '\033[90mOther Models\033[0m %s/%s' "$(format_usd_cents "$API_SPEND")" "$(format_usd_cents "$API_LIMIT")")
          fi
          ;;
        esac
      fi
      if [ -z "$BILLING_RIGHT" ]; then
        BILLING_RIGHT="$(format_usd_cents "$SPEND") / $(format_usd_cents "$LIMIT")"
      fi
      ;;
    *)
      BILLING_RIGHT=$(printf '\033[90mOther Models\033[0m %s' "$(format_pct "$API_PCT")")
      if [ -n "$API_EST_CENTS" ]; then
        BILLING_RIGHT="$BILLING_RIGHT $(printf '\033[90m≈\033[0m') $(format_usd_cents "$API_EST_CENTS") / $(format_usd_cents "$LIMIT")"
      else
        BILLING_RIGHT="$BILLING_RIGHT / $(format_usd_cents "$LIMIT")"
      fi
      ;;
  esac

  print_lr "$BILLING_LEFT" "$BILLING_RIGHT"
fi
