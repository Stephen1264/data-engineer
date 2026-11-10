-- 订单归属以购买时间为准。卖家参与过的订单来自商品明细。
WITH orders_2017 AS (
    SELECT *
    FROM orders
    WHERE order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp <  '2018-01-01'
), seller_orders AS (
    SELECT i.seller_id, i.order_id, SUM(i.price + i.freight_value) AS seller_order_gmv
    FROM order_items AS i
    JOIN orders_2017 AS o USING (order_id)
    GROUP BY i.seller_id, i.order_id
), ranked_reviews AS (
    SELECT r.order_id, r.review_score, ROW_NUMBER() OVER (
        PARTITION BY r.order_id
        ORDER BY r.review_answer_timestamp DESC, r.review_creation_date DESC,
                 r.review_id DESC, r.review_score DESC
    ) AS review_rank
    FROM order_reviews AS r
    JOIN orders_2017 AS o USING (order_id)
), seller_metrics AS (
    SELECT
        so.seller_id,
        s.seller_state,
        SUM(CASE WHEN o.order_status = 'delivered' THEN so.seller_order_gmv ELSE 0 END)
            AS gmv_2017,
        COUNT(*) AS order_count,
        COUNT(DISTINCT c.customer_unique_id) AS unique_customers,
        ROUND(AVG(r.review_score), 2) AS avg_review_score,
        -- 预计送达是日历日期。当天签收视为按时，无可用日期时分母为空。
        ROUND(100.0 * AVG(CASE
            WHEN o.order_status = 'delivered'
             AND o.order_delivered_customer_date >= o.order_purchase_timestamp
             AND o.order_estimated_delivery_date IS NOT NULL
            THEN DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)
        END), 2) AS late_delivery_rate,
        ROUND(100.0 * SUM(o.order_status = 'canceled') / COUNT(*), 2) AS cancel_rate
    FROM seller_orders AS so
    JOIN orders_2017 AS o USING (order_id)
    LEFT JOIN customers AS c USING (customer_id)
    JOIN sellers AS s USING (seller_id)
    LEFT JOIN ranked_reviews AS r ON r.order_id = o.order_id AND r.review_rank = 1
    GROUP BY so.seller_id, s.seller_state
), ranked_sellers AS (
    SELECT seller_metrics.*,
        RANK() OVER (PARTITION BY seller_state ORDER BY gmv_2017 DESC) AS state_rank
    FROM seller_metrics
)
SELECT seller_id, seller_state, gmv_2017, order_count, unique_customers,
       avg_review_score, late_delivery_rate, cancel_rate, state_rank
FROM ranked_sellers
ORDER BY gmv_2017 DESC, seller_id
LIMIT 20;
