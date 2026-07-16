-- Attribute ping-pong traffic to the routing rule pair driving it. Each
-- oscillating claim's route_in rule ids on the two queues identify the
-- rules pulling in each direction; a genuine conflict shows the same
-- rule pair across many claims.
CREATE OR REPLACE VIEW conflict_pairs AS
WITH victim_rules AS (
    SELECT
        p.claim_id,
        p.wq_x,
        p.wq_y,
        j.wq_id,
        j.rule_id
    FROM pingpong_claims p
    JOIN claim_journeys j USING (claim_id)
    WHERE j.wq_id IN (p.wq_x, p.wq_y) AND j.rule_id IS NOT NULL
),
pair_rules AS (
    SELECT
        claim_id, wq_x, wq_y,
        MIN(rule_id) FILTER (WHERE wq_id = wq_x) AS rule_into_x,
        MIN(rule_id) FILTER (WHERE wq_id = wq_y) AS rule_into_y
    FROM victim_rules
    GROUP BY claim_id, wq_x, wq_y
)
SELECT
    wq_x,
    wq_y,
    rule_into_x,
    rule_into_y,
    COUNT(*) AS victim_claims,
    ROUND(SUM(s.total_hours), 1) AS victim_hours,
    SUM(s.touches) AS wasted_touches
FROM pair_rules
JOIN fct_claim_stats s USING (claim_id)
WHERE rule_into_x IS NOT NULL AND rule_into_y IS NOT NULL
GROUP BY wq_x, wq_y, rule_into_x, rule_into_y
ORDER BY victim_claims DESC;
