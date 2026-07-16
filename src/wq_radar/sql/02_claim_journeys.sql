-- One row per queue VISIT: reconstructed from route_in events with
-- window functions. A visit spans from its route_in to the next
-- route_in (or the claim's resolve). Transition columns describe the
-- move that ended the visit.
CREATE OR REPLACE VIEW claim_journeys AS
WITH route_ins AS (
    SELECT
        claim_id,
        wq_id,
        rule_id,
        event_time AS entered_at,
        seq,
        ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY seq) AS visit_no,
        LEAD(wq_id) OVER (PARTITION BY claim_id ORDER BY seq) AS next_wq,
        LEAD(rule_id) OVER (PARTITION BY claim_id ORDER BY seq) AS next_rule,
        LEAD(event_time) OVER (PARTITION BY claim_id ORDER BY seq) AS next_entered_at
    FROM stg_events
    WHERE event_type = 'route_in'
),
resolves AS (
    SELECT claim_id, MAX(event_time) AS resolved_at
    FROM stg_events
    WHERE event_type = 'resolve'
    GROUP BY claim_id
)
SELECT
    r.claim_id,
    r.visit_no,
    r.wq_id,
    r.rule_id,
    r.entered_at,
    COALESCE(r.next_entered_at, s.resolved_at) AS left_at,
    DATEDIFF('minute', r.entered_at,
             COALESCE(r.next_entered_at, s.resolved_at)) / 60.0 AS visit_hours,
    r.next_wq,
    r.next_rule,
    (r.next_wq IS NOT NULL) AS transitioned
FROM route_ins r
LEFT JOIN resolves s USING (claim_id);
