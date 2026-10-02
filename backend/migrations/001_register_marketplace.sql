-- nkz-module-notifications/backend/migrations/001_register_marketplace.sql
-- Registration of the module in the marketplace (gateway auto-proxy).
-- Column is `id` (PK), NOT `module_id`. NOT NULL: id, name, display_name,
-- version, is_active, required_plan_level.

INSERT INTO marketplace_modules
    (id, name, display_name, description, scope, exposed_module, version,
     is_active, required_plan_level, required_roles, route_path, label,
     icon_url, metadata)
VALUES (
    'notifications',
    'notifications',
    'Notifications',
    'Notifications — alert delivery (digest + immediate) for Nekazari Platform',
    'notifications',
    './Module',
    '1.0.0',
    true,
    0,
    '{"TenantAdmin","PlatformAdmin"}',
    '/notifications',
    'Notifications',
    'bell',
    '{"api_prefix": "/api/notifications", "backend_service": "http://notifications-api-service:8000", "backend_mount": "/api/notifications", "strip_remainder_prefix": false, "requires_auth": true, "hostApiVersion": "^2.0.0", "deploy_method": "dist_endpoint"}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    metadata = EXCLUDED.metadata,
    updated_at = now();
