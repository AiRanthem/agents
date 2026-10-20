#!/usr/bin/env bash
# Self-check for the pure-bash fmt/fmtc/bar in ~/.qoder/statusline.sh:
# compares them against the original awk implementations. Run after editing
# the formatting functions. Exact decimal ties (.x5) are reported separately:
# bash rounds half-up, glibc %.1f half-even — documented ceiling.
export LC_ALL=en_US.UTF-8
script="$HOME/.qoder/statusline.sh"
eval "$(sed -n '/^# --- number formatting in pure bash/,/^# --- credits quota/p' "$script" | sed '$d')"

awk_fmt() { awk -v n="${1:-0}" 'BEGIN { if (n >= 1000000) printf "%.1fM", n / 1000000; else if (n >= 1000) printf "%.1fk", n / 1000; else printf "%d", n; }'; }
awk_fmtc() { awk -v n="${1:-0}" 'BEGIN { s = sprintf("%.1f", n + 0); sub(/\.0$/, "", s); printf "%s", s }'; }
awk_bar() { awk -v u="${1:-0}" -v t="${2:-0}" 'BEGIN { if (t + 0 <= 0) exit; p = int(u * 100 / t + 0.5); if (p > 100) p = 100; f = int(p * 8 / 100 + 0.5); if (f > 8) f = 8; s = ""; for (i = 0; i < 8; i++) s = s (i < f ? "\342\226\223" : "\342\226\221"); printf "%s %d%%", s, p }'; }

fail=0 ties=0
for n in 0 1 42 999 1000 1001 1049 1051 1234 9949 9951 9999 12345 99949 99951 99999 100000 123456 999949 999951 999999 1000000 1000001 1049999 1050001 1234567 1999999 2000000 10000000 123456789; do
  a=$(awk_fmt "$n"); b=$(fmt "$n")
  [ "$a" = "$b" ] || { echo "fmt MISMATCH n=$n awk=[$a] bash=[$b]"; fail=1; }
done
for c in 0 0.5 1 1.0 12 12.3 12.34 31.96 31.99 31.996 100 1000.2 0.05 20000 4770 0.1 3.14159 .5 7. 0.001 99.94 123456.78; do
  a=$(awk_fmtc "$c"); b=$(fmtc "$c")
  [ "$a" = "$b" ] || { echo "fmtc MISMATCH c=$c awk=[$a] bash=[$b]"; fail=1; }
done
# exact decimal ties: informational only (half-up vs half-even)
for c in 12.25 99.95 0.15 2.35 1000.25; do
  a=$(awk_fmtc "$c"); b=$(fmtc "$c")
  [ "$a" = "$b" ] || { echo "fmtc tie (known): c=$c awk=[$a] bash=[$b]"; ties=$((ties+1)); }
done
for pair in "0 100" "1 100" "4 100" "12 100" "24 100" "50 100" "74 100" "99 100" "100 100" "150 100" "4770 20000" "123456 1000000" "1 3" "2 3" "5 8" "0.5 2" "1.5 2" "12.34 99.9" "1 0" "0 0" "7 7" "1234567 2000000"; do
  u=${pair%% *}; t=${pair##* }
  a=$(awk_bar "$u" "$t"); b=$(bar "$u" "$t")
  [ "$a" = "$b" ] || { echo "bar MISMATCH u=$u t=$t awk=[$a] bash=[$b]"; fail=1; }
done
[ $fail -eq 0 ] && echo "ALL MATCH (ties noted: $ties)" || exit 1
