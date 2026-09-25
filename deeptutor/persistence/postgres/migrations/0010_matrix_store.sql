-- Matrix nio 0.26.0 store adapter：按 tenant/owner/Partner/Matrix user/device 隔离，
-- account/session blobs 由 nio pickle 后再经 DeepTutor Secret envelope 加密。
CREATE TABLE enterprise.matrix_accounts (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 secret_id text NOT NULL,
 secret_version integer NOT NULL,
 shared boolean NOT NULL,
 account_ciphertext bytea NOT NULL,
 account_nonce bytea NOT NULL,
 created_at_ms bigint NOT NULL,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES enterprise.users(tenant_id, id),
 CHECK ((length(partner_id) > 0) AND (length(partner_id) <= 128)),
 CHECK (length(matrix_user_id) > 0),
 CHECK (length(device_id) > 0),
 CHECK (length(secret_id) > 0),
 CHECK (secret_version >= 1),
 CHECK (octet_length(account_nonce) = 12),
 CHECK ((created_at_ms >= 0) AND (updated_at_ms >= created_at_ms))
);
CREATE TABLE enterprise.matrix_olm_sessions (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 sender_key text NOT NULL,
 session_id text NOT NULL,
 secret_id text NOT NULL,
 secret_version integer NOT NULL,
 creation_time timestamptz NOT NULL,
 last_usage_date timestamptz NOT NULL,
 session_ciphertext bytea NOT NULL,
 session_nonce bytea NOT NULL,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, sender_key, session_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  REFERENCES enterprise.matrix_accounts(tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(sender_key) > 0),
 CHECK (length(session_id) > 0),
 CHECK (length(secret_id) > 0),
 CHECK (secret_version >= 1),
 CHECK (last_usage_date >= creation_time),
 CHECK (octet_length(session_nonce) = 12),
 CHECK (updated_at_ms >= 0)
);
CREATE TABLE enterprise.matrix_megolm_inbound_sessions (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 room_id text NOT NULL,
 sender_key text NOT NULL,
 session_id text NOT NULL,
 fp_key text NOT NULL,
 secret_id text NOT NULL,
 secret_version integer NOT NULL,
 session_ciphertext bytea NOT NULL,
 session_nonce bytea NOT NULL,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id, sender_key, session_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  REFERENCES enterprise.matrix_accounts(tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(room_id) > 0),
 CHECK (length(sender_key) > 0),
 CHECK (length(session_id) > 0),
 CHECK (length(fp_key) > 0),
 CHECK (length(secret_id) > 0),
 CHECK (secret_version >= 1),
 CHECK (octet_length(session_nonce) = 12),
 CHECK (updated_at_ms >= 0)
);
CREATE TABLE enterprise.matrix_forwarded_chains (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 room_id text NOT NULL,
 sender_key text NOT NULL,
 session_id text NOT NULL,
 position integer NOT NULL,
 chain_sender_key text NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id, sender_key, session_id, position),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id, sender_key, session_id)
  REFERENCES enterprise.matrix_megolm_inbound_sessions(tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id, sender_key, session_id)
  ON DELETE CASCADE,
 CHECK (position >= 0),
 CHECK (length(chain_sender_key) > 0)
);
CREATE TABLE enterprise.matrix_device_keys (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 user_id text NOT NULL,
 key_device_id text NOT NULL,
 display_name text NOT NULL DEFAULT '',
 deleted boolean NOT NULL DEFAULT false,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  REFERENCES enterprise.matrix_accounts(tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(user_id) > 0),
 CHECK (length(key_device_id) > 0),
 CHECK (updated_at_ms >= 0)
);
CREATE TABLE enterprise.matrix_device_key_values (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 user_id text NOT NULL,
 key_device_id text NOT NULL,
 key_type text NOT NULL,
 key_value text NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id, key_type),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id)
  REFERENCES enterprise.matrix_device_keys(tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id)
  ON DELETE CASCADE,
 CHECK (length(key_type) > 0),
 CHECK (length(key_value) > 0)
);
CREATE TABLE enterprise.matrix_device_trust_state (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 user_id text NOT NULL,
 key_device_id text NOT NULL,
 state text NOT NULL,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id)
  REFERENCES enterprise.matrix_device_keys(tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id, key_device_id)
  ON DELETE CASCADE,
 CHECK (state IN ('unset','verified','blacklisted','ignored')),
 CHECK (updated_at_ms >= 0)
);
CREATE TABLE enterprise.matrix_encrypted_rooms (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 room_id text NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  REFERENCES enterprise.matrix_accounts(tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(room_id) > 0)
);
CREATE TABLE enterprise.matrix_sync_tokens (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 token text NOT NULL,
 updated_at_ms bigint NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  REFERENCES enterprise.matrix_accounts(tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(token) > 0),
 CHECK (updated_at_ms >= 0)
);
CREATE TABLE enterprise.matrix_outgoing_key_requests (
 tenant_id uuid NOT NULL,
 owner_id text NOT NULL,
 partner_id text NOT NULL,
 matrix_user_id text NOT NULL,
 device_id text NOT NULL,
 request_id text NOT NULL,
 session_id text NOT NULL,
 room_id text NOT NULL,
 algorithm text NOT NULL,
 PRIMARY KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id, request_id),
 FOREIGN KEY (tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  REFERENCES enterprise.matrix_accounts(tenant_id, owner_id, partner_id, matrix_user_id, device_id)
  ON DELETE CASCADE,
 CHECK (length(request_id) > 0),
 CHECK (length(session_id) > 0),
 CHECK (length(room_id) > 0),
 CHECK (length(algorithm) > 0)
);
CREATE INDEX matrix_olm_sessions_usage ON enterprise.matrix_olm_sessions USING btree (tenant_id, owner_id, partner_id, matrix_user_id, device_id, sender_key, last_usage_date DESC);
CREATE INDEX matrix_megolm_sessions_room ON enterprise.matrix_megolm_inbound_sessions USING btree (tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id, sender_key);
CREATE INDEX matrix_device_keys_user ON enterprise.matrix_device_keys USING btree (tenant_id, owner_id, partner_id, matrix_user_id, device_id, user_id);
CREATE INDEX matrix_encrypted_rooms_account ON enterprise.matrix_encrypted_rooms USING btree (tenant_id, owner_id, partner_id, matrix_user_id, device_id, room_id);
CREATE INDEX matrix_outgoing_key_requests_account ON enterprise.matrix_outgoing_key_requests USING btree (tenant_id, owner_id, partner_id, matrix_user_id, device_id, request_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY[
  'matrix_accounts','matrix_olm_sessions','matrix_megolm_inbound_sessions',
  'matrix_forwarded_chains','matrix_device_keys','matrix_device_key_values',
  'matrix_device_trust_state','matrix_encrypted_rooms','matrix_sync_tokens',
  'matrix_outgoing_key_requests'
 ] LOOP
  EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (owner_id = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (owner_id = nullif(current_setting(''app.user_id'',true),''''))',t);
 END LOOP;
END $$;
