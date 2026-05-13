BEGIN;

CREATE INDEX IF NOT EXISTS ix_friendship_amigo1_estado
ON friendships (correo_amigo_1, estado);

CREATE INDEX IF NOT EXISTS ix_friendship_amigo2_estado
ON friendships (correo_amigo_2, estado);

COMMIT;