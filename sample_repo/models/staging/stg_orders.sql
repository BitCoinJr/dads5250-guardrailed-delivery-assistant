SELECT
    order_id,
    CAST(order_date AS DATE) AS order_date,
    LOWER(status) AS status,
    CAST(amount AS DECIMAL(18, 2)) AS amount
FROM {{ ref('orders') }}
