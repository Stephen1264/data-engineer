-- Olist 源表保持原始粒度和字段名。邮编前缀作为文本保留。
CREATE TABLE IF NOT EXISTS customers (
    customer_id CHAR(32) PRIMARY KEY,
    customer_unique_id CHAR(32) NOT NULL,
    customer_zip_code_prefix VARCHAR(5) NOT NULL,
    customer_city VARCHAR(96) NOT NULL,
    customer_state CHAR(2) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS geolocation (
    geolocation_zip_code_prefix VARCHAR(5) NOT NULL,
    geolocation_lat DOUBLE NOT NULL,
    geolocation_lng DOUBLE NOT NULL,
    geolocation_city VARCHAR(128) NOT NULL,
    geolocation_state CHAR(2) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS orders (
    order_id CHAR(32) PRIMARY KEY,
    customer_id CHAR(32) NOT NULL,
    order_status VARCHAR(20) NOT NULL,
    order_purchase_timestamp DATETIME NOT NULL,
    order_approved_at DATETIME,
    order_delivered_carrier_date DATETIME,
    order_delivered_customer_date DATETIME,
    order_estimated_delivery_date DATETIME,
    KEY idx_orders_purchase (order_purchase_timestamp),
    KEY idx_orders_status_date (order_status, order_purchase_timestamp, customer_id),
    KEY idx_orders_customer_status_date (customer_id, order_status, order_purchase_timestamp)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS order_items (
    order_id CHAR(32) NOT NULL,
    order_item_id SMALLINT UNSIGNED NOT NULL,
    product_id CHAR(32) NOT NULL,
    seller_id CHAR(32) NOT NULL,
    shipping_limit_date DATETIME,
    price DECIMAL(12,2) NOT NULL,
    freight_value DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS order_payments (
    order_id CHAR(32) NOT NULL,
    payment_sequential SMALLINT UNSIGNED NOT NULL,
    payment_type VARCHAR(24) NOT NULL,
    payment_installments SMALLINT UNSIGNED NOT NULL,
    payment_value DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
) ENGINE=InnoDB;

-- review_id 和 order_id 都可能重复，保留源表中的每一条评价。
CREATE TABLE IF NOT EXISTS order_reviews (
    review_row_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    review_id CHAR(32) NOT NULL,
    order_id CHAR(32) NOT NULL,
    review_score TINYINT UNSIGNED NOT NULL,
    review_comment_title TEXT,
    review_comment_message TEXT,
    review_creation_date DATETIME,
    review_answer_timestamp DATETIME,
    KEY idx_reviews_order_answer (order_id, review_answer_timestamp, review_creation_date, review_id, review_score)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS products (
    product_id CHAR(32) PRIMARY KEY,
    product_category_name VARCHAR(128),
    product_name_lenght INT UNSIGNED,
    product_description_lenght INT UNSIGNED,
    product_photos_qty INT UNSIGNED,
    product_weight_g INT UNSIGNED,
    product_length_cm INT UNSIGNED,
    product_height_cm INT UNSIGNED,
    product_width_cm INT UNSIGNED,
    KEY idx_products_category (product_category_name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sellers (
    seller_id CHAR(32) PRIMARY KEY,
    seller_zip_code_prefix VARCHAR(5) NOT NULL,
    seller_city VARCHAR(96) NOT NULL,
    seller_state CHAR(2) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS product_category_name_translation (
    product_category_name VARCHAR(128) PRIMARY KEY,
    product_category_name_english VARCHAR(128)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gekkolab_load_manifest (
    id TINYINT PRIMARY KEY,
    content_sha256 CHAR(64) NOT NULL
) ENGINE=InnoDB;
