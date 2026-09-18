USE jaes_bima2;

INSERT INTO roles(name,description) VALUES
('MasterAdmin','Full dashboard administration and system access'),
('Researcher','Historical analysis and ML development'),
('Operator','Realtime operational monitoring'),
('Viewer','Read-only inspection access')
ON DUPLICATE KEY UPDATE description=VALUES(description);

SET @master_id = (SELECT id FROM roles WHERE name='MasterAdmin' LIMIT 1);
UPDATE users u JOIN roles r ON u.role_id=r.id
SET u.role_id=@master_id
WHERE r.name='Admin' AND r.id<>@master_id;
DELETE FROM roles WHERE name='Admin' AND id<>@master_id;

INSERT INTO permissions(code,description) VALUES
('realtime.view','View realtime inspection'),
('historical.view','View historical analysis'),
('ml1.train','Train ML1'),
('ml2.train','Train ML2'),
('error.view','View error analysis'),
('model.compare','Compare models'),
('model.register','Register model'),
('model.activate','Activate production model'),
('users.manage','Create edit disable dashboard users'),
('roles.manage','Manage dashboard roles and permissions')
ON DUPLICATE KEY UPDATE description=VALUES(description);

DELETE rp FROM role_permissions rp JOIN roles r ON r.id=rp.role_id
WHERE r.name IN ('MasterAdmin','Researcher','Operator','Viewer');
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r CROSS JOIN permissions p WHERE r.name='MasterAdmin';
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.code IN
('realtime.view','historical.view','ml1.train','ml2.train','error.view','model.compare','model.register')
WHERE r.name='Researcher';
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.code IN ('realtime.view','error.view')
WHERE r.name='Operator';
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.code IN ('realtime.view','historical.view','model.compare')
WHERE r.name='Viewer';
