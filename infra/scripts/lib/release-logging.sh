#!/usr/bin/env bash

timestamp_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_info() {
  printf '[%s] %s\n' "$(timestamp_utc)" "$*"
}

run_logged_step() {
  local label="$1"
  shift

  local started_at
  local finished_at
  local elapsed_seconds

  log_info "START ${label}"
  started_at="$(date +%s)"
  "$@"
  finished_at="$(date +%s)"
  elapsed_seconds="$((finished_at - started_at))"
  log_info "DONE ${label} (${elapsed_seconds}s)"
}
