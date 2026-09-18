USE jaes_bima2;

CREATE TABLE IF NOT EXISTS roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL UNIQUE,
  description VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS permissions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(100) NOT NULL UNIQUE,
  description VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS role_permissions (
  role_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
  FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS users (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(150),
  role_id INT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  last_login DATETIME NULL,
  FOREIGN KEY (role_id) REFERENCES roles(id)
);
CREATE TABLE IF NOT EXISTS user_sessions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  session_token_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  revoked_at DATETIME NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NULL,
  action VARCHAR(120) NOT NULL,
  target_type VARCHAR(100),
  target_id VARCHAR(150),
  details_json JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS ais_observation (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  observed_at DATETIME(3) NOT NULL,
  mmsi BIGINT NOT NULL,
  vessel_name VARCHAR(150),
  lat DOUBLE, lon DOUBLE, sog DOUBLE, cog DOUBLE, heading DOUBLE,
  operational_state VARCHAR(50), nearest_port VARCHAR(50), nearest_berth VARCHAR(80),
  distance_to_berth_nm DOUBLE, freshness_status VARCHAR(30), source_updated_at DATETIME(3) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ais_obs (observed_at,mmsi)
);
CREATE TABLE IF NOT EXISTS cctv_observation (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  observed_at DATETIME(3) NOT NULL,
  camera_id VARCHAR(100) NOT NULL,
  port VARCHAR(50) NOT NULL,
  car_queue INT DEFAULT 0, motor_queue INT DEFAULT 0,
  car_in_total BIGINT DEFAULT 0, car_out_total BIGINT DEFAULT 0,
  motor_in_total BIGINT DEFAULT 0, motor_out_total BIGINT DEFAULT 0,
  total_queue INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_cctv_obs (observed_at,camera_id)
);
CREATE TABLE IF NOT EXISTS prediction_history (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  predicted_at DATETIME(3) NOT NULL,
  mmsi BIGINT NOT NULL,
  origin_port VARCHAR(50), destination_port VARCHAR(50),
  eta_base_min DOUBLE, eta_corrected_min DOUBLE, estimated_arrival_at DATETIME(3) NULL,
  turnaround_base_min DOUBLE, turnaround_correction_min DOUBLE, estimated_departure_at DATETIME(3) NULL,
  ml1_model_id VARCHAR(150), ml2_model_id VARCHAR(150),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS actual_event (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  mmsi BIGINT NOT NULL,
  terminal VARCHAR(50), berth VARCHAR(80),
  actual_arrival_at DATETIME(3) NULL, actual_departure_at DATETIME(3) NULL,
  source VARCHAR(50) DEFAULT 'AIS', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS model_registry (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  model_type VARCHAR(20) NOT NULL,
  run_id VARCHAR(150) NOT NULL,
  algorithm VARCHAR(50) NOT NULL,
  artifact_path VARCHAR(500) NOT NULL,
  metrics_json JSON NULL, parameters_json JSON NULL, dataset_period VARCHAR(150),
  status VARCHAR(30) NOT NULL DEFAULT 'candidate',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_model_run (model_type,run_id)
);
CREATE TABLE IF NOT EXISTS model_activation_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  model_registry_id BIGINT NOT NULL,
  activated_by BIGINT NULL,
  activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deactivated_at DATETIME NULL,
  FOREIGN KEY (model_registry_id) REFERENCES model_registry(id),
  FOREIGN KEY (activated_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS queue_service_event (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  event_id VARCHAR(255) NOT NULL UNIQUE,
  occurred_at DATETIME(3) NOT NULL,
  port VARCHAR(50) NOT NULL,
  mmsi BIGINT NOT NULL,
  vessel_name VARCHAR(150),
  capacity_pce DOUBLE DEFAULT 0,
  queue_car_before INT DEFAULT 0,
  queue_motor_before INT DEFAULT 0,
  loaded_car INT DEFAULT 0,
  loaded_motor INT DEFAULT 0,
  loaded_pce DOUBLE DEFAULT 0,
  queue_car_after INT DEFAULT 0,
  queue_motor_after INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_qse_day_port (occurred_at,port)
);

CREATE TABLE IF NOT EXISTS daily_port_summary (
  service_date DATE NOT NULL,
  port VARCHAR(50) NOT NULL,
  first_observed_at DATETIME(3) NOT NULL,
  last_observed_at DATETIME(3) NOT NULL,
  car_in_start BIGINT DEFAULT 0,
  motor_in_start BIGINT DEFAULT 0,
  car_out_start BIGINT DEFAULT 0,
  motor_out_start BIGINT DEFAULT 0,
  loaded_car_start BIGINT DEFAULT 0,
  loaded_motor_start BIGINT DEFAULT 0,
  departure_count_start BIGINT DEFAULT 0,
  car_in_last BIGINT DEFAULT 0,
  motor_in_last BIGINT DEFAULT 0,
  car_out_last BIGINT DEFAULT 0,
  motor_out_last BIGINT DEFAULT 0,
  loaded_car_last BIGINT DEFAULT 0,
  loaded_motor_last BIGINT DEFAULT 0,
  departure_count_last BIGINT DEFAULT 0,
  car_in_day BIGINT DEFAULT 0,
  motor_in_day BIGINT DEFAULT 0,
  car_out_day BIGINT DEFAULT 0,
  motor_out_day BIGINT DEFAULT 0,
  loaded_car_day BIGINT DEFAULT 0,
  loaded_motor_day BIGINT DEFAULT 0,
  departures_day BIGINT DEFAULT 0,
  queue_car_end INT DEFAULT 0,
  queue_motor_end INT DEFAULT 0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY(service_date,port)
);
