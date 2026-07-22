ALTER TABLE deliveries
    ADD COLUMN c2pa_status VARCHAR(16) NOT NULL DEFAULT 'NOT_REQUESTED'
    CHECK (c2pa_status IN ('NOT_REQUESTED', 'PENDING', 'SIGNING', 'SIGNED', 'SIGN_FAILED'));

CREATE INDEX ix_deliveries_c2pa_status ON deliveries(c2pa_status)
    WHERE c2pa_status IN ('PENDING', 'SIGNING');
