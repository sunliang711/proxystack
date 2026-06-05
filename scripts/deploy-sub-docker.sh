#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

IMAGE="proxystack-sub:latest"
CONTAINER_NAME="proxystack-sub"
DATA_DIR="/opt/proxystack/sub"
HOST="0.0.0.0"
PORT="3003"
CONTAINER_USER="10001:10001"
DATA_OWNER="10001:10001"
PULL_IMAGE="0"
REPLACE_CONTAINER="0"

# 展示 Docker 部署脚本用法。
usage() {
	cat <<'EOF'
Usage: scripts/deploy-sub-docker.sh [options]

Deploy proxystack-sub with Docker using a persistent host data directory mapped
to container /data. Existing containers are never replaced unless --replace is
explicitly provided.

Options:
  --image IMAGE            Docker image. Default: proxystack-sub:latest
  --name NAME              Container name. Default: proxystack-sub
  --data-dir DIR           Host data directory mounted to /data. Default: /opt/proxystack/sub
  --host HOST              Host bind address. Default: 0.0.0.0
  --port PORT              Host port mapped to container port 3003. Default: 3003
  --user UID:GID           Container user. Default: 10001:10001
  --data-owner UID:GID     Host data directory owner. Default: 10001:10001
  --pull                   Pull image before running.
  --replace                Remove an existing same-name container before running.
  --dry-run                Print commands without executing writes.
  -h, --help               Show this help.
EOF
}

# 读取带值参数，并拒绝缺失值。
read_arg() {
	local option_name="${1:-}"
	local option_value="${2:-}"
	if [[ -z "${option_value}" || "${option_value}" == --* ]]; then
		die "${option_name} requires a value"
	fi
	printf '%s' "${option_value}"
}

# 解析命令行参数。
parse_args() {
	while [[ "$#" -gt 0 ]]; do
		case "$1" in
			--image)
				IMAGE="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--image=*)
				IMAGE="${1#*=}"
				shift
				;;
			--name)
				CONTAINER_NAME="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--name=*)
				CONTAINER_NAME="${1#*=}"
				shift
				;;
			--data-dir)
				DATA_DIR="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--data-dir=*)
				DATA_DIR="${1#*=}"
				shift
				;;
			--host)
				HOST="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--host=*)
				HOST="${1#*=}"
				shift
				;;
			--port)
				PORT="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--port=*)
				PORT="${1#*=}"
				shift
				;;
			--user)
				CONTAINER_USER="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--user=*)
				CONTAINER_USER="${1#*=}"
				shift
				;;
			--data-owner)
				DATA_OWNER="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--data-owner=*)
				DATA_OWNER="${1#*=}"
				shift
				;;
			--pull)
				PULL_IMAGE="1"
				shift
				;;
			--replace)
				REPLACE_CONTAINER="1"
				shift
				;;
			--dry-run)
				DRY_RUN="1"
				shift
				;;
			-h|--help)
				usage
				exit 0
				;;
			*)
				die "Unknown argument: $1"
				;;
		esac
	done
}

# 校验 Docker 参数和托管数据目录。
validate_args() {
	if [[ -z "${IMAGE}" || "${IMAGE}" == -* ]]; then
		die "Image must not be empty or start with '-'"
	fi
	if [[ -z "${CONTAINER_NAME}" || "${CONTAINER_NAME}" == -* ]]; then
		die "Container name must not be empty or start with '-'"
	fi
	if [[ -z "${HOST}" || "${HOST}" == -* ]]; then
		die "Host must not be empty or start with '-'"
	fi
	if [[ ! "${PORT}" =~ ^[0-9]+$ || "${PORT}" -lt 1 || "${PORT}" -gt 65535 ]]; then
		die "Port must be between 1 and 65535"
	fi
	if [[ -z "${CONTAINER_USER}" || "${CONTAINER_USER}" == -* ]]; then
		die "Container user must not be empty or start with '-'"
	fi
	if [[ -z "${DATA_OWNER}" || "${DATA_OWNER}" == -* ]]; then
		die "Data owner must not be empty or start with '-'"
	fi
	guard_managed_path "${DATA_DIR}" "data directory"
}

# 创建 Docker volume 持久化目录。
ensure_data_dirs() {
	ensure_dir "${DATA_DIR}" "0750" "${DATA_OWNER}" "managed"
	ensure_dir "${DATA_DIR}/inputs" "0750" "${DATA_OWNER}" "managed"
	ensure_dir "${DATA_DIR}/bundles" "0750" "${DATA_OWNER}" "managed"
	ensure_dir "${DATA_DIR}/current" "0750" "${DATA_OWNER}" "managed"
}

# 判断同名容器是否已存在。
container_exists() {
	docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1
}

# 未指定 --replace 时，在写目录或拉镜像前拒绝同名容器。
check_container_conflict_before_writes() {
	if [[ "${REPLACE_CONTAINER}" == "1" ]]; then
		return 0
	fi
	if is_dry_run; then
		log "Container conflict check skipped for dry-run"
		return 0
	fi

	if container_exists; then
		die "Container already exists: ${CONTAINER_NAME}. Use --replace to remove it."
	fi
}

# 根据参数决定是否拉取镜像。
maybe_pull_image() {
	if [[ "${PULL_IMAGE}" != "1" ]]; then
		return 0
	fi
	run docker pull "${IMAGE}"
}

# 确认镜像可用后再替换旧容器，避免拉取失败时先中断旧服务。
ensure_image_available() {
	if is_dry_run; then
		log "Image availability check skipped for dry-run"
		return 0
	fi
	if docker image inspect "${IMAGE}" >/dev/null 2>&1; then
		return 0
	fi
	die "Docker image not found locally: ${IMAGE}. Use --pull to fetch it before replacing containers."
}

# 指定 --replace 时，在镜像确认可用后替换旧容器。
replace_existing_container_after_image_ready() {
	if [[ "${REPLACE_CONTAINER}" != "1" ]]; then
		return 0
	fi
	if is_dry_run; then
		run docker rm -f "${CONTAINER_NAME}"
		return 0
	fi

	if container_exists; then
		run docker rm -f "${CONTAINER_NAME}"
	fi
}

# 使用安全默认参数启动订阅服务容器。
run_container() {
	local port_mapping="${HOST}:${PORT}:3003"

	run docker run -d \
		--name "${CONTAINER_NAME}" \
		--restart unless-stopped \
		--publish "${port_mapping}" \
		--volume "${DATA_DIR}:/data" \
		--user "${CONTAINER_USER}" \
		--read-only \
		--cap-drop ALL \
		--tmpfs /tmp:rw,noexec,nosuid,size=64m \
		"${IMAGE}" \
		proxystack-sub serve --host 0.0.0.0 --port 3003 --data-dir /data
}

# 主入口。
main() {
	parse_args "$@"
	validate_args
	require_cmd docker

	check_container_conflict_before_writes
	ensure_data_dirs
	maybe_pull_image
	ensure_image_available
	replace_existing_container_after_image_ready
	run_container
	log "Docker subscription deployment completed"
}

main "$@"
