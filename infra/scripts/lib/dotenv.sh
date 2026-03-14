#!/usr/bin/env bash

_dotenv_trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

_dotenv_normalize_value() {
  local trimmed="$(_dotenv_trim_whitespace "$1")"
  local first_char=""
  local last_char=""
  if [[ ${#trimmed} -ge 2 ]]; then
    first_char="${trimmed:0:1}"
    last_char="${trimmed: -1}"
    if [[ "$first_char" == "$last_char" && ( "$first_char" == "'" || "$first_char" == '"' ) ]]; then
      printf '%s' "${trimmed:1:${#trimmed}-2}"
      return
    fi
  fi
  printf '%s' "$trimmed"
}

dotenv_export_file() {
  local path="$1"
  local line=""
  local key=""
  local value=""

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ -z "${line//[[:space:]]/}" || "$line" =~ ^[[:space:]]*# ]]; then
      continue
    fi
    if [[ "$line" =~ ^[[:space:]]*export[[:space:]]+(.+)$ ]]; then
      line="${BASH_REMATCH[1]}"
    fi
    if [[ "$line" != *=* ]]; then
      continue
    fi

    key="$(_dotenv_trim_whitespace "${line%%=*}")"
    value="$(_dotenv_normalize_value "${line#*=}")"

    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "Invalid env key in ${path}: ${key}" >&2
      return 1
    fi

    export "$key=$value"
  done < "$path"
}
