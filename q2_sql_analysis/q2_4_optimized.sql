-- 订单粒度始终为一行。只对已筛选的订单读取商品和最新评价。
SELECT c.customer_state,
       COUNT(*) AS orders,
       SUM(COALESCE((
           SELECT SUM(i.price)
           FROM order_items AS i
           WHERE i.order_id = o.order_id
       ), 0)) AS revenue,
       AVG((
           SELECT r.review_score
           FROM order_reviews AS r
           WHERE r.order_id = o.order_id
           ORDER BY r.review_answer_timestamp DESC, r.review_creation_date DESC,
                    r.review_id DESC, r.review_score DESC
           LIMIT 1
       )) AS avg_score
FROM customers AS c
STRAIGHT_JOIN orders AS o ON o.customer_id = c.customer_id
WHERE c.customer_city COLLATE utf8mb4_0900_ai_ci LIKE '%sao%'
  AND o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01'
GROUP BY c.customer_state
ORDER BY revenue DESC, c.customer_state;
