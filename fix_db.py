import sqlite3
from config import Config

def upgrade_database():
    db_path = Config.DB_NAME
    print(f"--- Upgrading Database: {db_path} ---")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Ensure User Table (NEW for Multi-User Auth)
    try:
        cursor.execute("SELECT id FROM user LIMIT 1")
        print("User table already exists.")
        
        # Check if login_username column exists (NEW for username/email split)
        try:
            cursor.execute("SELECT login_username FROM user LIMIT 1")
            print("User table has login_username column.")
        except sqlite3.OperationalError:
            print("Adding login_username column to user table...", end=" ")
            cursor.execute("ALTER TABLE user ADD COLUMN login_username VARCHAR(200)")
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_user_login_username ON user (login_username)")
            print("Done.")
            
    except sqlite3.OperationalError:
        print("Creating 'user' table...", end=" ")
        cursor.execute("""
            CREATE TABLE user (
                id INTEGER PRIMARY KEY,
                email VARCHAR(200) NOT NULL UNIQUE,
                login_username VARCHAR(200),
                full_name VARCHAR(200),
                ews_server VARCHAR(200),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                is_admin BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME
            )
        """)
        cursor.execute("CREATE INDEX ix_user_email ON user (email)")
        cursor.execute("CREATE INDEX ix_user_login_username ON user (login_username)")
        print("Done.")
    
    # 2. Ensure Task Table Columns
    task_columns = [
        ("project", "VARCHAR(100) DEFAULT 'Unknown'"),
        ("tags_json", "TEXT DEFAULT '[]'"),
        ("domain_hint", "VARCHAR(100) DEFAULT 'Unknown'"),
        ("effort_estimate_hours", "FLOAT"),
        ("business_impact", "TEXT"),
        ("reply_acknowledge", "TEXT"),
        ("reply_done", "TEXT"),
        ("reply_delegate", "TEXT"),
        ("action_taken", "VARCHAR(50)"),
        ("received_at", "DATETIME"),
        ("auto_completed_at", "DATETIME"),
        ("completion_evidence", "TEXT"),
        ("triage_category", "VARCHAR(50) DEFAULT 'deep_work'"),
        ("delegated_to", "VARCHAR(200)"),
        ("delegated_at", "DATETIME"),
        ("ews_item_id", "VARCHAR(500)"),
        ("ews_change_key", "VARCHAR(500)"),
        ("priority", "VARCHAR(20) DEFAULT 'medium'")
    ]
    
    for col_name, col_type in task_columns:
        try:
            cursor.execute(f"SELECT {col_name} FROM task LIMIT 1")
        except sqlite3.OperationalError:
            print(f"Adding column to 'task': {col_name}...", end=" ")
            try:
                cursor.execute(f"ALTER TABLE task ADD COLUMN {col_name} {col_type}")
                print("Done.")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")

    # 3. Ensure Person Table
    try:
        cursor.execute("SELECT id FROM person LIMIT 1")
    except sqlite3.OperationalError:
        print("Creating 'person' table...", end=" ")
        cursor.execute("""
            CREATE TABLE person (
                id INTEGER PRIMARY KEY,
                email VARCHAR(200) NOT NULL UNIQUE,
                name VARCHAR(200),
                job_title VARCHAR(200),
                department VARCHAR(200),
                office_location VARCHAR(200),
                manager_name VARCHAR(200),
                interaction_count INTEGER DEFAULT 0,
                last_interaction_at DATETIME,
                manual_role VARCHAR(100),
                is_hidden BOOLEAN DEFAULT 0,
                projects_json TEXT DEFAULT '[]'
            )
        """)
        cursor.execute("CREATE INDEX ix_person_email ON person (email)")
        print("Done.")

    # 4. Ensure ApprovalRequest Table
    try:
        cursor.execute("SELECT id FROM approval_request LIMIT 1")
    except sqlite3.OperationalError:
        print("Creating 'approval_request' table...", end=" ")
        cursor.execute("""
            CREATE TABLE approval_request (
                id INTEGER PRIMARY KEY,
                source_email_id VARCHAR(300) NOT NULL UNIQUE,
                request_type VARCHAR(100) NOT NULL,
                summary TEXT NOT NULL,
                details_5w1h_json TEXT DEFAULT '{}',
                risk_level VARCHAR(20) DEFAULT 'Medium',
                ai_recommendation VARCHAR(20),
                confidence_score FLOAT DEFAULT 0.0,
                impact_analysis TEXT,
                conflict_flag TEXT,
                status VARCHAR(50) DEFAULT 'Pending',
                human_action_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ews_item_id VARCHAR(500)
            )
        """)
        cursor.execute("CREATE INDEX ix_approval_source_email ON approval_request (source_email_id)")
        cursor.execute("CREATE INDEX ix_approval_status ON approval_request (status)")
        print("Done.")

    # 5. Ensure ApprovalAuditLog Table
    try:
        cursor.execute("SELECT id FROM approval_audit_log LIMIT 1")
    except sqlite3.OperationalError:
        print("Creating 'approval_audit_log' table...", end=" ")
        cursor.execute("""
            CREATE TABLE approval_audit_log (
                id INTEGER PRIMARY KEY,
                approval_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(approval_id) REFERENCES approval_request(id)
            )
        """)
        print("Done.")

    conn.commit()
    conn.close()
    print("--- Database Upgrade Complete ---")
    
if __name__ == "__main__":
    upgrade_database()