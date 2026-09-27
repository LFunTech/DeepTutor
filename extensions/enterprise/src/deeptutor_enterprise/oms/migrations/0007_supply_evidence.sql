-- 旧供给不能凭数量字段自动推断已核验；原行默认待核对，不删除历史消耗。
ALTER TABLE oms.supply_lots
  ADD COLUMN IF NOT EXISTS supply_basis text NOT NULL DEFAULT 'legacy_unverified',
  ADD COLUMN IF NOT EXISTS verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS created_by text,
  ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='oms.supply_lots'::regclass AND conname='supply_lots_verified_native'
  ) THEN
    ALTER TABLE oms.supply_lots ADD CONSTRAINT supply_lots_verified_native CHECK (
      supply_basis IN ('legacy_unverified','native_units','money','credits','paygo')
      AND (supply_basis IN ('legacy_unverified','native_units') OR hard_ceiling IS NULL)
      AND (verified_at IS NULL OR (supply_basis='native_units' AND hard_ceiling IS NOT NULL))
      AND (created_by IS NULL OR length(created_by)>0)
      AND version>=1
    );
  END IF;
END
$$;
