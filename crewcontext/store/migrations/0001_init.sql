-- Initial schema migration for CrewContext  
-- Run: psql -d crewcontext -f 0001_init.sql  
  
CREATE TABLE IF NOT EXISTS events (  
    id TEXT PRIMARY KEY,  
    type TEXT NOT NULL,  
    process_id TEXT NOT NULL,  
    entity_id TEXT,  
    relation_id TEXT,  
    data JSONB NOT NULL,  
    agent_id TEXT NOT NULL,  
    scope TEXT DEFAULT 'default',  
    timestamp TIMESTAMPTZ DEFAULT NOW(),  
    metadata JSONB DEFAULT '{}'::jsonb  
); 
  
CREATE TABLE IF NOT EXISTS entities (  
    id TEXT PRIMARY KEY,  
    type TEXT NOT NULL,  
    attributes JSONB NOT NULL,  
    scope TEXT DEFAULT 'default',  
    valid_from TIMESTAMPTZ DEFAULT NOW(),  
    valid_to TIMESTAMPTZ,  
    created_at TIMESTAMPTZ DEFAULT NOW(),  
    provenance JSONB DEFAULT '{}'::jsonb  
);  
  
CREATE TABLE IF NOT EXISTS relations (  
    id TEXT PRIMARY KEY,  
    type TEXT NOT NULL,  
    from_entity_id TEXT NOT NULL,  
    to_entity_id TEXT NOT NULL,  
    attributes JSONB DEFAULT '{}'::jsonb,  
    scope TEXT DEFAULT 'default',  
    valid_from TIMESTAMPTZ DEFAULT NOW(),  
    valid_to TIMESTAMPTZ,  
    provenance JSONB DEFAULT '{}'::jsonb  
);  
  
CREATE INDEX IF NOT EXISTS idx_events_process ON events(process_id);  
CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id);  
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);  
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp); 
