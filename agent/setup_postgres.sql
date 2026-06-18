-- Setup script untuk AI Agent database
-- Run: psql -U postgres -f agent/setup_postgres.sql

CREATE USER agent_user WITH PASSWORD 'agent_pass';
CREATE DATABASE quant_agent OWNER agent_user;
GRANT ALL PRIVILEGES ON DATABASE quant_agent TO agent_user;

\connect quant_agent

-- Tables dibuat otomatis oleh agent/storage.py init_schema()
-- Script ini hanya setup user + db

SELECT 'Setup complete: quant_agent database ready.' AS status;
