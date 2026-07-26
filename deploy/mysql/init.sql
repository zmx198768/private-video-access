-- MySQL 8 initialization for a new installation.
-- Replace CHANGE_ME_WITH_A_STRONG_PASSWORD before running.
-- Run as a MySQL administrator:
--   mysql -u root -p < deploy/mysql/init.sql

CREATE DATABASE IF NOT EXISTS `private_video`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'private_video'@'127.0.0.1'
  IDENTIFIED BY 'CHANGE_ME_WITH_A_STRONG_PASSWORD';

ALTER USER 'private_video'@'127.0.0.1'
  IDENTIFIED BY 'CHANGE_ME_WITH_A_STRONG_PASSWORD';

GRANT ALL PRIVILEGES ON `private_video`.*
  TO 'private_video'@'127.0.0.1';

FLUSH PRIVILEGES;

-- Application tables are intentionally not duplicated here.
-- Create or upgrade them with:
--   python manage.py migrate
