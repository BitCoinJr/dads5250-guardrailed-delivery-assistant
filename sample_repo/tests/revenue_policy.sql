SELECT 1 AS failed
WHERE
    (SELECT COALESCE(SUM(revenue), 0) FROM {{ ref('fct_revenue') }})
    <>
    (SELECT COALESCE(SUM(amount), 0) FROM {{ ref('stg_orders') }} WHERE 1 = 1)
