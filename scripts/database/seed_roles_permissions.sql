USE jaes_bima2;

INSERT INTO roles (name, description) VALUES
('MasterAdmin','Full system access including user and role management'),
('Researcher','Historical analysis and ML development'),
('Operator','Realtime operational monitoring'),
('Viewer','Read-only inspection access')
ON DUPLICATE KEY UPDATE description=VALUES(description);

INSERT INTO permissions (code, description) VALUES
('realtime.view','View realtime inspection'),
('historical.view','View historical analysis'),
('ml1.train','Train ML1'),
('ml2.train','Train ML2'),
('error.view','View error analysis'),
('model.compare','Compare models'),
('model.register','Register model'),
('model.activate','Activate production model'),
('users.manage','Create/edit/disable users'),
('roles.manage','Manage roles and permissions')
ON DUPLICATE KEY UPDATE description=VALUES(description);

INSERT IGNORE INTO role_permissions(role_id, permission_id)
SELECT r.id,p.id FROM roles r CROSS JOIN permissions p WHERE r.name='MasterAdmin';

INSERT IGNORE INTO role_permissions(role_id, permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p
ON p.code IN ('realtime.view','historical.view','ml1.train','ml2.train','error.view','model.compare','model.register')
WHERE r.name='Researcher';

INSERT IGNORE INTO role_permissions(role_id, permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p
ON p.code IN ('realtime.view','error.view')
WHERE r.name='Operator';

INSERT IGNORE INTO role_permissions(role_id, permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p
ON p.code IN ('realtime.view','historical.view','model.compare')
WHERE r.name='Viewer';
