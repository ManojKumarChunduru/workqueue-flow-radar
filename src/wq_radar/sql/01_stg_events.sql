-- Typed staging view over the raw event log. Event order within a claim
-- is (event_time, event_id): event_id breaks timestamp ties with the
-- emission order, since two events in the same second must not shuffle
-- between runs.
CREATE OR REPLACE VIEW stg_events AS
SELECT
    event_id,
    claim_id,
    CAST(event_time AS TIMESTAMP) AS event_time,
    event_type,
    wq_id,
    user_id,
    rule_id,
    ROW_NUMBER() OVER (
        PARTITION BY claim_id ORDER BY event_time, event_id
    ) AS seq
FROM raw_events;
