-- Ping-pong detection: claims oscillating between the SAME two queues.
--
-- An oscillating transition is a move whose destination equals the
-- queue visited two steps earlier (A -> B -> A shape). One such return
-- is normal operations (rework); a conflict keeps pulling the claim
-- back, so the flag requires at least {min_oscillations} oscillating
-- transitions, all within one unordered queue pair.
CREATE OR REPLACE VIEW pingpong_claims AS
WITH moves AS (
    SELECT
        claim_id,
        visit_no,
        wq_id AS from_wq,
        next_wq AS to_wq,
        rule_id AS from_rule,
        next_rule AS to_rule,
        LAG(wq_id) OVER (PARTITION BY claim_id ORDER BY visit_no) AS prev_wq
    FROM claim_journeys
    WHERE transitioned
),
oscillations AS (
    SELECT
        claim_id,
        LEAST(from_wq, to_wq) AS wq_x,
        GREATEST(from_wq, to_wq) AS wq_y,
        COUNT(*) AS oscillating_transitions,
        ANY_VALUE(from_rule) AS sample_rule_from,
        ANY_VALUE(to_rule) AS sample_rule_to
    FROM moves
    WHERE prev_wq IS NOT NULL AND to_wq = prev_wq
    GROUP BY claim_id, wq_x, wq_y
)
SELECT
    o.claim_id,
    o.wq_x,
    o.wq_y,
    -- the oscillating A->B->A moves plus the initial A->B entry move
    o.oscillating_transitions + 1 AS pair_transitions,
    s.total_transitions,
    s.total_hours,
    s.touches
FROM oscillations o
JOIN fct_claim_stats s USING (claim_id)
WHERE o.oscillating_transitions + 1 >= {min_oscillations};
