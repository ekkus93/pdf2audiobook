//! The bridge's fixtures follow the shared CLI contracts in `desktop/contracts` (spec D9.c).
//!
//! The fixtures in `tests/fixtures` are real CLI outputs (paths replaced). Each one must
//! validate against its schema and parse through [`super::result::parse`].

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use super::process::Finished;
use super::result::{Outcome, parse};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).to_path_buf()
}

fn schema(name: &str) -> jsonschema::Validator {
    let path = root()
        .join("../contracts")
        .join(format!("{name}.schema.json"));
    let schema: Value = serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
    jsonschema::options()
        .should_validate_formats(true)
        .build(&schema)
        .unwrap()
}

fn fixture(name: &str) -> String {
    fs::read_to_string(root().join("tests/fixtures").join(name)).unwrap()
}

fn assert_valid(schema_name: &str, instance: &Value) {
    let validator = schema(schema_name);
    let errors: Vec<String> = validator
        .iter_errors(instance)
        .map(|error| error.to_string())
        .collect();
    assert!(errors.is_empty(), "{schema_name}: {errors:?}");
}

/// Success fixtures and the contract each follows.
const RESULTS: [(&str, &str); 13] = [
    ("doctor.json", "doctor"),
    ("doctor-llm-check.json", "doctor"),
    ("config-show.json", "config-show"),
    ("inspect-book.json", "inspect-book"),
    ("inspect-manifest.json", "inspect-manifest"),
    ("workspace.json", "workspace"),
    ("voices.json", "voices"),
    ("thumbnail.json", "thumbnail"),
    ("analyze.json", "analyze"),
    ("convert.json", "convert"),
    ("convert-dry-run.json", "convert-dry-run"),
    ("edits-list.json", "edits-list"),
    ("pack-m4b.json", "pack-m4b"),
];

#[test]
fn success_fixtures_follow_their_contracts_and_parse() {
    for (file, contract) in RESULTS {
        let stdout = fixture(file);
        let expected: Value = serde_json::from_str(&stdout).unwrap();
        assert_valid(contract, &expected);
        let done = Finished {
            code: Some(0),
            stdout,
            stderr: String::new(),
        };
        assert_eq!(
            parse(&done),
            Outcome::Success { result: expected },
            "{file}"
        );
    }
}

#[test]
fn error_fixtures_follow_the_contract_and_parse() {
    let cases = [
        ("error.input.stderr", 3, None),
        ("error.review-required.stderr", 6, Some("review_required")),
    ];
    for (file, code, reason) in cases {
        let stderr = fixture(file);
        let envelope: Value = serde_json::from_str(stderr.lines().last().unwrap()).unwrap();
        assert_valid("error", &envelope);
        let done = Finished {
            code: Some(code),
            stdout: String::new(),
            stderr,
        };
        let Outcome::Failed { error, .. } = parse(&done) else {
            panic!("{file} did not parse as a failure")
        };
        assert_eq!(error.code, code);
        assert_eq!(error.reason.as_deref(), reason);
    }
}

#[test]
fn review_address_and_run_status_fixtures_follow_their_contracts() {
    let line: Value = serde_json::from_str(fixture("review-address.json").trim()).unwrap();
    assert_valid("review-address", &line);
    for file in ["run-status.running.json", "run-status.completed.json"] {
        let status: Value = serde_json::from_str(&fixture(file)).unwrap();
        assert_valid("run-status", &status);
    }
}

#[test]
fn contracts_reject_a_broken_output() {
    let mut doctor: Value = serde_json::from_str(&fixture("doctor.json")).unwrap();
    doctor.as_object_mut().unwrap().remove("version");
    assert!(!schema("doctor").is_valid(&doctor));
    let mut error: Value = serde_json::from_str(fixture("error.input.stderr").trim()).unwrap();
    error["error"]["reason"] = Value::from("made_up_reason");
    assert!(!schema("error").is_valid(&error));
}

#[test]
fn every_contract_has_a_fixture() {
    let mut contracts: Vec<String> = fs::read_dir(root().join("../contracts"))
        .unwrap()
        .filter_map(|entry| {
            let name = entry.unwrap().file_name().into_string().unwrap();
            name.strip_suffix(".schema.json").map(str::to_owned)
        })
        .collect();
    contracts.sort();
    let mut covered: Vec<String> = RESULTS
        .iter()
        .map(|(_, contract)| contract.to_string())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .chain(["error", "review-address", "run-status"].map(String::from))
        .collect();
    covered.sort();
    assert_eq!(contracts, covered);
}
