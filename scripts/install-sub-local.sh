#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR="${PROJECT_ROOT}"
BASE_DIR="/opt/proxystack"
BIN_DIR="/usr/local/bin"
IMPORT_BUNDLE=""
INSTALL_SYSTEMD="0"
START_SERVICE="0"
INSTALL_USER="proxystack"
INSTALL_GROUP="proxystack"
PYTHON_BIN="python3"

# 展示 install-sub-local 用法。
usage() {
	cat <<'EOF'
Usage: scripts/install-sub-local.sh [options]

Install proxystack-sub for a local non-Docker deployment. The script creates
the venv and subscription data directories, optionally imports a bundle, and
optionally installs or starts proxystack-sub.service.

Options:
  --source DIR             Install from a local source directory. Default: repository root
  --base-dir DIR           Managed base directory. Default: /opt/proxystack
  --bin-dir DIR            Console-script symlink directory. Default: /usr/local/bin
  --import-bundle FILE     Import a sub-bundle.zip after installation.
  --python CMD             Python command used to create the venv. Default: python3
  --user USER              System user. Default: proxystack
  --group GROUP            System group. Default: proxystack
  --install-systemd        Run proxystack-agent service install sub.
  --start                  Run proxystack-agent service start sub.
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
			--import-bundle)
				IMPORT_BUNDLE="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--import-bundle=*)
				IMPORT_BUNDLE="${1#*=}"
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
			--install-systemd)
				INSTALL_SYSTEMD="1"
				shift
				;;
			--start)
				START_SERVICE="1"
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

# 校验安装来源、路径和发布包输入。
validate_args() {
	guard_managed_path "${BASE_DIR}" "base directory"
	guard_system_dir "${BIN_DIR}" "bin directory"
	validate_install_identity "${INSTALL_USER}" "${INSTALL_GROUP}" "${BASE_DIR}" "/usr/sbin/nologin"
	if [[ ! -d "${SOURCE_DIR}" && "${DRY_RUN}" != "1" ]]; then
		die "Source directory does not exist: ${SOURCE_DIR}"
	fi
	if [[ -n "${IMPORT_BUNDLE}" && ! -f "${IMPORT_BUNDLE}" && "${DRY_RUN}" != "1" ]]; then
		die "Import bundle does not exist: ${IMPORT_BUNDLE}"
	fi
}

# 创建系统组，已存在时保持不动。
ensure_group() {
	require_cmd getent
	if getent group "${INSTALL_GROUP}" >/dev/null 2>&1; then
		log "Group already exists: ${INSTALL_GROUP}"
		return 0
	fi
	require_cmd groupadd
	run groupadd --system "${INSTALL_GROUP}"
}

# 创建系统用户，已存在时保持不动。
ensure_user() {
	require_cmd id
	if id -u "${INSTALL_USER}" >/dev/null 2>&1; then
		log "User already exists: ${INSTALL_USER}"
		return 0
	fi
	require_cmd useradd
	run useradd --system --home "${BASE_DIR}" --shell /usr/sbin/nologin --gid "${INSTALL_GROUP}" "${INSTALL_USER}"
}

# 创建订阅服务本地部署需要的托管目录。
ensure_sub_dirs() {
	local owner_group="${INSTALL_USER}:${INSTALL_GROUP}"
	local data_dir="${BASE_DIR}/sub"

	ensure_dir "${BASE_DIR}" "0750" "${owner_group}" "managed"
	ensure_dir "${data_dir}" "0750" "${owner_group}" "managed"
	ensure_dir "${data_dir}/inputs" "0750" "${owner_group}" "managed"
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
			log "Python package already up to date; skipping pip install"
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
	run ln -sf "${BASE_DIR}/.venv/bin/proxystack-agent" "${BIN_DIR}/proxystack-agent"
	run ln -sf "${BASE_DIR}/.venv/bin/proxystack-sub" "${BIN_DIR}/proxystack-sub"
	run ln -sf "${BASE_DIR}/.venv/bin/ps-agent" "${BIN_DIR}/ps-agent"
	run ln -sf "${BASE_DIR}/.venv/bin/ps-sub" "${BIN_DIR}/ps-sub"
}

# 创建默认 config.yaml，已存在时保持不动。
ensure_config() {
	local config_path="${BASE_DIR}/config.yaml"

	if [[ -f "${config_path}" ]]; then
		log "Config already exists: ${config_path}"
	fi
	run_as_user "${INSTALL_USER}" "${BASE_DIR}/.venv/bin/proxystack-agent" init --config "${config_path}" --base-dir "${BASE_DIR}"
}

# 根据参数决定是否导入订阅发布包。
maybe_import_bundle() {
	if [[ -z "${IMPORT_BUNDLE}" ]]; then
		return 0
	fi
	run_as_user "${INSTALL_USER}" "${BASE_DIR}/.venv/bin/proxystack-sub" import "${IMPORT_BUNDLE}" --data-dir "${BASE_DIR}/sub"
}

# 根据参数决定是否安装 systemd unit。
maybe_install_systemd() {
	if [[ "${INSTALL_SYSTEMD}" != "1" ]]; then
		return 0
	fi
	run "${BASE_DIR}/.venv/bin/proxystack-agent" service install sub --config "${BASE_DIR}/config.yaml"
}

# 根据参数决定是否启动订阅服务。
maybe_start_service() {
	if [[ "${START_SERVICE}" != "1" ]]; then
		return 0
	fi
	run "${BASE_DIR}/.venv/bin/proxystack-agent" service start sub --config "${BASE_DIR}/config.yaml"
}

# 主入口。
main() {
	parse_args "$@"
	step "validate arguments" validate_args
	step "check root permission" require_root
	step "check link command" require_cmd ln
	step "check Python venv support" ensure_python_venv_available "${PYTHON_BIN}"

	step "prepare system group" ensure_group
	step "prepare system user" ensure_user
	step "prepare subscription directories" ensure_sub_dirs
	step "prepare Python venv" ensure_venv "${BASE_DIR}/.venv" "${PYTHON_BIN}" "${INSTALL_USER}"
	step "install Python package" install_python_package
	step "link console scripts" link_console_scripts
	step "ensure agent config" ensure_config
	step "handle optional subscription bundle import" maybe_import_bundle
	step "handle optional systemd unit installation" maybe_install_systemd
	step "handle optional subscription service start" maybe_start_service
}

main "$@"
