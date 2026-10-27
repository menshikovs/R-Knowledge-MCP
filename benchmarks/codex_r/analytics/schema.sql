-- Derived data only. Composite run/trial keys are logical foreign keys throughout.
CREATE TABLE IF NOT EXISTS analytics_meta (schema_version INTEGER PRIMARY KEY);
INSERT INTO analytics_meta SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM analytics_meta);
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY, relative_path VARCHAR NOT NULL,
    import_state VARCHAR NOT NULL, completion_state VARCHAR NOT NULL,
    configuration VARCHAR, configuration_source VARCHAR,
    model VARCHAR, effort VARCHAR, instructions VARCHAR,
    revision VARCHAR, dirty BOOLEAN, dirty_fingerprint VARCHAR, source_sha256 VARCHAR,
    images_json VARCHAR, package_pins_json VARCHAR,
    registered_tools_json VARCHAR, allowed_tools_json VARCHAR,
    toolset VARCHAR, telemetry_schema VARCHAR, manifest_schema INTEGER,
    expected_trials INTEGER, observed_trials INTEGER, source_fingerprint VARCHAR,
    jsonl_present BOOLEAN, jsonl_complete BOOLEAN, imported_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS run_metadata (
    run_id VARCHAR PRIMARY KEY,
    created_at_utc VARCHAR,
    benchmark_suite VARCHAR,
    suite_source VARCHAR,
    suite_label VARCHAR,
    tasks_json VARCHAR,
    conditions_json VARCHAR,
    repetitions INTEGER,
    trial_plan_count INTEGER,
    scorer_versions_json VARCHAR,
    prompt_versions_json VARCHAR,
    task_input_hashes_json VARCHAR,
    environment_json VARCHAR,
    timeout_seconds DOUBLE,
    trial_plan_status VARCHAR,
    full_status VARCHAR,
    full_status_reason VARCHAR,
    v2_observation_schema VARCHAR,
    v2_observation_status VARCHAR,
    experiment_id VARCHAR,
    experiment_version VARCHAR,
    experiment_metadata_json VARCHAR
);
CREATE TABLE IF NOT EXISTS trial_plan (
    run_id VARCHAR, planned_trial_id VARCHAR, task_id VARCHAR,
    mode VARCHAR, repetition INTEGER, task_input_sha256 VARCHAR,
    condition VARCHAR, execution_order INTEGER,
    PRIMARY KEY (run_id, planned_trial_id)
);
CREATE TABLE IF NOT EXISTS trials (
    run_id VARCHAR, trial_id VARCHAR, task_id VARCHAR NOT NULL, block VARCHAR,
    mode VARCHAR NOT NULL, repetition INTEGER, model VARCHAR, effort VARCHAR,
    configuration VARCHAR, instructions VARCHAR, compatibility_key VARCHAR,
    status VARCHAR, finalized BOOLEAN, scorer_version VARCHAR,
    passed INTEGER, total INTEGER, fully_correct BOOLEAN, failed_checks_json VARCHAR,
    duration_seconds DOUBLE, agent_seconds DOUBLE,
    mcp_calls_observed INTEGER, client_calls INTEGER, server_calls INTEGER,
    list_tools INTEGER, tool_search_calls INTEGER, metrics_source VARCHAR,
    metrics_json VARCHAR, primary_error_json VARCHAR, cleanup_errors_json VARCHAR,
    cleanup_completed BOOLEAN, session_deleted BOOLEAN, interrupted BOOLEAN,
    api_input_tokens BIGINT, api_output_tokens BIGINT, api_cached_tokens BIGINT,
    api_reasoning_tokens BIGINT, api_total_tokens BIGINT, usage_status VARCHAR,
    cost_amount DOUBLE, cost_currency VARCHAR, cost_status VARCHAR,
    started_at VARCHAR, completed_at VARCHAR,
    condition VARCHAR, execution_order INTEGER, experiment_id VARCHAR,
    scorer_digest VARCHAR, prompt_digest VARCHAR,
    PRIMARY KEY (run_id, trial_id)
);
CREATE TABLE IF NOT EXISTS score_checks (
    run_id VARCHAR, trial_id VARCHAR, scoring_id VARCHAR, check_name VARCHAR,
    passed BOOLEAN, PRIMARY KEY (run_id, trial_id, scoring_id, check_name)
);
CREATE TABLE IF NOT EXISTS score_dimensions (
    run_id VARCHAR, trial_id VARCHAR, scoring_id VARCHAR, scorer_version VARCHAR,
    dimension VARCHAR, status VARCHAR, passed INTEGER, total INTEGER,
    checks_json VARCHAR,
    PRIMARY KEY (run_id, trial_id, scoring_id, dimension)
);
CREATE TABLE IF NOT EXISTS mcp_calls (
    run_id VARCHAR, trial_id VARCHAR, observation_source VARCHAR, call_id VARCHAR,
    tool_name VARCHAR NOT NULL, counted BOOLEAN NOT NULL, status VARCHAR,
    call_sequence INTEGER, request_fingerprint VARCHAR, package_name VARCHAR,
    repository VARCHAR, function_name VARCHAR,
    is_error BOOLEAN, partial BOOLEAN, duration_ms DOUBLE,
    request_bytes BIGINT, result_bytes BIGINT, useful_bytes BIGINT,
    result_tokens_estimate BIGINT, error_codes_json VARCHAR,
    verification_status VARCHAR, version_mismatch BOOLEAN, source_count INTEGER,
    output_truncated BOOLEAN, page_truncated BOOLEAN,
    repeat_kind VARCHAR, repeat_count INTEGER, cache_hits INTEGER,
    cache_network_requests INTEGER, correlation VARCHAR, correlated_call_id VARCHAR,
    PRIMARY KEY (run_id, trial_id, observation_source, call_id)
);
-- V2 observations have no trial identifier. Keep them run-scoped; never join by order.
CREATE TABLE IF NOT EXISTS mcp_observations_v2 (
    run_id VARCHAR, observation_id VARCHAR, source VARCHAR, client_call_number INTEGER,
    client_item_id VARCHAR, server_call_number INTEGER, tool_name VARCHAR,
    correlation_quality VARCHAR, request_projection_json VARCHAR,
    response_projection_json VARCHAR, duration_ms DOUBLE,
    PRIMARY KEY (run_id, observation_id)
);
CREATE TABLE IF NOT EXISTS events (
    run_id VARCHAR, event_id VARCHAR, trial_id VARCHAR, event_type VARCHAR,
    timestamp_utc VARCHAR, monotonic_offset_ms DOUBLE, clock VARCHAR, source VARCHAR,
    call_id VARCHAR, tool_name VARCHAR, correlation VARCHAR,
    cleanup_operation VARCHAR, cleanup_status VARCHAR, error_json VARCHAR,
    PRIMARY KEY (run_id, event_id)
);
-- Closed schema-versioned agent/exposure/evidence projections only; never raw stream items.
CREATE TABLE IF NOT EXISTS agent_telemetry (
    run_id VARCHAR, event_id VARCHAR, trial_id VARCHAR, event_type VARCHAR,
    event_projection_json VARCHAR,
    PRIMARY KEY (run_id, event_id)
);
CREATE TABLE IF NOT EXISTS scoring_revisions (
    run_id VARCHAR, trial_id VARCHAR, revision_id VARCHAR, scorer_version VARCHAR,
    report_path VARCHAR, report_sha256 VARCHAR, generated_at VARCHAR,
    status VARCHAR, dimensions_json VARCHAR, claim_audit_json VARCHAR, primary_error_json VARCHAR,
    passed INTEGER, total INTEGER, fully_correct BOOLEAN, failed_checks_json VARCHAR,
    answer_sha256 VARCHAR, answer_matches_original BOOLEAN,
    PRIMARY KEY (run_id, trial_id, revision_id)
);
CREATE TABLE IF NOT EXISTS artifacts (
    run_id VARCHAR, trial_id VARCHAR, relative_path VARCHAR, sha256 VARCHAR,
    bytes BIGINT, kind VARCHAR,
    PRIMARY KEY (run_id, trial_id, relative_path)
);
CREATE TABLE IF NOT EXISTS source_files (
    run_id VARCHAR, relative_path VARCHAR, sha256 VARCHAR, bytes BIGINT,
    PRIMARY KEY (run_id, relative_path)
);
CREATE TABLE IF NOT EXISTS import_issues (
    run_id VARCHAR, issue_code VARCHAR, occurrences INTEGER,
    PRIMARY KEY (run_id, issue_code)
);
-- P2 evidence is derived from closed telemetry records; payloads and model reasoning are absent.
CREATE TABLE IF NOT EXISTS agent_traces (
    run_id VARCHAR, trial_id VARCHAR, trace_id VARCHAR,
    trace_model_version VARCHAR, trace_completeness VARCHAR,
    integrity_status VARCHAR, schema_validation_status VARCHAR,
    expected_checkpoint_count INTEGER, captured_checkpoint_count INTEGER,
    missing_checkpoint_count INTEGER, capture_completeness DOUBLE,
    trial_duration_ms DOUBLE, time_to_first_mcp_ms DOUBLE,
    event_count INTEGER, integrity_issues_json VARCHAR,
    opportunity_manifest_version VARCHAR, opportunity_manifest_sha256 VARCHAR,
    PRIMARY KEY (run_id, trial_id)
);
CREATE TABLE IF NOT EXISTS agent_spans (
    run_id VARCHAR, trial_id VARCHAR, trace_id VARCHAR,
    span_id VARCHAR, parent_span_id VARCHAR,
    span_kind VARCHAR, event_type VARCHAR, status VARCHAR,
    capture_source VARCHAR, verification_status VARCHAR,
    timestamp_start_utc VARCHAR, timestamp_end_utc VARCHAR, clock VARCHAR,
    start_offset_ms DOUBLE, end_offset_ms DOUBLE, duration_ms DOUBLE,
    call_id VARCHAR, tool_name VARCHAR, event_ids_json VARCHAR,
    PRIMARY KEY (run_id, trial_id, span_id)
);
CREATE TABLE IF NOT EXISTS observability_checkpoints (
    run_id VARCHAR, trial_id VARCHAR, checkpoint_type VARCHAR, subject VARCHAR,
    observation_status VARCHAR, expected BOOLEAN, capture_source VARCHAR,
    verification_status VARCHAR, evidence_reference VARCHAR, reason_code VARCHAR,
    PRIMARY KEY (run_id, trial_id, checkpoint_type, subject)
);
CREATE TABLE IF NOT EXISTS task_opportunity_registry (
    run_id VARCHAR, opportunity_version VARCHAR, task_id VARCHAR,
    task_family VARCHAR, annotation_status VARCHAR, source_path VARCHAR,
    source_file_sha256 VARCHAR, opportunity_manifest_sha256 VARCHAR,
    opportunity_count INTEGER,
    PRIMARY KEY (run_id, opportunity_version, task_id)
);
CREATE TABLE IF NOT EXISTS task_mcp_opportunities (
    run_id VARCHAR, opportunity_version VARCHAR, task_id VARCHAR,
    opportunity_id VARCHAR, task_family VARCHAR, capability VARCHAR,
    candidate_tools_json VARCHAR, relevance VARCHAR, source VARCHAR,
    source_path VARCHAR, rationale VARCHAR, evidence_class VARCHAR,
    source_file_sha256 VARCHAR, opportunity_manifest_sha256 VARCHAR,
    PRIMARY KEY (run_id, opportunity_version, task_id, opportunity_id)
);
CREATE TABLE IF NOT EXISTS trial_opportunity_assessments (
    run_id VARCHAR, trial_id VARCHAR, opportunity_version VARCHAR,
    task_id VARCHAR, opportunity_id VARCHAR,
    applicability_status VARCHAR, configured_status VARCHAR,
    visibility_status VARCHAR, discovery_status VARCHAR,
    invocation_status VARCHAR, success_status VARCHAR,
    assessment_state VARCHAR, adequate_observation BOOLEAN,
    utilized BOOLEAN, missed BOOLEAN, candidate_calls INTEGER,
    repeated_calls INTEGER, evidence_class VARCHAR, opportunity_manifest_sha256 VARCHAR,
    PRIMARY KEY (run_id, trial_id, opportunity_version, opportunity_id)
);

-- Additive migration for databases created by analytics schema v1 before dashboard v2.
ALTER TABLE mcp_calls ADD COLUMN IF NOT EXISTS call_sequence INTEGER;
ALTER TABLE mcp_calls ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR;
ALTER TABLE scoring_revisions ADD COLUMN IF NOT EXISTS status VARCHAR;
ALTER TABLE scoring_revisions ADD COLUMN IF NOT EXISTS dimensions_json VARCHAR;
ALTER TABLE scoring_revisions ADD COLUMN IF NOT EXISTS claim_audit_json VARCHAR;
ALTER TABLE scoring_revisions ADD COLUMN IF NOT EXISTS primary_error_json VARCHAR;
ALTER TABLE score_dimensions ADD COLUMN IF NOT EXISTS scoring_id VARCHAR;
UPDATE score_dimensions SET scoring_id='original' WHERE scoring_id IS NULL;
ALTER TABLE mcp_calls ADD COLUMN IF NOT EXISTS package_name VARCHAR;
ALTER TABLE mcp_calls ADD COLUMN IF NOT EXISTS repository VARCHAR;
ALTER TABLE mcp_calls ADD COLUMN IF NOT EXISTS function_name VARCHAR;

-- Dashboard v2 adds explicit run plans, scope status, V2 projections and dimensions.
DELETE FROM analytics_meta WHERE schema_version = 1;
INSERT INTO analytics_meta SELECT 2 WHERE NOT EXISTS (
    SELECT 1 FROM analytics_meta WHERE schema_version = 2
);

-- B1 adds paired condition identity without changing the legacy mode field.
ALTER TABLE run_metadata ADD COLUMN IF NOT EXISTS experiment_id VARCHAR;
ALTER TABLE run_metadata ADD COLUMN IF NOT EXISTS experiment_version VARCHAR;
ALTER TABLE run_metadata ADD COLUMN IF NOT EXISTS experiment_metadata_json VARCHAR;
ALTER TABLE trial_plan ADD COLUMN IF NOT EXISTS condition VARCHAR;
ALTER TABLE trial_plan ADD COLUMN IF NOT EXISTS execution_order INTEGER;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS condition VARCHAR;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS execution_order INTEGER;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS experiment_id VARCHAR;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS scorer_digest VARCHAR;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS prompt_digest VARCHAR;
DELETE FROM analytics_meta WHERE schema_version = 2;
INSERT INTO analytics_meta SELECT 3 WHERE NOT EXISTS (
    SELECT 1 FROM analytics_meta WHERE schema_version = 3
);

-- Scorer revisions can add dimensions without replacing the original dimensions.
DELETE FROM analytics_meta WHERE schema_version = 3;
INSERT INTO analytics_meta SELECT 4 WHERE NOT EXISTS (
    SELECT 1 FROM analytics_meta WHERE schema_version = 4
);

-- Agent tool and evidence projections are additive; historical runs remain unchanged.
DELETE FROM analytics_meta WHERE schema_version = 4;
INSERT INTO analytics_meta SELECT 5 WHERE NOT EXISTS (
    SELECT 1 FROM analytics_meta WHERE schema_version = 5
);

-- P2 adds versioned trace projections and researcher-authored MCP opportunity assessments.
CREATE INDEX IF NOT EXISTS agent_spans_trial_timeline
    ON agent_spans (run_id, trial_id, start_offset_ms);
CREATE INDEX IF NOT EXISTS trial_opportunities_capability
    ON trial_opportunity_assessments (run_id, opportunity_version, task_id, opportunity_id);
DELETE FROM analytics_meta WHERE schema_version = 5;
INSERT INTO analytics_meta SELECT 6 WHERE NOT EXISTS (
    SELECT 1 FROM analytics_meta WHERE schema_version = 6
);
