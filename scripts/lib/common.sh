#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"

# 判断当前是否处于 dry-run 预览模式。
is_dry_run() {
	if [[ "${DRY_RUN}" == "1" ]]; then
		return 0
	fi
	return 1
}

# 输出普通日志，日志内容必须保持英文。
log() {
	printf '[INFO] %s\n' "$*" >&2
}

# 输出警告日志，日志内容必须保持英文。
warn() {
	printf '[WARN] %s\n' "$*" >&2
}

# 输出错误日志并退出，日志内容必须保持英文。
die() {
	printf '[ERROR] %s\n' "$*" >&2
	exit 1
}

# 把命令参数转为安全可读的 shell 展示形式，仅用于日志。
quote_command() {
	local quoted_args=()
	local arg
	local quoted_arg

	for arg in "$@"; do
		printf -v quoted_arg '%q' "$arg"
		quoted_args+=("$quoted_arg")
	done
	IFS=' '
	printf '%s' "${quoted_args[*]}"
}

# 通过参数数组执行命令；dry-run 时只打印命令，不执行。
run() {
	if [[ "$#" -eq 0 ]]; then
		die "run requires at least one argument"
	fi

	local command_text
	command_text="$(quote_command "$@")"
	if is_dry_run; then
		log "DRY-RUN: ${command_text}"
		return 0
	fi

	log "RUN: ${command_text}"
	"$@"
}

# 检查外部命令是否存在；dry-run 时允许缺失以便预览。
require_cmd() {
	local command_name="${1:-}"
	if [[ -z "${command_name}" ]]; then
		die "require_cmd needs a command name"
	fi
	if command -v "${command_name}" >/dev/null 2>&1; then
		return 0
	fi
	if is_dry_run; then
		warn "Command not found during dry-run: ${command_name}"
		return 0
	fi
	die "Required command not found: ${command_name}"
}

# 要求以 root 身份运行；dry-run 时跳过真实权限检查。
require_root() {
	require_cmd id
	if is_dry_run; then
		log "Root check skipped for dry-run"
		return 0
	fi
	if [[ "$(id -u)" != "0" ]]; then
		die "This script must run as root"
	fi
}

# 保护托管目录，拒绝空路径、根目录、系统目录和路径穿越。
guard_managed_path() {
	local path="${1:-}"
	local label="${2:-managed path}"
	local trimmed
	local current
	local part
	local parts=()

	if [[ -z "${path}" ]]; then
		die "${label} must not be empty"
	fi
	if [[ "${path}" != /* ]]; then
		die "${label} must be absolute: ${path}"
	fi
	case "${path}" in
		/|/.|/..|/usr|/usr/*|/etc|/etc/*|/bin|/bin/*|/sbin|/sbin/*|/lib|/lib/*|/lib64|/lib64/*|/dev|/dev/*|/proc|/proc/*|/sys|/sys/*|/run|/run/*|/var|/var/*|/tmp)
			die "${label} is not allowed as a managed path: ${path}"
			;;
	esac
	if [[ "${path}" == /tmp/* && "${DRY_RUN}" != "1" ]]; then
		die "${label} under /tmp is only allowed during dry-run: ${path}"
	fi
	if [[ "${path}" == *"/../"* || "${path}" == */.. || "${path}" == *"/./"* || "${path}" == */. ]]; then
		die "${label} must not contain dot path segments: ${path}"
	fi

	trimmed="${path#/}"
	IFS='/' read -r -a parts <<<"${trimmed}"
	current="/"
	for part in "${parts[@]}"; do
		if [[ -z "${part}" ]]; then
			continue
		fi
		if [[ "${current}" == "/" ]]; then
			current="/${part}"
		else
			current="${current}/${part}"
		fi
		if [[ -L "${current}" ]]; then
			if is_dry_run && [[ "${current}" == "/tmp" ]]; then
				continue
			fi
			die "${label} must not cross symlink path: ${current}"
		fi
	done
}

# 保护系统目标目录，允许 /usr/local/bin 这类非托管输出目录但拒绝危险根路径。
guard_system_dir() {
	local path="${1:-}"
	local label="${2:-system directory}"
	local trimmed
	local current
	local part
	local parts=()

	if [[ -z "${path}" ]]; then
		die "${label} must not be empty"
	fi
	if [[ "${path}" != /* ]]; then
		die "${label} must be absolute: ${path}"
	fi
	case "${path}" in
		/usr/local/bin|/usr/local/sbin|/opt/*)
			;;
		/tmp/*)
			if [[ "${DRY_RUN}" != "1" ]]; then
				die "${label} under /tmp is only allowed during dry-run: ${path}"
			fi
			;;
		*)
			die "${label} must be /usr/local/bin, /usr/local/sbin, /opt/*, or /tmp/* during dry-run: ${path}"
			;;
	esac
	if [[ "${path}" == *"/../"* || "${path}" == */.. || "${path}" == *"/./"* || "${path}" == */. ]]; then
		die "${label} must not contain dot path segments: ${path}"
	fi

	trimmed="${path#/}"
	IFS='/' read -r -a parts <<<"${trimmed}"
	current="/"
	for part in "${parts[@]}"; do
		if [[ -z "${part}" ]]; then
			continue
		fi
		if [[ "${current}" == "/" ]]; then
			current="/${part}"
		else
			current="${current}/${part}"
		fi
		if [[ -L "${current}" ]]; then
			if is_dry_run && [[ "${current}" == "/tmp" ]]; then
				continue
			fi
			die "${label} must not cross symlink path: ${current}"
		fi
	done
}

# 创建目录并设置权限和 owner；scope 为 managed 时启用托管路径保护。
ensure_dir() {
	local path="${1:-}"
	local mode="${2:-0750}"
	local owner_group="${3:-}"
	local scope="${4:-managed}"

	if [[ "${scope}" == "managed" ]]; then
		guard_managed_path "${path}" "managed directory"
	elif [[ "${scope}" == "system" ]]; then
		guard_system_dir "${path}" "system directory"
	elif [[ "${scope}" != "none" ]]; then
		die "Unknown directory guard scope: ${scope}"
	fi

	require_cmd install
	run install -d -m "${mode}" "${path}"
	if [[ -n "${owner_group}" ]]; then
		require_cmd chown
		run chown "${owner_group}" "${path}"
	fi
}

# 以指定用户执行命令；优先使用 runuser，必要时使用 sudo。
run_as_user() {
	local target_user="${1:-}"
	shift || die "run_as_user needs a user and a command"
	if [[ "$#" -eq 0 ]]; then
		die "run_as_user needs a command"
	fi
	if [[ -z "${target_user}" ]]; then
		run "$@"
		return 0
	fi
	if ! is_dry_run && [[ "$(id -un)" == "${target_user}" ]]; then
		run "$@"
		return 0
	fi
	if command -v runuser >/dev/null 2>&1; then
		run runuser -u "${target_user}" -- "$@"
		return 0
	fi
	if command -v sudo >/dev/null 2>&1; then
		run sudo -u "${target_user}" -- "$@"
		return 0
	fi
	if is_dry_run; then
		run runuser -u "${target_user}" -- "$@"
		return 0
	fi
	die "Required command not found: runuser or sudo"
}

# 创建 Python venv；已存在 pyvenv.cfg 时保持不动。
ensure_venv() {
	local venv_dir="${1:-}"
	local python_bin="${2:-python3}"
	local owner_user="${3:-}"

	guard_managed_path "${venv_dir}" "venv directory"
	require_cmd "${python_bin}"
	if [[ -f "${venv_dir}/pyvenv.cfg" ]]; then
		log "Python venv already exists: ${venv_dir}"
		return 0
	fi
	run_as_user "${owner_user}" "${python_bin}" -m venv "${venv_dir}"
}
