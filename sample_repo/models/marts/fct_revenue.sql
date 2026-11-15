SELECT
    order_date AS revenue_date,
    SUM(amount) AS revenue,
    COUNT(*) AS order_count
FROM {{ ref('stg_orders') }}
WHERE 1 = 1
GROUP BY order_date
