#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CURRENT_USER="$(id -un)"
SELF_PID="$$"
DRY_RUN=false

if (($# > 1)); then
  printf 'Usage: %s [--dry-run]\n' "${BASH_SOURCE[0]}" >&2
  exit 2
fi

case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=true ;;
  *)
    printf 'Usage: %s [--dry-run]\n' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac

is_project_service() {
  local pid="$1" args="$2" cwd exe

  [[ "$pid" != "$SELF_PID" ]] || return 1
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" || return 1
  exe="$(readlink -f "/proc/$pid/exe" 2>/dev/null)" || return 1
  case "$cwd" in
    "$ROOT_DIR"|"$ROOT_DIR"/*) ;;
    *) return 1 ;;
  esac

  case "$args" in
    bash\ scripts/dev.sh*|bash\ */scripts/dev.sh*|*/bash\ scripts/dev.sh*|*/bash\ */scripts/dev.sh*)
      [[ "$exe" == */bash ]] || return 1
      ;;
    npm\ run\ dev*)
      case "$exe" in */node|*/npm|*/npm-cli.js) ;; *) return 1 ;; esac
      ;;
    sh\ -c\ vite\ --host*|bash\ -c\ vite\ --host*|dash\ -c\ vite\ --host*)
      case "$exe" in */sh|*/bash|*/dash) ;; *) return 1 ;; esac
      ;;
    *uvicorn*app.main:app*|*uvicorn*backend.app.main:app*)
      case "$exe" in */python|*/python[0-9]*|*/uv|*/uvicorn) ;; *) return 1 ;; esac
      ;;
    *node_modules/.bin/vite*)
      [[ "$exe" == */node ]] || return 1
      ;;
    *node_modules/@esbuild/*)
      [[ "$exe" == */esbuild ]] || return 1
      ;;
    *)
      return 1
      ;;
  esac

  return 0
}

is_live_project_service() {
  local pid="$1" args

  args="$(ps -p "$pid" -ww -o args= 2>/dev/null)" || return 1
  [[ -n "$args" ]] || return 1
  is_project_service "$pid" "$args"
}

candidate_pids=()
candidate_details=()
while read -r pid args; do
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  if is_project_service "$pid" "$args"; then
    candidate_pids+=("$pid")
    candidate_details+=("$pid $args")
  fi
done < <(ps -u "$CURRENT_USER" -ww -o pid=,args=)

if ((${#candidate_pids[@]} == 0)); then
  echo "No matching world_simulation_2D services found."
  exit 0
fi

echo "Matching world_simulation_2D services:"
printf '  %s\n' "${candidate_details[@]}"

if [[ "$DRY_RUN" == true ]]; then
  exit 0
fi

echo "Sending TERM..."
for pid in "${candidate_pids[@]}"; do
  is_live_project_service "$pid" && kill -TERM "$pid" 2>/dev/null || true
done

# ponytail: fixed five-second grace period; a service supervisor can replace this if needed.
remaining=("${candidate_pids[@]}")
deadline=$((SECONDS + 5))
while ((${#remaining[@]} > 0 && SECONDS < deadline)); do
  next_remaining=()
  for pid in "${remaining[@]}"; do
    is_live_project_service "$pid" && next_remaining+=("$pid")
  done
  remaining=("${next_remaining[@]}")
  ((${#remaining[@]} == 0)) || sleep 0.1
done

if ((${#remaining[@]} > 0)); then
  echo "Still running after 5 seconds; sending KILL to: ${remaining[*]}"
  for pid in "${remaining[@]}"; do
    is_live_project_service "$pid" && kill -KILL "$pid" 2>/dev/null || true
  done
  sleep 0.2
fi

survivors=()
for pid in "${candidate_pids[@]}"; do
  is_live_project_service "$pid" && survivors+=("$pid")
done

if ((${#survivors[@]} > 0)); then
  printf 'Unable to stop PIDs: %s\n' "${survivors[*]}" >&2
  exit 1
fi

echo "All matching services stopped."
