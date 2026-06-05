#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

WHEEL=""
SOURCE_DIR=""
PACKAGE_SPEC=""
BASE_DIR="/opt/proxystack"
IMPORT_BUNDLE=""
INSTALL_SYSTEMD="0"
START_SERVICE="0"
INSTALL_USER="proxystack"
INSTALL_GROUP="proxystack"
PYTHON_BIN="python3"
INSTALL_DEPS="0"

# 展示 install-sub-local 用法。
usage() {
	cat <<'EOF'
Usage: scripts/install-sub-local.sh [options]

Install proxystack-sub for a local non-Docker deployment. The script creates
the venv and subscription data directories, optionally imports a bundle, and
optionally installs or starts proxystack-sub.service.

Install source, choose exactly one:
  --wheel FILE             Install from a wheel file.
  --source DIR             Install from a local source directory.
  --package SPEC           Install from a pip package spec.

Options:
  --base-dir DIR           Managed base directory. Default: /opt/proxystack
  --import-bundle FILE     Import a sub-bundle.zip after installation.
  --python CMD             Python command used to create the venv. Default: python3
  --user USER              System user. Default: proxystack
  --group GROUP            System group. Default: proxystack
  --install-systemd        Run proxystack-agent service install sub.
  --start                  Run proxystack-agent service start sub.
  --install-deps           Install missing native dependencies when supported.
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
			--wheel)
				WHEEL="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--wheel=*)
				WHEEL="${1#*=}"
				shift
				;;
			--source)
				SOURCE_DIR="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--source=*)
				SOURCE_DIR="${1#*=}"
				shift
				;;
			--package)
				PACKAGE_SPEC="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--package=*)
				PACKAGE_SPEC="${1#*=}"
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
			--install-deps)
				INSTALL_DEPS="1"
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
	local install_sources=0

	[[ -n "${WHEEL}" ]] && ((install_sources += 1))
	[[ -n "${SOURCE_DIR}" ]] && ((install_sources += 1))
	[[ -n "${PACKAGE_SPEC}" ]] && ((install_sources += 1))
	if [[ "${install_sources}" -ne 1 ]]; then
		die "Choose exactly one of --wheel, --source, or --package"
	fi
	guard_managed_path "${BASE_DIR}" "base directory"
	validate_install_identity "${INSTALL_USER}" "${INSTALL_GROUP}" "${BASE_DIR}" "/usr/sbin/nologin"
	if [[ -n "${PACKAGE_SPEC}" && "${PACKAGE_SPEC}" == -* ]]; then
		die "Package spec must not start with '-'"
	fi
	if [[ -n "${WHEEL}" && ! -f "${WHEEL}" && "${DRY_RUN}" != "1" ]]; then
		die "Wheel file does not exist: ${WHEEL}"
	fi
	if [[ -n "${SOURCE_DIR}" && ! -d "${SOURCE_DIR}" && "${DRY_RUN}" != "1" ]]; then
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
	ensure_dir "${data_dir}/bundles" "0750" "${owner_group}" "managed"
	ensure_dir "${data_dir}/current" "0750" "${owner_group}" "managed"
}

# 在 venv 中安装 proxystack Python 包。
install_python_package() {
	local venv_python="${BASE_DIR}/.venv/bin/python"

	pip_install_with_fallback "${INSTALL_USER}" "${venv_python}" --upgrade pip
	if [[ -n "${WHEEL}" ]]; then
		pip_install_with_fallback "${INSTALL_USER}" "${venv_python}" "${WHEEL}"
	elif [[ -n "${SOURCE_DIR}" ]]; then
		pip_install_with_fallback "${INSTALL_USER}" "${venv_python}" "${SOURCE_DIR}"
	else
		pip_install_with_fallback "${INSTALL_USER}" "${venv_python}" "${PACKAGE_SPEC}"
	fi
}

# 创建默认 config.yaml，已存在时保持不动。
ensure_config() {
	local config_path="${BASE_DIR}/config.yaml"

	if [[ -f "${config_path}" ]]; then
		log "Config already exists: ${config_path}"
		return 0
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
	validate_args
	require_root
	ensure_python_venv_available "${PYTHON_BIN}" "${INSTALL_DEPS}"

	ensure_group
	ensure_user
	ensure_sub_dirs
	ensure_venv "${BASE_DIR}/.venv" "${PYTHON_BIN}" "${INSTALL_USER}"
	install_python_package
	ensure_config
	maybe_import_bundle
	maybe_install_systemd
	maybe_start_service
	log "Local subscription installation completed"
}

main "$@"
