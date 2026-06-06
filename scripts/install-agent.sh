#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR="${PROJECT_ROOT}"
BASE_DIR="/opt/proxystack"
BIN_DIR="/usr/local/bin"
PYTHON_BIN="python3"
INSTALL_USER="proxystack"
INSTALL_GROUP="proxystack"
RUN_INIT="1"
INSTALL_SYSTEMD="0"

# 展示 install-agent 用法。
usage() {
	cat <<'EOF'
Usage: scripts/install-agent.sh [options]

Install proxystack-agent into a local Python venv. The script bootstraps users,
directories, venv, package installation, console-script links, and optionally
systemd unit files. It does not install mihomo, xray-core, or geo data.

Options:
  --source DIR             Install from a local source directory. Default: repository root
  --base-dir DIR           Managed base directory. Default: /opt/proxystack
  --bin-dir DIR            Console-script symlink directory. Default: /usr/local/bin
  --python CMD             Python command used to create the venv. Default: python3
  --user USER              System user. Default: proxystack
  --group GROUP            System group. Default: proxystack
  --no-init                Do not run proxystack-agent init.
  --install-systemd        Run proxystack-agent service install.
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
			--source)
				SOURCE_DIR="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--source=*)
				SOURCE_DIR="${1#*=}"
				shift
				;;
			--base-dir)
				BASE_DIR="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--base-dir=*)
				BASE_DIR="${1#*=}"
				shift
				;;
			--bin-dir)
				BIN_DIR="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--bin-dir=*)
				BIN_DIR="${1#*=}"
				shift
				;;
			--python)
				PYTHON_BIN="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--python=*)
				PYTHON_BIN="${1#*=}"
				shift
				;;
			--user)
				INSTALL_USER="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--user=*)
				INSTALL_USER="${1#*=}"
				shift
				;;
			--group)
				INSTALL_GROUP="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--group=*)
				INSTALL_GROUP="${1#*=}"
				shift
				;;
			--no-init)
				RUN_INIT="0"
				shift
				;;
			--install-systemd)
				INSTALL_SYSTEMD="1"
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

# 校验安装来源和关键路径。
validate_args() {
	guard_managed_path "${BASE_DIR}" "base directory"
	guard_system_dir "${BIN_DIR}" "bin directory"
	validate_install_identity "${INSTALL_USER}" "${INSTALL_GROUP}" "${BASE_DIR}" "/usr/sbin/nologin"
	if [[ ! -d "${SOURCE_DIR}" && "${DRY_RUN}" != "1" ]]; then
		die "Source directory does not exist: ${SOURCE_DIR}"
	fi
}

# 创建系统组，已存在时保持不动。
ensure_group() {
	require_cmd getent
	if getent group "${INSTALL_GROUP}" >/dev/null 2>&1; then
		log "SKIP: group already exists: ${INSTALL_GROUP}"
		return 0
	fi
	require_cmd groupadd
	run groupadd --system "${INSTALL_GROUP}"
}

# 创建系统用户，已存在时保持不动。
ensure_user() {
	require_cmd id
	if id -u "${INSTALL_USER}" >/dev/null 2>&1; then
		log "SKIP: user already exists: ${INSTALL_USER}"
		return 0
	fi
	require_cmd useradd
	run useradd --system --home "${BASE_DIR}" --shell /usr/sbin/nologin --gid "${INSTALL_GROUP}" "${INSTALL_USER}"
}

# 创建 agent 需要的托管目录。
ensure_agent_dirs() {
	local owner_group="${INSTALL_USER}:${INSTALL_GROUP}"

	ensure_dir "${BASE_DIR}" "0750" "${owner_group}" "managed"
	ensure_dir "${BASE_DIR}/bin" "0750" "${owner_group}" "managed"
	ensure_dir "${BASE_DIR}/geo" "0750" "${owner_group}" "managed"
	ensure_dir "${BASE_DIR}/downloads" "0750" "${owner_group}" "managed"
	ensure_dir "${BASE_DIR}/runtime" "0750" "${owner_group}" "managed"
	ensure_dir "${BASE_DIR}/publish" "0750" "${owner_group}" "managed"
	ensure_dir "${BASE_DIR}/stacks" "0750" "${owner_group}" "managed"
}

# 在 venv 中安装 proxystack Python 包。
install_python_package() {
	local venv_python="${BASE_DIR}/.venv/bin/python"
	local stamp_path="${BASE_DIR}/runtime/source.sha256"
	local source_fingerprint=""
	local staged_source

	if is_dry_run; then
		log "Python package idempotency check skipped for dry-run"
	else
		source_fingerprint="$(source_tree_fingerprint "${SOURCE_DIR}")"
		if python_package_current \
			"${stamp_path}" \
			"${source_fingerprint}" \
			"${BASE_DIR}/.venv/bin/proxystack-agent" \
			"${BASE_DIR}/.venv/bin/proxystack-sub" \
			"${BASE_DIR}/.venv/bin/ps-agent" \
			"${BASE_DIR}/.venv/bin/ps-sub"; then
			log "SKIP: Python package already up to date"
			return 0
		fi
	fi

	staged_source="$(stage_python_source "${SOURCE_DIR}" "${BASE_DIR}/runtime/source" "${INSTALL_USER}:${INSTALL_GROUP}")"
	ensure_pip_available "${INSTALL_USER}" "${venv_python}"
	pip_install_with_fallback "${INSTALL_USER}" "${venv_python}" "${staged_source}"
	if [[ -n "${source_fingerprint}" ]]; then
		write_python_package_stamp "${stamp_path}" "${source_fingerprint}" "${INSTALL_USER}:${INSTALL_GROUP}"
	fi
}

# 链接 console scripts 到系统 bin 目录。
link_console_scripts() {
	ensure_dir "${BIN_DIR}" "0755" "" "system"
	ensure_symlink "${BASE_DIR}/.venv/bin/proxystack-agent" "${BIN_DIR}/proxystack-agent" "system"
	ensure_symlink "${BASE_DIR}/.venv/bin/proxystack-sub" "${BIN_DIR}/proxystack-sub" "system"
	ensure_symlink "${BASE_DIR}/.venv/bin/ps-agent" "${BIN_DIR}/ps-agent" "system"
	ensure_symlink "${BASE_DIR}/.venv/bin/ps-sub" "${BIN_DIR}/ps-sub" "system"
}

# 根据参数决定是否初始化 config.yaml。
maybe_init_project() {
	if [[ "${RUN_INIT}" != "1" ]]; then
		log "SKIP: project init disabled"
		return 0
	fi
	if ! is_dry_run && [[ -f "${BASE_DIR}/config.yaml" ]]; then
		log "SKIP: config already exists: ${BASE_DIR}/config.yaml"
		return 0
	fi
	run_as_user "${INSTALL_USER}" "${BASE_DIR}/.venv/bin/proxystack-agent" init --config "${BASE_DIR}/config.yaml" --base-dir "${BASE_DIR}"
}

# 根据参数决定是否安装 systemd unit。
maybe_install_systemd() {
	if [[ "${INSTALL_SYSTEMD}" != "1" ]]; then
		return 0
	fi
	if systemd_units_installed; then
		log "SKIP: systemd units already installed"
		return 0
	fi
	run "${BASE_DIR}/.venv/bin/proxystack-agent" service install --config "${BASE_DIR}/config.yaml"
}

# 判断 agent 需要的 systemd unit 是否已经全部安装。
systemd_units_installed() {
	if is_dry_run; then
		return 1
	fi
	[[ -f /etc/systemd/system/proxystack-xray@.service ]] &&
		[[ -f /etc/systemd/system/proxystack-clash@.service ]] &&
		[[ -f /etc/systemd/system/proxystack-sub.service ]]
}

# 主入口。
main() {
	parse_args "$@"
	validate_args
	require_root
	require_cmd ln
	ensure_python_venv_available "${PYTHON_BIN}"

	ensure_group
	ensure_user
	ensure_agent_dirs
	ensure_venv "${BASE_DIR}/.venv" "${PYTHON_BIN}" "${INSTALL_USER}"
	install_python_package
	link_console_scripts
	maybe_init_project
	maybe_install_systemd
	log "Agent installation completed"
}

main "$@"
