#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

TARGET="all"
BASE_DIR="/opt/proxystack"
BIN_DIR="/usr/local/bin"
INSTALL_USER="proxystack"
INSTALL_GROUP="proxystack"
PURGE_DATA="0"
REMOVE_USER="0"
REMOVE_BIN="0"

# 展示 uninstall-local 用法。
usage() {
	cat <<'EOF'
Usage: scripts/uninstall-local.sh [options]

Uninstall local proxystack systemd units safely. By default the script stops
and disables services, removes unit files, and keeps data, users, and CLI links.

Options:
  --target TARGET          all, agent, or sub. Default: all
  --base-dir DIR           Managed base directory. Default: /opt/proxystack
  --bin-dir DIR            Console-script symlink directory. Default: /usr/local/bin
  --user USER              System user. Default: proxystack
  --group GROUP            System group. Default: proxystack
  --remove-bin             Remove CLI symlinks that point into the managed venv.
  --purge-data             Remove base directory. Only allowed with --target all.
  --remove-user            Remove system user and group. Only allowed with --target all.
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
			--target)
				TARGET="$(read_arg "$1" "${2:-}")"
				shift 2
				;;
			--target=*)
				TARGET="${1#*=}"
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
			--remove-bin)
				REMOVE_BIN="1"
				shift
				;;
			--purge-data)
				PURGE_DATA="1"
				shift
				;;
			--remove-user)
				REMOVE_USER="1"
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

# 校验目标和危险清理参数。
validate_args() {
	case "${TARGET}" in
		all|agent|sub)
			;;
		*)
			die "Target must be one of: all, agent, sub"
			;;
	esac
	guard_managed_path "${BASE_DIR}" "base directory"
	guard_system_dir "${BIN_DIR}" "bin directory"
	if [[ "${PURGE_DATA}" == "1" && "${TARGET}" != "all" ]]; then
		die "--purge-data is only allowed with --target all"
	fi
	if [[ "${REMOVE_USER}" == "1" && "${TARGET}" != "all" ]]; then
		die "--remove-user is only allowed with --target all"
	fi
	validate_install_identity "${INSTALL_USER}" "${INSTALL_GROUP}" "${BASE_DIR}" "/usr/sbin/nologin"
}

# 输出当前 target 对应的 systemd 实例匹配模式。
service_patterns_for_target() {
	case "${TARGET}" in
		all)
			printf '%s\n' "proxystack-xray@*.service" "proxystack-clash@*.service" "proxystack-sub.service"
			;;
		agent)
			printf '%s\n' "proxystack-xray@*.service" "proxystack-clash@*.service"
			;;
		sub)
			printf '%s\n' "proxystack-sub.service"
			;;
	esac
}

# 输出当前 target 对应的模板 unit 文件。
unit_paths_for_target() {
	case "${TARGET}" in
		all)
			printf '%s\n' \
				"/etc/systemd/system/proxystack-xray@.service" \
				"/etc/systemd/system/proxystack-clash@.service" \
				"/etc/systemd/system/proxystack-sub.service"
			;;
		agent)
			printf '%s\n' \
				"/etc/systemd/system/proxystack-xray@.service" \
				"/etc/systemd/system/proxystack-clash@.service"
			;;
		sub)
			printf '%s\n' "/etc/systemd/system/proxystack-sub.service"
			;;
	esac
}

# 输出当前 target 对应的 CLI 命令名。
bin_names_for_target() {
	case "${TARGET}" in
		all)
			printf '%s\n' "proxystack-agent" "proxystack-sub" "ps-agent" "ps-sub"
			;;
		agent)
			printf '%s\n' "proxystack-agent" "ps-agent"
			;;
		sub)
			printf '%s\n' "proxystack-sub" "ps-sub"
			;;
	esac
}

# 按 systemctl 模式列出已加载或已知 unit 名称。
list_systemd_units() {
	local pattern

	for pattern in "$@"; do
		{ systemctl list-units --all --full --plain --no-legend "${pattern}" 2>/dev/null || true; } | awk '$1 !~ /@\.service$/ {print $1}'
		{ systemctl list-unit-files --full --plain --no-legend "${pattern}" 2>/dev/null || true; } | awk '$1 !~ /@\.service$/ {print $1}'
	done | awk 'NF && !seen[$0]++'
}

# 停止和禁用目标服务，未发现实例时保持幂等。
stop_and_disable_services() {
	local patterns=()
	local units=()
	local item

	while IFS= read -r item; do
		patterns+=("${item}")
	done < <(service_patterns_for_target)
	if is_dry_run; then
		run systemctl stop "${patterns[@]}"
		run systemctl disable "${patterns[@]}"
		return 0
	fi

	while IFS= read -r item; do
		units+=("${item}")
	done < <(list_systemd_units "${patterns[@]}")
	if [[ "${#units[@]}" -eq 0 ]]; then
		log "No matching systemd units found"
		return 0
	fi
	run systemctl stop "${units[@]}"
	run systemctl disable "${units[@]}"
}

# 删除模板 unit 文件并刷新 systemd。
remove_unit_files() {
	local unit_path

	while IFS= read -r unit_path; do
		if [[ -z "${unit_path}" ]]; then
			continue
		fi
		if [[ -e "${unit_path}" || -L "${unit_path}" ]] || is_dry_run; then
			run rm -f "${unit_path}"
		else
			log "Unit file already absent: ${unit_path}"
		fi
	done < <(unit_paths_for_target)
	run systemctl daemon-reload
}

# 删除指向托管 venv 的 CLI symlink，避免误删用户自己的同名文件。
remove_bin_links() {
	local bin_name
	local bin_path
	local link_target

	if [[ "${REMOVE_BIN}" != "1" ]]; then
		log "CLI link removal skipped"
		return 0
	fi
	while IFS= read -r bin_name; do
		if [[ -z "${bin_name}" ]]; then
			continue
		fi
		bin_path="${BIN_DIR}/${bin_name}"
		if is_dry_run; then
			run rm -f "${bin_path}"
			continue
		fi
		if [[ ! -e "${bin_path}" && ! -L "${bin_path}" ]]; then
			log "CLI link already absent: ${bin_path}"
			continue
		fi
		if [[ ! -L "${bin_path}" ]]; then
			warn "Skipping non-symlink CLI path: ${bin_path}"
			continue
		fi
		link_target="$(readlink "${bin_path}")"
		case "${link_target}" in
			"${BASE_DIR}/.venv/bin/"*)
				run rm -f "${bin_path}"
				;;
			*)
				warn "Skipping unmanaged CLI symlink: ${bin_path} -> ${link_target}"
				;;
		esac
	done < <(bin_names_for_target)
}

# 按显式参数删除托管数据目录。
maybe_purge_data() {
	if [[ "${PURGE_DATA}" != "1" ]]; then
		log "Data purge skipped"
		return 0
	fi
	run rm -rf "${BASE_DIR}"
}

# 按显式参数删除系统用户和组。
maybe_remove_user() {
	if [[ "${REMOVE_USER}" != "1" ]]; then
		log "User removal skipped"
		return 0
	fi
	require_cmd id
	require_cmd getent
	require_cmd userdel
	require_cmd groupdel
	if id -u "${INSTALL_USER}" >/dev/null 2>&1 || is_dry_run; then
		run userdel "${INSTALL_USER}"
	else
		log "User already absent: ${INSTALL_USER}"
	fi
	if getent group "${INSTALL_GROUP}" >/dev/null 2>&1 || is_dry_run; then
		run groupdel "${INSTALL_GROUP}"
	else
		log "Group already absent: ${INSTALL_GROUP}"
	fi
}

# 主入口。
main() {
	parse_args "$@"
	step "validate arguments" validate_args
	step "check root permission" require_root
	step "check systemctl command" require_cmd systemctl
	step "check remove command" require_cmd rm

	step "stop and disable services" stop_and_disable_services
	step "remove systemd units" remove_unit_files
	step "handle optional console link removal" remove_bin_links
	step "handle optional data purge" maybe_purge_data
	step "handle optional system user removal" maybe_remove_user
}

main "$@"
