#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# PR Review Spec MCP Server Setup Script
#
# A platform-agnostic setup script modeled after zen's run-server.sh. Handles
# environment setup, dependency installation (uv and fallback venv), CLI/desktop
# registration for Claude, Codex, and Gemini, optional Docker cleanup, and run.
# ============================================================================

# Initialize pyenv early if present
if [[ -d "$HOME/.pyenv" ]]; then
  export PYENV_ROOT="$HOME/.pyenv"
  export PATH="$PYENV_ROOT/bin:$PATH"
  if command -v pyenv &>/dev/null; then
    eval "$(pyenv init --path)" 2>/dev/null || true
    eval "$(pyenv init -)" 2>/dev/null || true
  fi
fi

# ----------------------------------------------------------------------------
# Constants and configuration
# ----------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
VENV_PATH=".pr_review_venv"
DOCKER_CLEANED_FLAG=".docker_cleaned"
DESKTOP_CONFIG_FLAG=".desktop_configured"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="mcp_server.log"
ENV_FILE=".env"
SERVER_NAME="pr-review-spec"

# Flags
DO_SYNC="false"           # dependency sync/install
USE_DEV="false"           # include dev deps
DO_LOG="false"            # write logs
DO_FOLLOW="false"         # follow logs (tee live)
DO_REGISTER="false"       # Claude CLI
DO_DESKTOP="false"        # Claude Desktop
DO_CODEX="false"          # Codex CLI
DO_GEMINI="false"         # Gemini CLI
DO_MIGRATE_ENV="false"    # host.docker.internal -> localhost
ASSUME_YES="false"        # auto-approve prompts
DO_DRYRUN="false"         # print instructions only (alias: --config)

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
ok() { echo -e "${GREEN}✓${NC} $*" >&2; }
warn() { echo -e "${YELLOW}!${NC} $*" >&2; }
err() { echo -e "${RED}✗${NC} $*" >&2; }
info() { echo -e "${YELLOW}$*${NC}" >&2; }

get_script_dir() { cd "$(dirname "$0")" && pwd; }

# Read version from pyproject.toml
read_version() {
  if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    local v
    v=$(grep -E '^version\s*=\s*"[^"]+"' "$SCRIPT_DIR/pyproject.toml" | head -1 | sed -E 's/.*"(.*)"/\1/')
    [[ -n "$v" ]] && echo "$v" && return 0
  fi
  echo "unknown"
}

prompt_yes() {
  # Usage: prompt_yes "Question? (Y/n): "
  local q="$1"
  if [[ "$ASSUME_YES" == "true" ]]; then return 0; fi
  if [[ ! -t 0 ]]; then return 1; fi
  read -p "$q" -n 1 -r; echo ""
  [[ ! $REPLY =~ ^[Nn]$ ]]
}

clear_python_cache() {
  info "Clearing Python cache files..."
  find . -name "*.pyc" -delete 2>/dev/null || true
  find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  ok "Python cache cleared"
}

detect_os() {
  case "$OSTYPE" in
    darwin*) echo "macos" ;;
    linux*)
      if grep -qi microsoft /proc/version 2>/dev/null; then echo "wsl"; else echo "linux"; fi ;;
    msys*|cygwin*|win32) echo "windows" ;;
    *) echo "unknown" ;;
  esac
}

get_claude_config_path() {
  local os_type=$(detect_os)
  case "$os_type" in
    macos) echo "$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
    linux) echo "$HOME/.config/Claude/claude_desktop_config.json" ;;
    wsl)
      if command -v wslvar &>/dev/null; then
        local win_appdata=$(wslvar APPDATA 2>/dev/null || true)
        [[ -n "$win_appdata" ]] && echo "$(wslpath "$win_appdata")/Claude/claude_desktop_config.json" && return
      fi
      echo "/mnt/c/Users/$USER/AppData/Roaming/Claude/claude_desktop_config.json" ;;
    windows) echo "$APPDATA/Claude/claude_desktop_config.json" ;;
    *) echo "" ;;
  esac
}

# ----------------------------------------------------------------------------
# Docker cleanup (one-time)
# ----------------------------------------------------------------------------
cleanup_docker() {
  [[ -f "$DOCKER_CLEANED_FLAG" ]] && return 0
  if ! command -v docker &>/dev/null || ! docker info &>/dev/null 2>&1; then
    return 0
  fi
  local found=false
  local containers=(
    "gemini-mcp-server" "gemini-mcp-redis"
    "zen-mcp-server" "zen-mcp-redis" "zen-mcp-log-monitor"
  )
  for c in "${containers[@]}"; do
    if docker ps -a --format "{{.Names}}" | grep -q "^${c}$" 2>/dev/null; then
      [[ "$found" == false ]] && echo "One-time Docker cleanup..." && found=true
      docker stop "$c" >/dev/null 2>&1 || true
      docker rm "$c" >/dev/null 2>&1 || true
    fi
  done
  local images=("gemini-mcp-server:latest" "zen-mcp-server:latest")
  for i in "${images[@]}"; do
    if docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${i}$" 2>/dev/null; then
      [[ "$found" == false ]] && echo "One-time Docker cleanup..." && found=true
      docker rmi "$i" >/dev/null 2>&1 || true
    fi
  done
  local volumes=("redis_data" "mcp_logs")
  for v in "${volumes[@]}"; do
    if docker volume ls --format "{{.Name}}" | grep -q "^${v}$" 2>/dev/null; then
      [[ "$found" == false ]] && echo "One-time Docker cleanup..." && found=true
      docker volume rm "$v" >/dev/null 2>&1 || true
    fi
  done
  [[ "$found" == true ]] && ok "Docker cleanup complete"
  touch "$DOCKER_CLEANED_FLAG"
}

# ----------------------------------------------------------------------------
# Python/venv bootstrap
# ----------------------------------------------------------------------------
get_venv_python_path() {
  local venv_path="$1"
  local abs=$(cd "$(dirname "$venv_path")" && pwd)/"$(basename "$venv_path")"
  if [[ -f "$abs/bin/python" ]]; then echo "$abs/bin/python"; return 0; fi
  if [[ -f "$abs/Scripts/python.exe" ]]; then echo "$abs/Scripts/python.exe"; return 0; fi
  return 1
}

detect_linux_distro() {
  if [[ -f /etc/os-release ]]; then . /etc/os-release; echo "${ID:-unknown}"; return; fi
  [[ -f /etc/debian_version ]] && echo "debian" && return
  [[ -f /etc/redhat-release ]] && echo "rhel" && return
  [[ -f /etc/arch-release ]] && echo "arch" && return
  echo "unknown"
}

get_install_command() {
  local distro="$1"; local python_version="${2:-}"
  local ver=""; [[ "$python_version" =~ ([0-9]+\.[0-9]+) ]] && ver="${BASH_REMATCH[1]}"
  case "$distro" in
    ubuntu|debian|raspbian|pop|linuxmint|elementary)
      if [[ -n "$ver" ]]; then
        echo "sudo apt update && (sudo apt install -y python${ver}-venv python${ver}-dev || sudo apt install -y python3-venv python3-pip)"; else echo "sudo apt update && sudo apt install -y python3-venv python3-pip"; fi ;;
    fedora) echo "sudo dnf install -y python3-venv python3-pip" ;;
    rhel|centos|rocky|almalinux|oracle) echo "sudo dnf install -y python3-venv python3-pip || sudo yum install -y python3-venv python3-pip" ;;
    arch|manjaro|endeavouros) echo "sudo pacman -Syu --noconfirm python-pip python-virtualenv" ;;
    opensuse|suse) echo "sudo zypper install -y python3-venv python3-pip" ;;
    alpine) echo "sudo apk add --no-cache python3-dev py3-pip py3-virtualenv" ;;
    *) echo "" ;;
  esac
}

can_use_sudo() {
  command -v sudo &>/dev/null || return 1
  sudo -n true 2>/dev/null && return 0
  [[ -t 0 ]] && sudo true 2>/dev/null && return 0
  return 1
}

try_install_system_packages() {
  local python_cmd="${1:-python3}"
  local os=$(detect_os)
  [[ "$os" == "linux" || "$os" == "wsl" ]] || return 1
  local ver=$($python_cmd --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)
  local distro=$(detect_linux_distro)
  local cmd=$(get_install_command "$distro" "$ver")
  [[ -z "$cmd" ]] && return 1
  info "Attempting to install required Python packages..."
  if can_use_sudo; then
    info "Installing system packages (may ask for password)..."
    bash -c "$cmd" >/dev/null 2>&1 && { ok "System packages installed"; return 0; }
  fi
  return 1
}

bootstrap_pip() {
  local vpython="$1"
  info "Bootstrapping pip in virtual environment..."
  if $vpython -m ensurepip --default-pip >/dev/null 2>&1; then ok "pip bootstrapped"; return 0; fi
  local url="https://bootstrap.pypa.io/get-pip.py"; local tmp=$(mktemp)
  if command -v curl &>/dev/null; then curl -fsSL "$url" -o "$tmp" || true; else wget -q "$url" -O "$tmp" || true; fi
  if [[ -s "$tmp" ]]; then $vpython "$tmp" >/dev/null 2>&1 && ok "pip installed"; fi
  rm -f "$tmp" || true
}

create_or_activate_virtualenv() {
  # Prefer uv if present and project is configured
  if command -v uv &>/dev/null; then
    # Ensure uv has a venv, otherwise fallback to system python virtualenv
    # We'll still resolve python path for CLI registrations
    local uv_py
    uv_py=$(uv run which python 2>/dev/null || true)
    if [[ -n "$uv_py" ]]; then echo "$uv_py"; return 0; fi
  fi

  # If already inside venv, prefer that
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    ok "Using activated virtual environment"
    echo "$(command -v python)"; return 0
  fi

  local python_cmd=""
  # Prefer pyenv local if present
  if [[ -f .python-version && $(command -v pyenv) ]]; then pyenv local &>/dev/null || true; fi
  for c in python3.12 python3.13 python3.11 python3 python; do
    if command -v "$c" &>/dev/null; then python_cmd="$c"; break; fi
  done
  if [[ -z "$python_cmd" ]]; then err "No Python found (3.10+ required)"; exit 1; fi

  # Create venv if missing
  if [[ ! -d "$VENV_PATH" ]]; then
    info "Creating virtual environment at $VENV_PATH..."
    if ! $python_cmd -m venv "$VENV_PATH" 2>/dev/null; then
      local err_out=$($python_cmd -m venv "$VENV_PATH" 2>&1 || true)
      if echo "$err_out" | grep -E -q "No module named venv|ensurepip|python3.*-venv"; then
        try_install_system_packages "$python_cmd" && $python_cmd -m venv "$VENV_PATH" >/dev/null 2>&1 || true
      fi
      if [[ ! -d "$VENV_PATH" ]]; then
        if command -v virtualenv &>/dev/null; then virtualenv -p "$python_cmd" "$VENV_PATH" >/dev/null 2>&1 || true; fi
      fi
      [[ -d "$VENV_PATH" ]] || { err "Unable to create virtual environment"; exit 1; }
    fi
    ok "Virtual environment created"
  fi

  local vpython
  vpython=$(get_venv_python_path "$VENV_PATH") || { err "Venv Python not found"; exit 1; }
  # Ensure pip exists
  if ! $vpython -m pip --version >/dev/null 2>&1; then bootstrap_pip "$vpython" || true; fi
  if ! $vpython -m pip --version >/dev/null 2>&1; then err "pip unavailable in venv"; exit 1; fi
  echo "$vpython"
}

install_dependencies() {
  local vpython="$1"
  info "Installing dependencies..."
  if command -v uv >/dev/null 2>&1; then
    if [[ "$USE_DEV" == "true" ]]; then uv sync --dev >/dev/null; else uv sync >/dev/null; fi
  else
    local has_req=false
    if [[ -f requirements.txt ]]; then has_req=true; "$vpython" -m pip install -r requirements.txt >/dev/null; fi
    if [[ "$has_req" == false && -f pyproject.toml ]]; then
      if [[ "$USE_DEV" == "true" ]]; then "$vpython" -m pip install -e .[dev] >/dev/null; else "$vpython" -m pip install -e . >/dev/null; fi
    fi
  fi
  ok "Dependencies installed"
}

# ----------------------------------------------------------------------------
# Env handling
# ----------------------------------------------------------------------------
read_env_vars() {
  local file="$1"; [[ -f "$file" ]] || return 0
  grep -E '^[[:space:]]*[^#][^=]*=.*$' "$file" | sed 's/^[[:space:]]*//' || true
}

prepare_env_file() {
  if [[ -f "$ENV_FILE" ]]; then return 0; fi
  info "No $ENV_FILE found. Server will still run; set GITHUB_TOKEN for GitHub API access."
  if [[ -f .env.example ]]; then
    if prompt_yes "Create .env from .env.example? (Y/n): "; then
      cp .env.example "$ENV_FILE"
      ok "Created $ENV_FILE from example"
      return 0
    fi
  fi
  # Fall back to creating a minimal .env with placeholders
  cat > "$ENV_FILE" <<EOF
# GitHub token for API access (PAT or fine-grained)
GITHUB_TOKEN=your_github_token_here

# Optional tuning
# HTTP_PER_PAGE=100
# PR_FETCH_MAX_PAGES=50
# PR_FETCH_MAX_COMMENTS=2000
# HTTP_MAX_RETRIES=3
EOF
  ok "Created minimal $ENV_FILE"
}

migrate_env_file() {
  [[ -f "$ENV_FILE" ]] || return 0
  if grep -q 'host\.docker\.internal' "$ENV_FILE"; then
    info "Migrating Docker hostnames in $ENV_FILE..."
    if sed --version >/dev/null 2>&1; then sed -i 's/host\.docker\.internal/localhost/g' "$ENV_FILE"; else sed -i '' 's/host\.docker\.internal/localhost/g' "$ENV_FILE"; fi
    ok "Migrated .env"
  fi
}

maybe_migrate_env_file() {
  [[ -f "$ENV_FILE" ]] || return 0
  if grep -q 'host\.docker\.internal' "$ENV_FILE"; then
    if prompt_yes "Replace host.docker.internal with localhost in $ENV_FILE? (Y/n): "; then
      migrate_env_file
    fi
  fi
}

check_api_keys() {
  local token_val=$(grep -E '^GITHUB_TOKEN=' "$ENV_FILE" 2>/dev/null | sed 's/^GITHUB_TOKEN=//')
  if [[ -n "${GITHUB_TOKEN:-}" && "${GITHUB_TOKEN}" != "your_github_token_here" ]]; then ok "GITHUB_TOKEN configured (env)"; return; fi
  if [[ -n "$token_val" && "$token_val" != "your_github_token_here" ]]; then ok "GITHUB_TOKEN configured (.env)"; return; fi
  warn "No GITHUB_TOKEN found; GitHub API may rate limit."
}

parse_env_variables() {
  local vars=""; [[ -f "$ENV_FILE" ]] || { echo "$vars"; return; }
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^[[:space:]]*([^=]+)=(.*)$ ]]; then
      local k="${BASH_REMATCH[1]}"; local v="${BASH_REMATCH[2]}"
      k=$(echo "$k" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      v=$(echo "$v" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/^"//;s/"$//')
      v=$(echo "$v" | sed 's/[[:space:]]*#.*$//')
      [[ -n "$v" && ! "$v" =~ ^your_.*_here$ && ! "$v" =~ ^[[:space:]]*$ ]] && vars+="$k=$v"$'\n'
    fi
  done < "$ENV_FILE"
  echo "$vars"
}

# ----------------------------------------------------------------------------
# Claude/Codex/Gemini integrations
# ----------------------------------------------------------------------------
build_claude_env_args() {
  local out=""; local env_vars=$(parse_env_variables)
  if [[ -n "$env_vars" ]]; then
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then out+=" -e ${BASH_REMATCH[1]}=\"${BASH_REMATCH[2]}\""; fi
    done <<< "$env_vars"
  fi
  echo "$out"
}

check_claude_cli_integration() {
  local vpython="$1"; local server_path="$2"
  if ! command -v claude &>/dev/null; then
    if [[ "$DO_REGISTER" == "true" ]]; then
      warn "Claude CLI not found. Install from: https://docs.anthropic.com/claude/docs/claude-code-cli"
    else
      info "Claude CLI not found; skipping registration"
    fi
    return 0
  fi
  info "Configuring Claude CLI ($SERVER_NAME)..."
  local env_args=$(build_claude_env_args)
  claude mcp remove "$SERVER_NAME" -s user >/dev/null 2>&1 || true
  local cmd="claude mcp add '$SERVER_NAME' -s user$env_args -- '$vpython' '$server_path'"
  if eval "$cmd" >/dev/null 2>&1; then ok "Claude CLI configured ($SERVER_NAME)"; else warn "Claude CLI registration failed"; fi
}

configure_claude_desktop() {
  local vpython="$1"; local server_path="$2"
  local cfg_path=$(get_claude_config_path); [[ -z "$cfg_path" ]] && return 0
  mkdir -p "$(dirname "$cfg_path")" 2>/dev/null || true
  local env_vars=$(parse_env_variables)
  local tmp=$(mktemp); local env_file=$(mktemp)
  [[ -n "$env_vars" ]] && echo "$env_vars" > "$env_file"
  python - "$cfg_path" "$vpython" "$server_path" "$env_file" << 'PY'
import json, sys, os
from json import JSONDecodeError
cfg_path, py, srv, env_file = sys.argv[1:5]
env = {}
try:
  with open(env_file) as f:
    for line in f:
      line=line.strip()
      if '=' in line and line:
        k,v=line.split('=',1)
        env[k]=v
except (OSError, ValueError):
  pass
cfg={'mcpServers':{}}
if os.path.exists(cfg_path):
  try:
    with open(cfg_path) as f: cfg=json.load(f) or cfg
  except (OSError, JSONDecodeError):
    pass
m=cfg.setdefault('mcpServers',{})
name=os.environ.get('SERVER_NAME','pr-review-spec')
entry={'command': py, 'args':[srv]}
if env: entry['env']=env
m[name]=entry
with open(cfg_path,'w') as f: json.dump(cfg,f,indent=2)
print(cfg_path)
PY
  rm -f "$tmp" "$env_file" 2>/dev/null || true
  ok "Claude Desktop configured at $cfg_path"
}

check_codex_cli_integration() {
  local vpython="$1"; local server_path="$2"
  if ! command -v codex &>/dev/null; then
    info "Codex CLI not found; skipping configuration"
    return 0
  fi
  local cfg="$HOME/.codex/config.toml"
  mkdir -p "$(dirname "$cfg")" 2>/dev/null || true
  local env_vars=$(parse_env_variables)
  # Remove existing section to make idempotent
  if [[ -f "$cfg" ]]; then
    # Delete prior [mcp_servers.$SERVER_NAME] and its nested env table if present
    # until the next [mcp_servers.*] section or EOF. Use portable sed.
    if sed --version >/dev/null 2>&1; then
      sed -i "/^\[mcp_servers\.${SERVER_NAME//\./\\.}\]/,/^\[mcp_servers\..*\]/d" "$cfg"
      # Also remove trailing empty lines
      sed -i ':a;N;$!ba;s/\n\{3,\}/\n\n/g' "$cfg"
    else
      # macOS/BSD sed
      sed -i '' "/^\[mcp_servers\.${SERVER_NAME//\./\\.}\]/,/^\[mcp_servers\..*\]/d" "$cfg"
    fi
  fi
  {
    echo ""; echo "[mcp_servers.$SERVER_NAME]"; echo "command = \"$vpython\""; echo "args = [\"$server_path\"]"; echo ""; echo "[mcp_servers.$SERVER_NAME.env]"; echo "PATH = \"/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$HOME/bin\"";
    if [[ -n "$env_vars" ]]; then
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
          local key="${BASH_REMATCH[1]}"; local value="${BASH_REMATCH[2]}"
          value=$(echo "$value" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
          echo "$key = \"$value\""
        fi
      done <<< "$env_vars"
    fi
  } >> "$cfg"
  ok "Codex CLI configured at $cfg ($SERVER_NAME)"
}

configure_gemini_cli() {
  local vpython="$1"; local server_path="$2"
  if [[ -z "${HOME:-}" ]]; then return 0; fi
  local gemini_cfg="$HOME/.gemini/settings.json"
  mkdir -p "$(dirname "$gemini_cfg")" 2>/dev/null || true
python - "$gemini_cfg" "$vpython" "$server_path" << 'PY'
import json, os, sys
from json import JSONDecodeError
cfg_path, py, srv = sys.argv[1:4]
cfg = {}
if os.path.exists(cfg_path):
  try:
    with open(cfg_path) as f: cfg=json.load(f) or {}
  except (OSError, JSONDecodeError):
    cfg={}
m = cfg.setdefault('mcpServers', {})
name = os.environ.get('SERVER_NAME','pr-review-spec')
m[name] = {'command': py, 'args': [srv]}
with open(cfg_path,'w') as f: json.dump(cfg,f,indent=2)
print(cfg_path)
PY
  ok "Gemini CLI configured"
}

# ----------------------------------------------------------------------------
# Display configuration instructions (Claude CLI, Desktop, Gemini, Codex)
# ----------------------------------------------------------------------------
display_config_instructions() {
  local python_cmd="$1"; local server_path="$2"; local script_dir=$(dirname "$server_path")
  echo ""
  local header="PR REVIEW SPEC MCP SERVER CONFIGURATION"
  echo "===== $header ====="
  printf '%*s\n' "$((${#header} + 12))" | tr ' ' '='
  echo ""

  info "1. Claude Code (CLI)"
  local env_vars=$(parse_env_variables)
  local env_args=""
  if [[ -n "$env_vars" ]]; then
    while IFS= read -r line; do
      if [[ -n "$line" && "$line" =~ ^([^=]+)=(.*)$ ]]; then
        env_args+=" -e ${BASH_REMATCH[1]}=\"${BASH_REMATCH[2]}\""
      fi
    done <<< "$env_vars"
  fi
  echo -e "   ${GREEN}claude mcp add $SERVER_NAME -s user$env_args -- $python_cmd $server_path${NC}"
  echo ""

  info "2. Claude Desktop"
  echo "   Add this to your Claude Desktop config file:"
  echo ""
  local example_env=""
  if [[ -n "$env_vars" ]]; then
    local first_entry=true
    while IFS= read -r line; do
      if [[ -n "$line" && "$line" =~ ^([^=]+)=(.*)$ ]]; then
        local key="${BASH_REMATCH[1]}"
        local value="your_$(echo "${key}" | tr '[:upper:]' '[:lower:]')"
        if [[ "$first_entry" == true ]]; then
          first_entry=false
          example_env="         \"$key\": \"$value\""
        else
          example_env+=",\n         \"$key\": \"$value\""
        fi
      fi
    done <<< "$env_vars"
  fi
  cat << EOF
   {
     "mcpServers": {
       "$SERVER_NAME": {
         "command": "$python_cmd",
         "args": ["$server_path"]$(if [[ -n "$example_env" ]]; then echo ","; fi)$(if [[ -n "$example_env" ]]; then echo "
         \"env\": {
$(echo -e "$example_env")
         }"; fi)
       }
     }
   }
EOF
  local config_path=$(get_claude_config_path)
  if [[ -n "$config_path" ]]; then
    echo ""
    info "   Config file location:"
    echo -e "   ${YELLOW}$config_path${NC}"
  fi
  echo ""
  info "   Restart Claude Desktop after updating the file"
  echo ""

  info "3. Gemini CLI"
  echo "   Add this to ~/.gemini/settings.json:"
  cat << EOF
   {
     "mcpServers": {
       "$SERVER_NAME": {
         "command": "$python_cmd",
         "args": ["$server_path"]
       }
     }
   }
EOF
  echo ""

  info "4. Codex CLI"
  echo "   Add this to ~/.codex/config.toml:"
  cat << EOF
   [mcp_servers.$SERVER_NAME]
   command = "$python_cmd"
   args = ["$server_path"]

   [mcp_servers.$SERVER_NAME.env]
   PATH = "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:\$HOME/.local/bin:\$HOME/.cargo/bin:\$HOME/bin"
EOF
  if [[ -n "$env_vars" ]]; then
    while IFS= read -r line; do
      if [[ -n "$line" && "$line" =~ ^([^=]+)=(.*)$ ]]; then
        local key="${BASH_REMATCH[1]}"
        echo "   ${key} = \"your_$(echo "${key}" | tr '[:upper:]' '[:lower:]')\""
      fi
    done <<< "$env_vars"
  else
    echo "   GITHUB_TOKEN = \"your_github_token_here\""
  fi
}

# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
usage() {
  cat >&2 <<EOF
Usage: ./run-server.sh [options]

Options:
  --sync             Install deps (requirements/pyproject)
  --dev              Include dev deps when installing
  --log              Tee output to logs/$LOG_FILE
  -f, --follow       Stream output and write logs/$LOG_FILE
  --env FILE         Path to .env (default: .env)
  --name NAME        Server name for CLI/desktop (default: pr-review-spec)
  --register         Register with Claude CLI
  --desktop          Configure Claude Desktop
  --codex            Configure Codex CLI
  --gemini           Configure Gemini CLI
  --migrate-env      Replace host.docker.internal -> localhost in .env
  -c, --config       Show client configuration instructions and exit
  --dry-run          Only print configuration instructions; do not run
  --clear-cache      Clear __pycache__/*.pyc and exit
  --version          Print version and exit
  --yes              Auto-approve interactive prompts
  -h, --help         Show help and exit

Examples:
  ./run-server.sh --sync --dev
  ./run-server.sh --register --desktop --codex --gemini
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sync) DO_SYNC="true"; shift ;;
      --dev) USE_DEV="true"; shift ;;
      --log) DO_LOG="true"; shift ;;
      -f|--follow) DO_FOLLOW="true"; DO_LOG="true"; shift ;;
      --env) ENV_FILE="$2"; shift 2 ;;
      --name) SERVER_NAME="$2"; shift 2 ;;
      --register) DO_REGISTER="true"; shift ;;
      --desktop) DO_DESKTOP="true"; shift ;;
      --codex) DO_CODEX="true"; shift ;;
      --gemini) DO_GEMINI="true"; shift ;;
      --migrate-env) DO_MIGRATE_ENV="true"; shift ;;
      -c|--config) DO_DRYRUN="true"; shift ;;
      --dry-run) DO_DRYRUN="true"; shift ;;
      --clear-cache) clear_python_cache; ok "Cache cleared"; exit 0 ;;
      --version) echo "$(read_version)"; exit 0 ;;
      --yes) ASSUME_YES="true"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) err "Unknown option: $1"; usage; exit 1 ;;
    esac
  done
}

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
parse_args "$@"

mkdir -p "$LOG_DIR"

# Header with version
HEADER="PR Review Spec MCP Server"
echo "$HEADER"
printf '%*s\n' "${#HEADER}" | tr ' ' '='
echo "Version: $(read_version)"
echo ""

clear_python_cache
cleanup_docker || true

prepare_env_file
if [[ "$DO_MIGRATE_ENV" == "true" ]]; then
  migrate_env_file
else
  maybe_migrate_env_file
fi
check_api_keys || true

if [[ "$DO_DRYRUN" == "true" ]]; then
  # Dry-run: print configuration instructions without mutating state
  DRY_PY="python"
  if command -v python3 >/dev/null 2>&1; then DRY_PY="python3"; fi
  display_config_instructions "$DRY_PY" "$SCRIPT_DIR/mcp_server.py" || true
  exit 0
fi

VPY=$(create_or_activate_virtualenv)
[[ "$DO_SYNC" == "true" ]] && install_dependencies "$VPY"

# Track whether we configured any client to avoid redundant banner
DID_REGISTER=false
DID_DESKTOP=false
DID_CODEX=false
DID_GEMINI=false

# Display a setup-complete banner similar to Zen and show helpful next steps
display_setup_complete() {
  echo ""
  local setup_header="SETUP COMPLETE"
  echo "===== $setup_header ====="
  printf '%*s\n' "$((${#setup_header} + 12))" | tr ' ' '='
  echo ""
  ok "$SERVER_NAME is ready to use!"
  echo ""
  echo "Logs will be written to: $LOG_DIR/$LOG_FILE"
  echo ""
  echo "To follow logs: ./run-server.sh -f"
  echo "To show config: ./run-server.sh -c"
  echo "To update: git pull, then run ./run-server.sh again"
  echo ""
  echo "Happy coding! 🎉"
  echo ""
}

display_setup_complete

if [[ "$DO_REGISTER" == "true" ]]; then
  check_claude_cli_integration "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_REGISTER=true
elif prompt_yes "Register with Claude CLI? (Y/n): "; then
  check_claude_cli_integration "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_REGISTER=true
fi
if [[ "$DO_DESKTOP" == "true" ]]; then
  SERVER_NAME="$SERVER_NAME" configure_claude_desktop "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_DESKTOP=true
elif prompt_yes "Configure Claude Desktop? (Y/n): "; then
  SERVER_NAME="$SERVER_NAME" configure_claude_desktop "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_DESKTOP=true
fi
if [[ "$DO_CODEX" == "true" ]]; then
  check_codex_cli_integration "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_CODEX=true
elif prompt_yes "Configure Codex CLI? (Y/n): "; then
  check_codex_cli_integration "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_CODEX=true
fi
if [[ "$DO_GEMINI" == "true" ]]; then
  configure_gemini_cli "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_GEMINI=true
elif prompt_yes "Configure Gemini CLI? (Y/n): "; then
  configure_gemini_cli "$VPY" "$SCRIPT_DIR/mcp_server.py" && DID_GEMINI=true
fi

info "Starting MCP server..."
export PYTHONUNBUFFERED=1
if command -v uv >/dev/null 2>&1; then
  if [[ "$DO_LOG" == "true" ]]; then
    echo "--- $(date) ---" >> "$LOG_DIR/$LOG_FILE"
    uv run -- python "$SCRIPT_DIR/mcp_server.py" 2>&1 | tee -a "$LOG_DIR/$LOG_FILE"
  else
    exec uv run -- python "$SCRIPT_DIR/mcp_server.py"
  fi
else
  if [[ "$DO_LOG" == "true" ]]; then
    echo "--- $(date) ---" >> "$LOG_DIR/$LOG_FILE"
    "$VPY" "$SCRIPT_DIR/mcp_server.py" 2>&1 | tee -a "$LOG_DIR/$LOG_FILE"
  else
    "$VPY" "$SCRIPT_DIR/mcp_server.py"
  fi
fi

if [[ "$DID_REGISTER" == "false" && "$DID_DESKTOP" == "false" && "$DID_CODEX" == "false" && "$DID_GEMINI" == "false" ]]; then
  display_config_instructions "$VPY" "$SCRIPT_DIR/mcp_server.py" || true
fi

# If follow requested and we logged, printing hint is redundant since tee streams live.
if [[ "$DO_FOLLOW" == "true" && "$DO_LOG" == "true" ]]; then
  info "Followed logs are streaming above; file: $LOG_DIR/$LOG_FILE"
fi
