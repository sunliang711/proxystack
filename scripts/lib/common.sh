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
	local IFS=' '
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

# 探测指定 Python 是否能真实创建 venv，覆盖 Debian 缺少 ensurepip 的场景。
python_venv_probe() {
	local python_bin="${1:-python3}"
	local temp_dir

	require_cmd mktemp
	temp_dir="$(mktemp -d)"
	if "${python_bin}" -m venv "${temp_dir}/venv" >/dev/null 2>&1; then
		rm -rf "${temp_dir}"
		return 0
	fi
	rm -rf "${temp_dir}"
	return 1
}

# 根据当前 Python 主次版本推导 Debian/Ubuntu venv 包名。
python_venv_package_name() {
	local python_bin="${1:-python3}"
	local package_name

	if package_name="$("${python_bin}" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")' 2>/dev/null)"; then
		printf '%s' "${package_name}"
		return 0
	fi
	printf '%s' "python3-venv"
}

# 使用系统包管理器安装原生部署依赖，目前支持 Debian/Ubuntu。
install_os_packages() {
	local packages=("$@")
	local os_id=""
	local os_like=""
	local os_release_path="${OS_RELEASE_PATH:-/etc/os-release}"

	if [[ "${#packages[@]}" -eq 0 ]]; then
		die "install_os_packages requires at least one package"
	fi
	if [[ -r "${os_release_path}" ]]; then
		# shellcheck source=/etc/os-release
		source "${os_release_path}"
		os_id="${ID:-}"
		os_like="${ID_LIKE:-}"
	fi
	case " ${os_id} ${os_like} " in
		*" debian "*|*" ubuntu "*)
			require_cmd apt-get
			run env DEBIAN_FRONTEND=noninteractive apt-get update
			run env DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
			;;
		*)
			die "Unsupported OS for automatic dependency installation; install manually: ${packages[*]}"
			;;
	esac
}

# 预检查 Python venv 依赖；缺失时自动安装当前系统可识别的 venv 包。
ensure_python_venv_available() {
	local python_bin="${1:-python3}"
	local package_name

	require_cmd "${python_bin}"
	if is_dry_run; then
		log "Python venv dependency check skipped for dry-run"
		return 0
	fi
	if python_venv_probe "${python_bin}"; then
		return 0
	fi
	package_name="$(python_venv_package_name "${python_bin}")"
	warn "Python venv support is unavailable for ${python_bin}; trying to install ${package_name}"
	install_os_packages "${package_name}"
	if python_venv_probe "${python_bin}"; then
		return 0
	fi
	die "Python venv support is still unavailable after installing ${package_name}"
}

# 保护托管目录，只允许生产专用目录和 dry-run 明确前缀。
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
		/opt/proxystack|/opt/proxystack/*)
			;;
		/tmp/proxystack-*)
			if [[ "${DRY_RUN}" != "1" ]]; then
				die "${label} under /tmp/proxystack-* is only allowed during dry-run: ${path}"
			fi
			;;
		*)
			die "${label} is not allowed as a managed path: ${path}"
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

# 校验安装身份，避免 root 或属性不匹配的已有用户接管托管目录。
validate_install_identity() {
	local install_user="${1:-}"
	local install_group="${2:-}"
	local home_dir="${3:-}"
	local expected_shell="${4:-/usr/sbin/nologin}"
	local passwd_entry
	local group_entry
	local user_uid
	local user_gid
	local user_home
	local user_shell
	local group_gid
	local passwd_fields=()
	local group_fields=()
	local IFS=':'

	if [[ -z "${install_user}" ]]; then
		die "Install user must not be empty"
	fi
	if [[ -z "${install_group}" ]]; then
		die "Install group must not be empty"
	fi
	if [[ "${install_user}" == -* ]]; then
		die "Install user must not start with '-': ${install_user}"
	fi
	if [[ "${install_group}" == -* ]]; then
		die "Install group must not start with '-': ${install_group}"
	fi
	if [[ "${install_user}" == *:* ]]; then
		die "Install user must not contain ':': ${install_user}"
	fi
	if [[ "${install_group}" == *:* ]]; then
		die "Install group must not contain ':': ${install_group}"
	fi
	if [[ ! "${install_user}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]]; then
		die "Install user has invalid characters: ${install_user}"
	fi
	if [[ ! "${install_group}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]]; then
		die "Install group has invalid characters: ${install_group}"
	fi
	if [[ "${install_user}" == "root" ]]; then
		die "Install user must not be root"
	fi
	if [[ "${install_group}" == "root" ]]; then
		die "Install group must not be root"
	fi
	if is_dry_run; then
		log "Install identity validation skipped for dry-run: ${install_user}:${install_group}"
		return 0
	fi

	require_cmd getent
	if group_entry="$(getent group "${install_group}")"; then
		read -r -a group_fields <<<"${group_entry}"
		group_gid="${group_fields[2]:-}"
		if [[ "${group_gid}" == "0" ]]; then
			die "Install group GID must not be 0: ${install_group}"
		fi
	else
		group_gid=""
	fi

	if ! passwd_entry="$(getent passwd "${install_user}")"; then
		return 0
	fi
	read -r -a passwd_fields <<<"${passwd_entry}"
	user_uid="${passwd_fields[2]:-}"
	user_gid="${passwd_fields[3]:-}"
	user_home="${passwd_fields[5]:-}"
	user_shell="${passwd_fields[6]:-}"
	if [[ "${user_uid}" == "0" ]]; then
		die "Install user UID must not be 0: ${install_user}"
	fi
	if [[ -z "${group_gid}" ]]; then
		die "Install group does not exist for existing user ${install_user}: ${install_group}"
	fi
	if [[ "${user_gid}" != "${group_gid}" ]]; then
		die "Existing user primary group mismatch: ${install_user}"
	fi
	if [[ "${user_home}" != "${home_dir}" ]]; then
		die "Existing user home mismatch: ${install_user}"
	fi
	if [[ "${user_shell}" != "${expected_shell}" ]]; then
		die "Existing user shell mismatch: ${install_user}"
	fi
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

# 输出 pip index 候选源，优先使用用户显式配置。
pip_index_candidates() {
	local indexes=()
	local seen=" "
	local index_url

	if [[ -n "${PIP_INDEX_URL:-}" ]]; then
		indexes+=("${PIP_INDEX_URL}")
	fi
	if [[ -n "${PIP_INDEX_URLS:-}" ]]; then
		for index_url in ${PIP_INDEX_URLS}; do
			indexes+=("${index_url}")
		done
	else
		indexes+=("https://pypi.org/simple")
		indexes+=("https://pypi.tuna.tsinghua.edu.cn/simple")
		indexes+=("https://mirrors.aliyun.com/pypi/simple")
		indexes+=("https://mirrors.ustc.edu.cn/pypi/simple")
	fi

	for index_url in "${indexes[@]}"; do
		if [[ -z "${index_url}" || "${seen}" == *" ${index_url} "* ]]; then
			continue
		fi
		seen="${seen}${index_url} "
		printf '%s\n' "${index_url}"
	done
}

# 通过多个 pip index 依次尝试安装 Python 包。
pip_install_with_fallback() {
	local target_user="${1:-}"
	local python_bin="${2:-}"
	local index_url

	shift 2 || die "pip_install_with_fallback needs a user, python and pip args"
	if [[ -z "${python_bin}" ]]; then
		die "pip_install_with_fallback needs a python binary"
	fi
	if [[ "$#" -eq 0 ]]; then
		die "pip_install_with_fallback needs pip install arguments"
	fi

	while IFS= read -r index_url; do
		log "Trying pip index: ${index_url}"
		if run_as_user "${target_user}" "${python_bin}" -m pip install --index-url "${index_url}" "$@"; then
			return 0
		fi
		warn "Pip install failed with index: ${index_url}"
	done < <(pip_index_candidates)
	die "Pip install failed with all configured indexes"
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
