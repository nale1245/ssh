-- =============================================================================
-- 全国大学数据分析大屏 · MySQL 5.7 建库建表脚本
-- 对应设计文档 v2 §3.2；按用户要求：不建 city 字段，统一使用 MySQL（不做 SQLite 兜底）
--
-- 执行方式（二选一）：
--   1) 命令行： mysql -u <user> -p < schema.sql
--   2) 由 load_data.py 自动执行（推荐，会先建库再逐条建表）
--
-- 说明：
--   - 字符集 utf8mb4 / utf8mb4_unicode_ci，支持中文校名与生僻字
--   - ranking 增加唯一键 (univ_id, year)，保证一校一年一条
--   - 增加外键，保证 ranking / admission / major_score 的 univ_id 有效
--   - 脚本可重复执行（IF NOT EXISTS），不会删除已有数据
-- =============================================================================

CREATE DATABASE IF NOT EXISTS university
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE university;

-- -----------------------------------------------------------------------------
-- 1) university：学校基础信息（一层 = 一所学校）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS university (
  id        INT PRIMARY KEY AUTO_INCREMENT,
  name      VARCHAR(100) NOT NULL UNIQUE COMMENT '学校名（取最新年份）',
  province  VARCHAR(50)  COMMENT '省级行政区',
  type      VARCHAR(20)  COMMENT '类型：综合/理工/师范/农业/林业',
  level     VARCHAR(20)  COMMENT '层次：985/211/双一流/普通',
  is_985    TINYINT(1) DEFAULT 0,
  is_211    TINYINT(1) DEFAULT 0,
  is_double TINYINT(1) DEFAULT 0,
  KEY idx_province (province)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='学校基础信息';

-- -----------------------------------------------------------------------------
-- 2) ranking：历年排名（一行 = 一所学校一年）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ranking (
  id             INT PRIMARY KEY AUTO_INCREMENT,
  univ_id        INT NOT NULL COMMENT '学校外键',
  year           INT NOT NULL COMMENT '年份 2021-2026',
  `rank`         INT COMMENT '名次；软科 500+ 的学校统一记为 1000（哨兵值，见 docs/阶段2）',
  score_total    DECIMAL(6,2) COMMENT '总分；500+ 学校软科不发布',
  score_research DECIMAL(6,2) COMMENT '科研得分；仅前 100 名有值',
  score_talent   DECIMAL(6,2) COMMENT '人才培养得分；仅前 100 名有值',
  score_social   DECIMAL(6,2) COMMENT '社会服务得分；仅前 100 名有值',
  stars          TINYINT COMMENT '星级 1-5（按名次分段派生，非软科官方字段）',
  UNIQUE KEY uk_univ_year (univ_id, year),
  KEY idx_year_rank (year, `rank`),
  CONSTRAINT fk_ranking_university FOREIGN KEY (univ_id)
    REFERENCES university (id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='历年软科排名';

-- -----------------------------------------------------------------------------
-- 3) admission：招生计划（阶段 5 阳光高考爬虫写入，先建空表）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admission (
  id       INT PRIMARY KEY AUTO_INCREMENT,
  univ_id  INT NOT NULL,
  year     INT,
  province VARCHAR(50),
  major    VARCHAR(100),
  `count`  INT COMMENT '招录人次',
  KEY idx_prov_year (province, year),
  KEY idx_univ (univ_id),
  CONSTRAINT fk_admission_university FOREIGN KEY (univ_id)
    REFERENCES university (id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='招生计划（P1）';

-- -----------------------------------------------------------------------------
-- 4) major_score：专业录取线（可选，P2，先建空表）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS major_score (
  id        INT PRIMARY KEY AUTO_INCREMENT,
  univ_id   INT NOT NULL,
  year      INT,
  province  VARCHAR(50),
  major     VARCHAR(100),
  min_score INT COMMENT '最低录取分',
  KEY idx_prov_major (province, major),
  CONSTRAINT fk_major_score_university FOREIGN KEY (univ_id)
    REFERENCES university (id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='专业录取线（P2）';
