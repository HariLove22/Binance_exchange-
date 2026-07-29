-- Fake BTC/USDT orders for testing the order book, before any form or API exists.
-- Re-runnable: clears existing orders first.
--
-- Prices and quantities are SCALED INTEGERS (8 decimals), same as the app writes them:
--   50,050.00 USDT  ->  5005000000000
--          1.00 BTC ->      100000000
--
-- The book is deliberately NOT crossed: best bid (50,000) < best ask (50,050), so the
-- spread is 50 USDT. A crossed book would be an invalid state a matching engine should
-- never have allowed to exist.
--
-- created_at is staggered so time priority is visible: at the same price, the older order
-- must fill first (FIFO).

DELETE FROM orders;

INSERT INTO orders (user_id, pair, side, price, quantity, status, created_at) VALUES
  -- ===== ASKS / sellers (price ascending — best ask first) =====
  (2, 'BTC/USDT', 'SELL', 5005000000000, 100000000, 'NEW', now() - interval '9 minutes'),  -- 50,050.00 x 1.00  <- BEST ASK
  (4, 'BTC/USDT', 'SELL', 5010000000000,  50000000, 'NEW', now() - interval '8 minutes'),  -- 50,100.00 x 0.50
  (6, 'BTC/USDT', 'SELL', 5015000000000, 120000000, 'NEW', now() - interval '7 minutes'),  -- 50,150.00 x 1.20
  (7, 'BTC/USDT', 'SELL', 5020000000000,  80000000, 'NEW', now() - interval '6 minutes'),  -- 50,200.00 x 0.80
  (8, 'BTC/USDT', 'SELL', 5030000000000, 250000000, 'NEW', now() - interval '5 minutes'),  -- 50,300.00 x 2.50

  -- ===== BIDS / buyers (price descending — best bid first) =====
  (1, 'BTC/USDT', 'BUY',  5000000000000, 200000000, 'NEW', now() - interval '4 minutes'),  -- 50,000.00 x 2.00  <- BEST BID
  (4, 'BTC/USDT', 'BUY',  4995000000000, 150000000, 'NEW', now() - interval '3 minutes'),  -- 49,950.00 x 1.50
  (6, 'BTC/USDT', 'BUY',  4990000000000,  75000000, 'NEW', now() - interval '2 minutes'),  -- 49,900.00 x 0.75
  (7, 'BTC/USDT', 'BUY',  4985000000000, 300000000, 'NEW', now() - interval '1 minute'),   -- 49,850.00 x 3.00
  (8, 'BTC/USDT', 'BUY',  4980000000000, 110000000, 'NEW', now());                          -- 49,800.00 x 1.10
