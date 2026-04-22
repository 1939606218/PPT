#!/usr/bin/env bash
# ============================================================
#  BSH PPT 评分系统 — 一键启动脚本
#  用法：bash start.sh [stop|status|logs]
# ============================================================


# cd /home/wangjun/PPT_new

# bash start.sh           # 一键启动（PostgreSQL + 后端 + 前端）
# bash start.sh stop      # 停止后端和前端（DB 保持运行）
# bash start.sh restart   # 重启
# bash start.sh status    # 查看三个服务的运行状态
# bash start.sh logs backend   # 实时看后端日志
# bash start.sh logs frontend  # 实时看前端日志


set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend-react"
CONDA_BASE="$HOME/miniconda3"

BACKEND_PORT=18766
FRONTEND_PORT=5174

# 日志文件
LOG_DIR="$SCRIPT_DIR/.logs"
mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# PID 文件
PID_DIR="$SCRIPT_DIR/.pids"
mkdir -p "$PID_DIR"
BACKEND_PID="$PID_DIR/backend.pid"
FRONTEND_PID="$PID_DIR/frontend.pid"

# ── 颜色输出 ─────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── 工具函数 ─────────────────────────────────────────────────
is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

wait_port() {
  local port="$1" timeout="${2:-20}" i=0
  while ! nc -z localhost "$port" 2>/dev/null; do
    sleep 1; (( i++ ))
    [[ $i -ge $timeout ]] && return 1
  done
  return 0
}

# ── stop ─────────────────────────────────────────────────────
cmd_stop() {
  info "正在停止所有服务..."
  if is_running "$BACKEND_PID"; then
    kill "$(cat "$BACKEND_PID")" 2>/dev/null && success "已停止 backend (PID=$(cat "$BACKEND_PID"))"
  else
    warn "backend 未在运行"
  fi
  rm -f "$BACKEND_PID"
  info "（PostgreSQL Docker 容器保持运行，如需停止：docker compose -f '$SCRIPT_DIR/docker-compose.yml' stop）"
}

# ── status ────────────────────────────────────────────────────
cmd_status() {
  echo -e "\n${BOLD}━━━ 服务状态 ━━━${NC}"
  # PostgreSQL
  if docker ps --filter name=ppt_postgres --format "{{.Status}}" 2>/dev/null | grep -q "healthy\|Up"; then
    success "PostgreSQL   :5433  ✓ 运行中"
  else
    error   "PostgreSQL   :5433  ✗ 未运行"
  fi
  # Backend
  if is_running "$BACKEND_PID"; then
    success "Backend      :$BACKEND_PORT  ✓ 运行中  (PID=$(cat "$BACKEND_PID"))"
  else
    warn    "Backend      :$BACKEND_PORT  ✗ 未运行"
  fi
  echo ""
}

# ── logs ──────────────────────────────────────────────────────
cmd_logs() {
  tail -f "$BACKEND_LOG"
}

# ── start ─────────────────────────────────────────────────────
cmd_start() {
  echo -e "\n${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BOLD}    BSH PPT 评分系统 — 启动中               ${NC}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

  # ── 1. PostgreSQL ────────────────────────────────────────────
  info "步骤 1/3 · PostgreSQL..."
  if docker ps --filter name=ppt_postgres --format "{{.Status}}" 2>/dev/null | grep -q "healthy\|Up"; then
    success "PostgreSQL 已在运行，跳过"
  else
    if [[ ! -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
      error "找不到 docker-compose.yml，跳过数据库启动"
    else
      docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d
      info "等待数据库就绪..."
      sleep 3
      success "PostgreSQL 启动完成 (:5433)"
    fi
  fi

  # ── 2. 构建前端（生产模式）──────────────────────────────────
  info "步骤 2/3 · 构建前端（npm run build）..."
  cd "$FRONTEND_DIR"
  npm run build 2>&1 | tail -5
  if [[ ! -d "$FRONTEND_DIR/dist" ]]; then
    error "前端构建失败，请查看上方输出"
    exit 1
  fi
  success "前端构建完成 → dist/"

  # ── 3. Backend（托管前端 dist/）────────────────────────────
  info "步骤 3/3 · 后端 FastAPI（端口 $BACKEND_PORT）..."
  if is_running "$BACKEND_PID"; then
    warn "后端已在运行 (PID=$(cat "$BACKEND_PID"))，跳过（如需重新部署请先 stop）"
  else
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate base

    cd "$BACKEND_DIR"
    nohup python main.py > "$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID"
    info "等待后端就绪 (端口 $BACKEND_PORT)..."
    if wait_port "$BACKEND_PORT" 30; then
      success "后端启动完成 (PID=$(cat "$BACKEND_PID")，日志：$BACKEND_LOG)"
    else
      error "后端启动超时，请查看日志：tail -f $BACKEND_LOG"
    fi
  fi

  # ── 汇总 ─────────────────────────────────────────────────────
  echo -e "\n${BOLD}━━━ 启动完成 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "  🌐 访问地址：${GREEN}${BOLD}http://localhost:$BACKEND_PORT${NC}"
  echo -e "             ${GREEN}${BOLD}http://$(hostname -I | awk '{print $1}'):$BACKEND_PORT${NC}"
  echo -e "\n  常用命令："
  echo -e "    ${CYAN}bash start.sh status${NC}          — 查看服务状态"
  echo -e "    ${CYAN}bash start.sh stop${NC}            — 停止所有服务"
  echo -e "    ${CYAN}bash start.sh restart${NC}         — 重新构建并重启"
  echo -e "    ${CYAN}bash start.sh logs backend${NC}    — 查看后端日志"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

# ── 入口 ─────────────────────────────────────────────────────
case "${1:-start}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  logs)   cmd_logs "$@" ;;
  restart) cmd_stop; sleep 1; cmd_start ;;
  *)
    echo "用法：bash start.sh [start|stop|status|restart|logs <backend|frontend>]"
    exit 1
    ;;
esac
