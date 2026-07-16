-- Daily operational KPIs per workqueue: the numbers a morning huddle
-- reads. Aging uses visit spans; first-pass yield means resolved with a
-- single queue visit and no deferral.
CREATE OR REPLACE VIEW fct_wq_kpis AS
WITH touches AS (
    SELECT wq_id, CAST(event_time AS DATE) AS day,
           COUNT(*) AS touches,
           COUNT(DISTINCT user_id) AS active_users
    FROM stg_events
    WHERE event_type = 'touch'
    GROUP BY 1, 2
),
defers AS (
    SELECT wq_id, CAST(event_time AS DATE) AS day, COUNT(*) AS defers
    FROM stg_events WHERE event_type = 'defer' GROUP BY 1, 2
),
visits AS (
    SELECT wq_id, CAST(entered_at AS DATE) AS day,
           COUNT(*) AS visits_started,
           ROUND(AVG(visit_hours), 2) AS avg_visit_hours,
           ROUND(QUANTILE_CONT(visit_hours, 0.95), 2) AS p95_visit_hours
    FROM claim_journeys
    GROUP BY 1, 2
),
resolves AS (
    SELECT e.wq_id, CAST(e.event_time AS DATE) AS day, COUNT(*) AS resolved
    FROM stg_events e
    WHERE e.event_type = 'resolve'
    GROUP BY 1, 2
)
SELECT
    COALESCE(v.wq_id, t.wq_id, r.wq_id) AS wq_id,
    COALESCE(v.day, t.day, r.day) AS day,
    COALESCE(v.visits_started, 0) AS visits_started,
    COALESCE(t.touches, 0) AS touches,
    COALESCE(t.active_users, 0) AS active_users,
    COALESCE(d.defers, 0) AS defers,
    COALESCE(r.resolved, 0) AS resolved,
    v.avg_visit_hours,
    v.p95_visit_hours
FROM visits v
FULL OUTER JOIN touches t USING (wq_id, day)
FULL OUTER JOIN defers d USING (wq_id, day)
FULL OUTER JOIN resolves r USING (wq_id, day);
