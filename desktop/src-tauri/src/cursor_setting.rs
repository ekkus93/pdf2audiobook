//! A GNOME cursor setting the AppImage's GTK cannot start with on Wayland.
//!
//! The AppImage carries the GTK of the system it was built on (3.24.33, Ubuntu 22.04). With the
//! desktop's cursor size set to 0, or no cursor theme named, that GTK fails to load a cursor
//! theme on Wayland and then aborts on an assertion before any window opens ("Failed to load
//! cursor theme", then `cursor_theme_name` in `gdkdisplay-wayland.c`). Newer GTK falls back to
//! defaults, so the `.deb`, which uses the system's GTK, is not affected.
//!
//! GTK is on Wayland when `WAYLAND_DISPLAY` names a socket or, with it unset, when the default
//! socket `$XDG_RUNTIME_DIR/wayland-0` exists: a terminal started outside the desktop session
//! has no `WAYLAND_DISPLAY` (nor `DISPLAY`), yet GTK still reaches the desktop through it.
//!
//! When the AppImage starts on Wayland with such a setting, it starts again in place with
//! `GDK_BACKEND=x11`, through Xwayland, where the same settings arrive by XSETTINGS and the
//! cursor loads; without an X server it uses the settings' defaults instead
//! (`GSETTINGS_BACKEND=memory`), which loses the desktop's other GTK settings but opens the app.

use std::ffi::OsString;

#[derive(Debug, PartialEq, Eq)]
pub enum Fix {
    X11,
    DefaultSettings,
}

impl Fix {
    fn variable(&self) -> (&'static str, &'static str) {
        match self {
            Fix::X11 => ("GDK_BACKEND", "x11"),
            Fix::DefaultSettings => ("GSETTINGS_BACKEND", "memory"),
        }
    }
}

/// The cursor theme and size GNOME's settings give GTK.
pub struct Cursor {
    pub theme: String,
    pub size: i32,
}

/// Whether GTK will connect to Wayland: a socket named in the environment, or the default one.
pub fn on_wayland(var: &impl Fn(&str) -> Option<OsString>, default_socket: bool) -> bool {
    let set = |name: &str| var(name).is_some_and(|value| !value.is_empty());
    set("WAYLAND_DISPLAY") || set("WAYLAND_SOCKET") || default_socket
}

/// What to change, if anything, given the environment, whether the default Wayland socket
/// exists, and the desktop's cursor setting. Only an AppImage on Wayland is affected, and a
/// variable already chosen (by the user, or by an earlier start) is left alone, so the restart
/// happens at most once.
pub fn choose(
    var: impl Fn(&str) -> Option<OsString>,
    default_socket: bool,
    cursor: Option<&Cursor>,
) -> Option<Fix> {
    let set = |name: &str| var(name).is_some_and(|value| !value.is_empty());
    if !set("APPIMAGE")
        || !on_wayland(&var, default_socket)
        || set("GDK_BACKEND")
        || set("GSETTINGS_BACKEND")
    {
        return None;
    }
    let cursor = cursor?;
    if cursor.size > 0 && !cursor.theme.is_empty() {
        return None;
    }
    Some(if set("DISPLAY") {
        Fix::X11
    } else {
        Fix::DefaultSettings
    })
}

#[cfg(target_os = "linux")]
fn read_cursor() -> Option<Cursor> {
    use gio::prelude::SettingsExt;
    const SCHEMA: &str = "org.gnome.desktop.interface";
    let schema = gio::SettingsSchemaSource::default()?.lookup(SCHEMA, true)?;
    if !schema.has_key("cursor-theme") || !schema.has_key("cursor-size") {
        return None;
    }
    let settings = gio::Settings::new_full(&schema, None::<&gio::SettingsBackend>, None);
    Some(Cursor {
        theme: settings.string("cursor-theme").to_string(),
        size: settings.int("cursor-size"),
    })
}

/// Before anything else starts: restart the AppImage with the fix when its GTK would abort.
/// Returns only when no restart is needed or the restart could not happen.
#[cfg(target_os = "linux")]
pub fn restart_if_needed() {
    use std::os::unix::process::CommandExt;
    let var = |name: &str| std::env::var_os(name);
    let default_socket = var("XDG_RUNTIME_DIR")
        .map(std::path::PathBuf::from)
        .is_some_and(|dir| dir.is_absolute() && dir.join("wayland-0").exists());
    if var("APPIMAGE").is_none() || !on_wayland(&var, default_socket) {
        return; // the common case: no settings to read
    }
    let Some(fix) = choose(var, default_socket, read_cursor().as_ref()) else {
        return;
    };
    let Ok(program) = std::env::current_exe() else {
        return;
    };
    let (name, value) = fix.variable();
    eprintln!(
        "pdf2audiobook: the desktop's cursor setting would stop this GTK on Wayland; starting with {name}={value}"
    );
    // exec only returns on failure; the app then starts as it would have.
    let _ = std::process::Command::new(program)
        .args(std::env::args_os().skip(1))
        .env(name, value)
        .exec();
}

#[cfg(not(target_os = "linux"))]
pub fn restart_if_needed() {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<OsString> {
        let map: HashMap<String, OsString> = pairs
            .iter()
            .map(|(key, value)| (key.to_string(), OsString::from(value)))
            .collect();
        move |name| map.get(name).cloned()
    }

    fn cursor(theme: &str, size: i32) -> Cursor {
        Cursor {
            theme: theme.into(),
            size,
        }
    }

    const APPIMAGE_ON_WAYLAND: [(&str, &str); 3] = [
        ("APPIMAGE", "/home/user/pdf2audiobook.AppImage"),
        ("WAYLAND_DISPLAY", "wayland-0"),
        ("DISPLAY", ":0"),
    ];

    #[test]
    fn a_zero_cursor_size_moves_the_appimage_to_x11() {
        let fix = choose(env(&APPIMAGE_ON_WAYLAND), false, Some(&cursor("", 0)));
        assert_eq!(fix, Some(Fix::X11));
        let fix = choose(
            env(&APPIMAGE_ON_WAYLAND),
            false,
            Some(&cursor("Adwaita", 0)),
        );
        assert_eq!(fix, Some(Fix::X11));
        let fix = choose(env(&APPIMAGE_ON_WAYLAND), false, Some(&cursor("", 24)));
        assert_eq!(fix, Some(Fix::X11));
    }

    #[test]
    fn without_an_x_server_the_settings_defaults_are_used() {
        let vars = env(&APPIMAGE_ON_WAYLAND[..2]);
        assert_eq!(
            choose(vars, false, Some(&cursor("", 0))),
            Some(Fix::DefaultSettings)
        );
    }

    #[test]
    fn a_usable_cursor_setting_changes_nothing() {
        let fix = choose(
            env(&APPIMAGE_ON_WAYLAND),
            false,
            Some(&cursor("Adwaita", 24)),
        );
        assert_eq!(fix, None);
        assert_eq!(choose(env(&APPIMAGE_ON_WAYLAND), false, None), None);
    }

    #[test]
    fn only_the_appimage_on_wayland_is_restarted() {
        let deb = env(&[("WAYLAND_DISPLAY", "wayland-0"), ("DISPLAY", ":0")]);
        assert_eq!(choose(deb, false, Some(&cursor("", 0))), None);
        let x11 = env(&[("APPIMAGE", "/a.AppImage"), ("DISPLAY", ":0")]);
        assert_eq!(choose(x11, false, Some(&cursor("", 0))), None);
    }

    #[test]
    fn the_default_wayland_socket_counts_when_wayland_display_is_unset() {
        // A terminal started outside the desktop session: no WAYLAND_DISPLAY and no DISPLAY.
        let tty = env(&[
            ("APPIMAGE", "/a.AppImage"),
            ("XDG_RUNTIME_DIR", "/run/user/1000"),
        ]);
        let fix = choose(&tty, true, Some(&cursor("", 0)));
        assert_eq!(fix, Some(Fix::DefaultSettings));
        assert_eq!(choose(&tty, false, Some(&cursor("", 0))), None);
    }

    #[test]
    fn a_backend_already_chosen_is_left_alone_so_it_restarts_once() {
        for chosen in [("GDK_BACKEND", "wayland"), ("GSETTINGS_BACKEND", "memory")] {
            let mut pairs = APPIMAGE_ON_WAYLAND.to_vec();
            pairs.push(chosen);
            assert_eq!(choose(env(&pairs), false, Some(&cursor("", 0))), None);
        }
    }
}
