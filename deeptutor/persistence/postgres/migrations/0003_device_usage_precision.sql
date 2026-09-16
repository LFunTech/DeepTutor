-- 小数用量与 lease 刷新分离；保留原整数秒 DTO 和既有设备/会话历史。
ALTER TABLE enterprise.device_credentials
  ADD COLUMN usage_remainder_us integer NOT NULL DEFAULT 0
    CHECK (usage_remainder_us >= 0 AND usage_remainder_us < 1000000);
