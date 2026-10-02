-- nkz-module-notifications/backend/migrations/001_register_marketplace.sql
-- Registration of the module in the API Gateway.
-- Without this, the auto-proxy will return 404 for /api/notifications/*

INSERT INTO marketplace_modules (module_id, metadata)
VALUES (
    'notifications',
    '{"api_prefix": "/api/notifications", "backend_service": "notifications-api-service", "backend_mount": "/api/notifications", "strip_remainder_prefix": false}'::jsonb
)
ON CONFLICT (module_id) DO UPDATE SET
    metadata = EXCLUDED.metadata;
