-- 空类别属于分类缺失，与存在类别但缺译名分别统计。
-- 可保留葡语并加未翻译标记，低成本但英文报表需要降级展示。
-- 可补建人工术语表，质量可控但需要持续维护和业务复核。
-- 可机器翻译后审核发布，覆盖快但容易把行业词误译成普通词。
SELECT p.product_category_name, COUNT(*) AS product_count
FROM products AS p
LEFT JOIN product_category_name_translation AS t
    ON t.product_category_name = p.product_category_name
WHERE NULLIF(TRIM(p.product_category_name), '') IS NOT NULL
  AND NULLIF(TRIM(t.product_category_name_english), '') IS NULL
GROUP BY p.product_category_name
ORDER BY product_count DESC, p.product_category_name;
