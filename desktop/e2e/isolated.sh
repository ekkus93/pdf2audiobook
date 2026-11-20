#!/usr/bin/env bash
# Give the native chooser, app and screenshots their own D-Bus session and X display.
set -euo pipefail

e2e_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [[ ${1:-} != --inside ]]; then
  e2e_session_root=$(mktemp -d -t pdf2audiobook-e2e-session.XXXXXX)
  cleanup_session() {
    local e2e_status=$?
    # D-Bus helpers may briefly hold their own runtime mount while shutting down.
    for _ in {1..40}; do
      if rm -rf -- "$e2e_session_root" 2>/dev/null; then
        return "$e2e_status"
      fi
      sleep 0.1
    done
    echo "Could not clean the native test session: $e2e_session_root" >&2
    return 1
  }
  trap cleanup_session EXIT
  export XDG_CONFIG_HOME="$e2e_session_root/config"
  export XDG_DATA_HOME="$e2e_session_root/data"
  export XDG_RUNTIME_DIR="$e2e_session_root/runtime"
  export TMPDIR="$e2e_session_root/tmp"
  mkdir -p "$XDG_CONFIG_HOME/xdg-desktop-portal" "$XDG_DATA_HOME" "$XDG_RUNTIME_DIR" "$TMPDIR"
  chmod 700 "$XDG_RUNTIME_DIR"
  cat > "$XDG_CONFIG_HOME/xdg-desktop-portal/portals.conf" <<'CONF'
[preferred]
default=gtk
org.freedesktop.impl.portal.FileChooser=gtk
CONF
  unset WAYLAND_DISPLAY
  export GDK_BACKEND=x11 XDG_CURRENT_DESKTOP=XFCE GIO_USE_VFS=local GVFS_DISABLE_FUSE=1
  dbus-run-session -- xvfb-run --auto-servernum --server-args="-screen 0 1280x900x24" \
    bash "$e2e_script_dir/isolated.sh" --inside
  exit "$?"
fi

for e2e_portal in /usr/libexec/xdg-desktop-portal-gtk /usr/libexec/xdg-desktop-portal; do
  if [[ ! -x $e2e_portal ]]; then
    echo "Install xdg-desktop-portal and xdg-desktop-portal-gtk for the native chooser." >&2
    exit 1
  fi
done
/usr/libexec/xdg-desktop-portal-gtk > "$TMPDIR/portal-gtk.log" 2>&1 &
e2e_gtk_pid=$!
/usr/libexec/xdg-desktop-portal > "$TMPDIR/portal.log" 2>&1 &
e2e_portal_pid=$!
trap 'kill "$e2e_gtk_pid" "$e2e_portal_pid" 2>/dev/null || true' EXIT
cd "$e2e_script_dir/.."
node e2e/walkthrough.mjs
