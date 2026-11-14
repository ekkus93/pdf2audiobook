//! The frontend's permissions stay as narrow as spec D8.a says: the app's own commands, its
//! events, the open and save dialogs, and the app's `chapter:` protocol, which reads only the
//! open book's `audio/` folder. Adding any other permission, capability, window or plugin fails
//! here.

use std::fs;
use std::path::PathBuf;

use serde_json::Value;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn json(path: &str) -> Value {
    serde_json::from_str(&fs::read_to_string(root().join(path)).unwrap()).unwrap()
}

#[test]
fn there_is_one_capability_for_the_main_window_only() {
    let files: Vec<String> = fs::read_dir(root().join("capabilities"))
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .collect();
    assert_eq!(files, ["default.json"]);
    let capability = json("capabilities/default.json");
    // The review window has no capability: it can't reach any command (spec D6.a).
    assert_eq!(capability["windows"], serde_json::json!(["main"]));
    assert!(
        capability.get("remote").is_none(),
        "no remote URL may use a capability"
    );
    assert!(capability.get("platforms").is_none());
}

#[test]
fn the_main_window_has_only_events_and_the_file_dialogs() {
    let capability = json("capabilities/default.json");
    let mut permissions: Vec<&str> = capability["permissions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|permission| {
            permission
                .as_str()
                .expect("plain permission names, no scopes")
        })
        .collect();
    permissions.sort_unstable();
    assert_eq!(
        permissions,
        [
            "core:event:allow-listen",
            "core:event:allow-unlisten",
            "dialog:allow-open",
            "dialog:allow-save",
        ]
    );
}

#[test]
fn the_asset_protocol_is_off() {
    // Its scope can only grow, so it would keep every earlier book's folder readable; chapters
    // come through the app's own `chapter:` protocol instead (audio::serve).
    let config = json("tauri.conf.json");
    let asset = &config["app"]["security"]["assetProtocol"];
    assert!(
        asset.is_null() || asset["enable"] == Value::Bool(false),
        "{asset}"
    );
    let manifest = fs::read_to_string(root().join("Cargo.toml")).unwrap();
    assert!(
        !manifest.contains("protocol-asset"),
        "the asset protocol feature is linked"
    );
}

#[test]
fn no_plugin_beyond_the_dialog_is_linked() {
    let manifest = fs::read_to_string(root().join("Cargo.toml")).unwrap();
    let plugins: Vec<&str> = manifest
        .lines()
        .filter_map(|line| line.split_once('=').map(|(name, _)| name.trim()))
        .filter(|name| name.starts_with("tauri-plugin-"))
        .collect();
    assert_eq!(plugins, ["tauri-plugin-dialog"]);
    let package: Value =
        serde_json::from_str(&fs::read_to_string(root().join("../package.json")).unwrap()).unwrap();
    let mut frontend: Vec<&str> = package["dependencies"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .filter(|name| name.starts_with("@tauri-apps/"))
        .collect();
    frontend.sort_unstable();
    assert_eq!(frontend, ["@tauri-apps/api", "@tauri-apps/plugin-dialog"]);
}

/// Every source a CSP directive lists, by directive.
fn csp(name: &str) -> Vec<(String, Vec<String>)> {
    let config = json("tauri.conf.json");
    config["app"]["security"][name]
        .as_object()
        .unwrap_or_else(|| panic!("{name} must be set as directives"))
        .iter()
        .map(|(directive, sources)| {
            let sources = sources
                .as_str()
                .unwrap()
                .split_whitespace()
                .map(str::to_owned)
                .collect();
            (directive.clone(), sources)
        })
        .collect()
}

/// Origins the app itself may reach: Tauri's IPC and the app's `chapter:` protocol, and only those.
const LOCAL: [&str; 4] = [
    "ipc:",
    "http://ipc.localhost",
    "chapter:",
    "http://chapter.localhost",
];

#[test]
fn the_release_csp_allows_only_the_apps_own_scripts_and_no_remote_origin() {
    let policy = csp("csp");
    let get = |name: &str| {
        policy
            .iter()
            .find(|(directive, _)| directive == name)
            .map(|(_, sources)| sources.clone())
            .unwrap_or_else(|| panic!("{name} is missing"))
    };
    assert_eq!(get("default-src"), ["'self'"]);
    assert_eq!(get("script-src"), ["'self'"]);
    assert_eq!(get("style-src"), ["'self'"]);
    assert_eq!(get("object-src"), ["'none'"]);
    assert_eq!(get("frame-src"), ["'none'"]);
    for (directive, sources) in &policy {
        for source in sources {
            assert!(!source.contains("unsafe-eval"), "{directive} allows eval");
            assert!(!source.contains('*'), "{directive} has a wildcard");
            if source.contains(':') && !source.starts_with('\'') {
                assert!(
                    LOCAL.contains(&source.as_str())
                        || ["data:", "blob:"].contains(&source.as_str()),
                    "{directive} allows {source}"
                );
            }
        }
        if directive != "style-src-attr" {
            assert!(
                !sources.iter().any(|source| source == "'unsafe-inline'"),
                "{directive}"
            );
        }
    }
}

#[test]
fn the_dev_csp_adds_only_the_local_dev_server() {
    for (directive, sources) in csp("devCsp") {
        for source in &sources {
            assert!(!source.contains("unsafe-eval"), "{directive} allows eval");
            assert!(!source.contains('*'), "{directive} has a wildcard");
            if source.contains(':') && !source.starts_with('\'') {
                assert!(
                    LOCAL.contains(&source.as_str())
                        || ["data:", "blob:", "ws://localhost:1420"].contains(&source.as_str()),
                    "{directive} allows {source}"
                );
            }
        }
    }
}

/// Spec D8.d: the app has no network client of its own. Network use happens only inside the
/// CLI. (`desktop/scripts/no_network.py` runs the app with IPv4 and IPv6 refused.)
#[test]
fn the_app_links_no_network_client() {
    let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".into());
    let output = std::process::Command::new(cargo)
        .args([
            "tree",
            "--offline",
            "--edges",
            "normal",
            "--prefix",
            "none",
            "--format",
            "{p}",
        ])
        .current_dir(root())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let tree = String::from_utf8(output.stdout).unwrap();
    let crates: std::collections::BTreeSet<&str> = tree
        .lines()
        .filter_map(|line| line.split_whitespace().next())
        .collect();
    assert!(crates.contains("tauri"), "the dependency tree was not read");
    for client in [
        "reqwest",
        "hyper",
        "ureq",
        "isahc",
        "curl",
        "surf",
        "attohttpc",
        "tungstenite",
        "tokio-tungstenite",
        "h2",
        "quinn",
    ] {
        assert!(!crates.contains(client), "the app links {client}");
    }
}
