-- 先把商品和运费归集到订单。取消率用百分数表示。
WITH item_totals AS (
    SELECT order_id, SUM(price + freight_value) AS order_gmv
    FROM order_items
    GROUP BY order_id
)
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
    COUNT(*) AS total_orders,
    SUM(o.order_status = 'delivered') AS delivered_orders,
    SUM(o.order_status = 'canceled') AS canceled_orders,
    ROUND(100.0 * SUM(o.order_status = 'canceled') / COUNT(*), 2) AS cancel_rate,
    SUM(CASE WHEN o.order_status = 'delivered' THEN COALESCE(i.order_gmv, 0) ELSE 0 END)
        AS delivered_gmv,
    ROUND(AVG(CASE
        WHEN o.order_status = 'delivered'
         AND o.order_delivered_customer_date >= o.order_purchase_timestamp
        THEN TIMESTAMPDIFF(SECOND, o.order_purchase_timestamp, o.order_delivered_customer_date) / 86400.0
    END), 2) AS avg_delivery_days
FROM orders AS o
LEFT JOIN item_totals AS i USING (order_id)
GROUP BY month
ORDER BY month;
