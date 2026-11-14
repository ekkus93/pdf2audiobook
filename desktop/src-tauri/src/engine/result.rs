//! Reading what a finished CLI command reported (spec D3.c).

use serde::{Deserialize, Serialize};

use super::process::Finished;

/// The CLI's JSON error object: `{"ok": false, "error": {...}, "warnings": [...]}`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EngineError {
    #[serde(rename = "type")]
    pub kind: String,
    pub code: i32,
    pub message: String,
    /// A stable code for failures the app acts on, such as `review_required` (spec D2.b).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum Outcome {
    /// Exit 0 with a JSON object on stdout.
    Success { result: serde_json::Value },
    /// The CLI reported a failure in its JSON error format.
    Failed {
        error: EngineError,
        warnings: Vec<String>,
    },
    /// Neither: only the exit code is kept, never any output text.
    Unreadable { exit_code: Option<i32> },
}

/// The fixed message shown for [`Outcome::Unreadable`].
pub const UNREADABLE_MESSAGE: &str = "The engine returned an unreadable result";

#[derive(Deserialize)]
struct ErrorEnvelope {
    ok: bool,
    error: EngineError,
    #[serde(default)]
    warnings: Vec<String>,
}

pub fn parse(done: &Finished) -> Outcome {
    if done.code == Some(0) {
        return match serde_json::from_str::<serde_json::Value>(done.stdout.trim()) {
            Ok(result) if result.is_object() => Outcome::Success { result },
            _ => Outcome::Unreadable {
                exit_code: done.code,
            },
        };
    }
    // The error object is the last JSON line on stderr; log events and warnings may precede it.
    done.stderr
        .lines()
        .rev()
        .filter_map(|line| serde_json::from_str::<ErrorEnvelope>(line.trim()).ok())
        .find(|envelope| !envelope.ok)
        .map(|envelope| Outcome::Failed {
            error: envelope.error,
            warnings: envelope.warnings,
        })
        .unwrap_or(Outcome::Unreadable {
            exit_code: done.code,
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn finished(code: Option<i32>, stdout: &str, stderr: &str) -> Finished {
        Finished {
            code,
            stdout: stdout.into(),
            stderr: stderr.into(),
        }
    }

    #[test]
    fn success_json_is_returned() {
        let done = finished(
            Some(0),
            "{\n  \"workspace\": \"/w\",\n  \"exists\": true\n}\n",
            "",
        );
        assert_eq!(
            parse(&done),
            Outcome::Success {
                result: json!({"workspace": "/w", "exists": true})
            }
        );
    }

    #[test]
    fn every_reason_is_kept() {
        let reasons = [
            "review_required",
            "review_acknowledgement_required",
            "workspace_locked",
            "pending_recovery",
            "chapter_conflict",
            "llm_unreachable",
            "llm_context_too_small",
            "llm_output_cap",
            "budget_exhausted",
        ];
        for reason in reasons {
            let line = json!({
                "ok": false,
                "error": {"type": "AudioError", "code": 6, "message": "Stopped", "reason": reason},
                "warnings": ["empty_chapter"],
            });
            let done = finished(Some(6), "", &format!("{line}\n"));
            assert_eq!(
                parse(&done),
                Outcome::Failed {
                    error: EngineError {
                        kind: "AudioError".into(),
                        code: 6,
                        message: "Stopped".into(),
                        reason: Some(reason.into()),
                    },
                    warnings: vec!["empty_chapter".into()],
                }
            );
        }
    }

    #[test]
    fn an_error_without_a_reason_has_none() {
        let done = finished(
            Some(3),
            "",
            r#"{"ok": false, "error": {"type": "InputError", "code": 3, "message": "PDF not found"}, "warnings": []}"#,
        );
        let Outcome::Failed { error, .. } = parse(&done) else {
            panic!("expected a failure")
        };
        assert_eq!(error.reason, None);
        assert_eq!(error.kind, "InputError");
    }

    #[test]
    fn the_error_is_found_after_log_lines() {
        let stderr = concat!(
            "Warning: Analysis recorded 2 warnings; see warnings in manifest.json.\n",
            "{\"event\": \"command_failed\", \"fields\": {\"error_code\": 5}, \"level\": \"error\"}\n",
            "{\"ok\": false, \"error\": {\"type\": \"LLMError\", \"code\": 5, \"message\": \"cut off\", \"reason\": \"llm_output_cap\"}, \"warnings\": []}\n",
        );
        let Outcome::Failed { error, .. } = parse(&finished(Some(5), "", stderr)) else {
            panic!("expected a failure")
        };
        assert_eq!(error.reason.as_deref(), Some("llm_output_cap"));
    }

    #[test]
    fn unreadable_success_output_keeps_only_the_exit_code() {
        for stdout in ["", "not json PRIVATE BOOK TEXT", "[1, 2]", "{\"cut\": "] {
            assert_eq!(
                parse(&finished(Some(0), stdout, "")),
                Outcome::Unreadable { exit_code: Some(0) }
            );
        }
    }

    #[test]
    fn a_failure_without_an_error_object_is_unreadable() {
        let stderrs = [
            "Traceback (most recent call last): PRIVATE BOOK TEXT\n",
            "{\"ok\": true, \"error\": {\"type\": \"X\", \"code\": 1, \"message\": \"m\"}}\n",
            "{\"ok\": false, \"error\": {\"type\": \"X\"}}\n",
            "",
        ];
        for stderr in stderrs {
            let outcome = parse(&finished(Some(1), "", stderr));
            assert_eq!(outcome, Outcome::Unreadable { exit_code: Some(1) });
            assert!(!format!("{outcome:?}").contains("PRIVATE"));
        }
    }

    #[test]
    fn a_process_ended_by_a_signal_is_unreadable() {
        assert_eq!(
            parse(&finished(None, "", "")),
            Outcome::Unreadable { exit_code: None }
        );
    }

    #[test]
    fn outcomes_serialize_for_the_frontend() {
        let failed = Outcome::Failed {
            error: EngineError {
                kind: "AudioError".into(),
                code: 6,
                message: "m".into(),
                reason: None,
            },
            warnings: vec![],
        };
        assert_eq!(
            serde_json::to_value(failed).unwrap(),
            json!({"outcome": "failed", "error": {"type": "AudioError", "code": 6, "message": "m"}, "warnings": []})
        );
        assert_eq!(
            serde_json::to_value(Outcome::Unreadable { exit_code: Some(2) }).unwrap(),
            json!({"outcome": "unreadable", "exit_code": 2})
        );
    }
}
