-- One row per claim: journey shape summary. total_transitions counts
-- queue moves; first-pass means one visit, zero deferrals.
CREATE OR REPLACE VIEW fct_claim_stats AS
WITH per_claim AS (
    SELECT
        claim_id,
        COUNT(*) AS visits,
        COUNT(*) FILTER (WHERE transitioned) AS total_transitions,
        MIN(entered_at) AS first_entered,
        MAX(left_at) AS last_left,
        DATEDIFF('minute', MIN(entered_at), MAX(left_at)) / 60.0 AS total_hours
    FROM claim_journeys
    GROUP BY claim_id
),
defers AS (
    SELECT claim_id, COUNT(*) AS defers
    FROM stg_events WHERE event_type = 'defer' GROUP BY claim_id
),
touches AS (
    SELECT claim_id, COUNT(*) AS touches
    FROM stg_events WHERE event_type = 'touch' GROUP BY claim_id
)
SELECT
    p.claim_id,
    p.visits,
    p.total_transitions,
    COALESCE(t.touches, 0) AS touches,
    COALESCE(d.defers, 0) AS defers,
    ROUND(p.total_hours, 2) AS total_hours,
    (p.visits = 1 AND COALESCE(d.defers, 0) = 0) AS first_pass
FROM per_claim p
LEFT JOIN defers d USING (claim_id)
LEFT JOIN touches t USING (claim_id);
