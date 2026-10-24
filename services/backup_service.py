import os
import sys
import json
import time
import shutil
import base64
import logging
import datetime
import subprocess
from urllib.parse import urlparse
from config import Config
from database import (
    get_db_connection, get_db_cursor, query_one, query_all, execute,
    resync_all_sequences, close_connection_pool, reset_connection_pool
)

logger = logging.getLogger('inflow.backup')

BACKUP_DIR_NAME = 'backups'

def get_backup_dir():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backup_dir = os.path.join(base_dir, BACKUP_DIR_NAME)
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def get_uploads_base_dir():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    uploads_dir = os.path.join(base_dir, 'static', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    return uploads_dir

def find_pg_binary(binary_name):
    """
    Find pg_dump or psql executable across standard runtime, PATH, and common installation locations.
    """
    exe_name = f"{binary_name}.exe" if sys.platform == 'win32' else binary_name
    
    candidates = [
        # 1. inFlow runtime bundled PostgreSQL
        r"E:\odoo-ai-19.0\odoo-ai-19.0\runtime\pgsql\bin",
        # 2. Base directory relative pgsql if present
        os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), 'pgsql', 'bin'),
        # 3. Standard Windows PostgreSQL install paths
        r"C:\Program Files\PostgreSQL\17\bin",
        r"C:\Program Files\PostgreSQL\16\bin",
        r"C:\Program Files\PostgreSQL\15\bin",
        r"C:\Program Files\PostgreSQL\14\bin",
        r"C:\Program Files (x86)\PostgreSQL\16\bin",
        # 4. Standard Linux paths
        "/usr/lib/postgresql/16/bin",
        "/usr/lib/postgresql/15/bin",
        "/usr/bin"
    ]
    
    for c_dir in candidates:
        full_path = os.path.join(c_dir, exe_name)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            return full_path
            
    which_path = shutil.which(binary_name)
    if which_path:
        return which_path
        
    return None

def ensure_backup_tables():
    """
    Ensures backup_settings, backup_logs, and app_uploaded_files tables exist in the database.
    """
    try:
        execute("""
            CREATE TABLE IF NOT EXISTS backup_settings (
                id SERIAL PRIMARY KEY,
                auto_backup_enabled BOOLEAN DEFAULT FALSE,
                auto_backup_frequency VARCHAR(50) DEFAULT 'daily',
                auto_backup_time VARCHAR(10) DEFAULT '23:00',
                auto_save_gdrive BOOLEAN DEFAULT FALSE,
                gdrive_mode VARCHAR(50) DEFAULT 'local_sync',
                gdrive_local_path TEXT DEFAULT 'G:\\My Drive\\inFlow_Backups',
                gdrive_folder_id VARCHAR(255) DEFAULT '',
                gdrive_service_account_json TEXT DEFAULT '',
                retention_count INTEGER DEFAULT 15,
                last_backup_at TIMESTAMP WITH TIME ZONE,
                last_backup_status VARCHAR(50),
                last_backup_file TEXT,
                last_backup_size BIGINT DEFAULT 0,
                last_gdrive_sync_at TIMESTAMP WITH TIME ZONE,
                last_gdrive_sync_status VARCHAR(50),
                last_gdrive_error TEXT,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        execute("""
            CREATE TABLE IF NOT EXISTS backup_logs (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                filepath TEXT NOT NULL,
                file_size_bytes BIGINT DEFAULT 0,
                backup_type VARCHAR(50) DEFAULT 'manual',
                status VARCHAR(50) DEFAULT 'completed',
                error_message TEXT,
                gdrive_status VARCHAR(50) DEFAULT 'none',
                gdrive_details TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        execute("""
            CREATE TABLE IF NOT EXISTS app_uploaded_files (
                id SERIAL PRIMARY KEY,
                rel_path VARCHAR(500) UNIQUE NOT NULL,
                file_data BYTEA NOT NULL,
                file_size BIGINT NOT NULL,
                mtime DOUBLE PRECISION DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_app_uploaded_files_rel_path ON app_uploaded_files(rel_path);
        """)
        
        row = query_one("SELECT id FROM backup_settings LIMIT 1")
        if not row:
            execute("""
                INSERT INTO backup_settings (
                    auto_backup_enabled, auto_backup_frequency, auto_backup_time,
                    auto_save_gdrive, gdrive_mode, gdrive_local_path, retention_count
                ) VALUES (
                    FALSE, 'daily', '23:00',
                    FALSE, 'local_sync', 'G:\\My Drive\\inFlow_Backups', 15
                );
            """)
    except Exception as e:
        logger.error(f"Error ensuring backup tables: {e}")

def sync_disk_uploads_to_db(uploads_root=None):
    """
    Scans the static/uploads directory and syncs all uploaded images/files
    into the PostgreSQL app_uploaded_files table so they are included in pg_dump SQL backups.
    Optimized to only read/upsert files whose size or mtime has changed.
    """
    import psycopg2
    ensure_backup_tables()
    
    if not uploads_root:
        uploads_root = get_uploads_base_dir()
    uploads_root = os.path.abspath(uploads_root)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    if not os.path.exists(uploads_root):
        return {'synced': 0, 'total': 0, 'bytes': 0}
        
    try:
        db_records = query_all("SELECT rel_path, file_size, mtime FROM app_uploaded_files;")
        db_map = {r['rel_path']: (r['file_size'], r.get('mtime') or 0.0) for r in db_records} if db_records else {}
    except Exception as e:
        logger.warning(f"Could not read app_uploaded_files metadata: {e}")
        db_map = {}
        
    synced_count = 0
    total_files = 0
    total_bytes = 0
    
    try:
        with get_db_cursor(commit=True) as cur:
            for root, dirs, files in os.walk(uploads_root):
                for f in files:
                    if f.startswith('.') or f.endswith('.tmp') or f.endswith('.temp'):
                        continue
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, base_dir).replace('\\', '/')
                    
                    try:
                        stat = os.stat(full_path)
                        f_size = stat.st_size
                        f_mtime = stat.st_mtime
                        total_files += 1
                        total_bytes += f_size
                        
                        db_info = db_map.get(rel_path)
                        if db_info and db_info[0] == f_size and abs(db_info[1] - f_mtime) < 1.0:
                            continue
                            
                        with open(full_path, 'rb') as fp:
                            data = fp.read()
                            
                        cur.execute("""
                            INSERT INTO app_uploaded_files (rel_path, file_data, file_size, mtime, updated_at)
                            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (rel_path) DO UPDATE SET
                                file_data = EXCLUDED.file_data,
                                file_size = EXCLUDED.file_size,
                                mtime = EXCLUDED.mtime,
                                updated_at = CURRENT_TIMESTAMP;
                        """, (rel_path, psycopg2.Binary(data), f_size, f_mtime))
                        synced_count += 1
                    except Exception as fe:
                        logger.warning(f"Error syncing uploaded file {rel_path}: {fe}")
                        
        logger.info(f"Disk to DB upload sync completed: {synced_count} updated, {total_files} total files ({format_file_size(total_bytes)})")
        return {'synced': synced_count, 'total': total_files, 'bytes': total_bytes}
    except Exception as e:
        logger.error(f"Error syncing uploads to DB: {e}", exc_info=True)
        return {'synced': synced_count, 'total': total_files, 'bytes': total_bytes, 'error': str(e)}

def sync_file_to_db(rel_path, file_data=None):
    """
    Syncs a single uploaded file into app_uploaded_files table immediately.
    """
    import psycopg2
    try:
        ensure_backup_tables()
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        clean_rel = rel_path.lstrip('/').replace('\\', '/')
        if not clean_rel.startswith('static/'):
            clean_rel = f"static/uploads/{clean_rel.split('static/uploads/')[-1]}"
            
        full_path = os.path.join(base_dir, clean_rel.replace('/', os.sep))
        
        if file_data is None:
            if not os.path.exists(full_path):
                return False
            with open(full_path, 'rb') as fp:
                file_data = fp.read()
                
        stat = os.stat(full_path) if os.path.exists(full_path) else None
        f_size = len(file_data)
        f_mtime = stat.st_mtime if stat else time.time()
        
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO app_uploaded_files (rel_path, file_data, file_size, mtime, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (rel_path) DO UPDATE SET
                    file_data = EXCLUDED.file_data,
                    file_size = EXCLUDED.file_size,
                    mtime = EXCLUDED.mtime,
                    updated_at = CURRENT_TIMESTAMP;
            """, (clean_rel, psycopg2.Binary(file_data), f_size, f_mtime))
        return True
    except Exception as e:
        logger.warning(f"Could not sync file {rel_path} to DB: {e}")
        return False

def restore_db_uploaded_files_to_disk(base_dir=None):
    """
    Restores all uploaded images and files stored in PostgreSQL app_uploaded_files table
    back to the local filesystem (static/uploads/...).
    Returns count of files restored.
    """
    if not base_dir:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        
    restored_count = 0
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = 'app_uploaded_files'
                );
            """)
            row = cur.fetchone()
            has_table = row['exists'] if row else False
            if not has_table:
                logger.info("No app_uploaded_files table found in database. Skipping disk file recovery.")
                return 0
                
            cur.execute("SELECT rel_path, file_data, file_size, mtime FROM app_uploaded_files;")
            rows = cur.fetchall()
            
            for r in rows:
                rel_path = r['rel_path']
                file_data = r['file_data']
                if not file_data:
                    continue
                    
                target_path = os.path.join(base_dir, rel_path.replace('/', os.sep))
                target_dir = os.path.dirname(target_path)
                os.makedirs(target_dir, exist_ok=True)
                
                # Check if file exists with matching size
                if os.path.exists(target_path) and os.path.getsize(target_path) == len(file_data):
                    continue
                    
                with open(target_path, 'wb') as fp:
                    fp.write(bytes(file_data))
                    
                if r.get('mtime'):
                    try:
                        os.utime(target_path, (time.time(), float(r['mtime'])))
                    except Exception:
                        pass
                restored_count += 1
                
        logger.info(f"Disk file restoration completed: {restored_count} images/files written to disk.")
        return restored_count
    except Exception as e:
        logger.error(f"Error restoring files from DB to disk: {e}", exc_info=True)
        return restored_count


def get_backup_settings():
    ensure_backup_tables()
    settings = query_one("SELECT * FROM backup_settings LIMIT 1")
    if not settings:
        return {
            'auto_backup_enabled': False,
            'auto_backup_frequency': 'daily',
            'auto_backup_time': '23:00',
            'auto_save_gdrive': False,
            'gdrive_mode': 'local_sync',
            'gdrive_local_path': r'G:\My Drive\inFlow_Backups',
            'gdrive_folder_id': '',
            'gdrive_service_account_json': '',
            'retention_count': 15,
            'last_backup_at': None,
            'last_backup_status': None,
            'last_backup_file': None,
            'last_backup_size': 0,
            'last_gdrive_sync_at': None,
            'last_gdrive_sync_status': None,
            'last_gdrive_error': None
        }
    return dict(settings)

def save_backup_settings(data):
    ensure_backup_tables()
    execute("""
        UPDATE backup_settings SET
            auto_backup_enabled = %s,
            auto_backup_frequency = %s,
            auto_backup_time = %s,
            auto_save_gdrive = %s,
            gdrive_mode = %s,
            gdrive_local_path = %s,
            gdrive_folder_id = %s,
            gdrive_service_account_json = %s,
            retention_count = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = (SELECT id FROM backup_settings LIMIT 1);
    """, (
        bool(data.get('auto_backup_enabled')),
        data.get('auto_backup_frequency', 'daily'),
        data.get('auto_backup_time', '23:00'),
        bool(data.get('auto_save_gdrive')),
        data.get('gdrive_mode', 'local_sync'),
        data.get('gdrive_local_path', r'G:\My Drive\inFlow_Backups').strip(),
        data.get('gdrive_folder_id', '').strip(),
        data.get('gdrive_service_account_json', '').strip(),
        int(data.get('retention_count', 15) or 15)
    ))
    return get_backup_settings()

def format_file_size(size_bytes):
    if size_bytes is None:
        return "0 B"
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0 or unit == 'TB':
            return f"{size:.2f} {unit}" if unit in ['MB', 'GB'] else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.2f} MB"

def list_backups():
    """
    List all .sql backup files in the backup directory with metadata.
    """
    b_dir = get_backup_dir()
    ensure_backup_tables()
    
    logs = query_all("SELECT * FROM backup_logs ORDER BY id DESC")
    log_map = {l['filename']: l for l in logs} if logs else {}
    
    backups = []
    if os.path.exists(b_dir):
        for fname in os.listdir(b_dir):
            if fname.lower().endswith('.sql'):
                fpath = os.path.join(b_dir, fname)
                try:
                    stat = os.stat(fpath)
                    mod_dt = datetime.datetime.fromtimestamp(stat.st_mtime)
                    log_entry = log_map.get(fname, {})
                    
                    is_safety = fname.startswith('pre_restore_')
                    
                    backups.append({
                        'filename': fname,
                        'filepath': fpath,
                        'size_bytes': stat.st_size,
                        'formatted_size': format_file_size(stat.st_size),
                        'modified_at': mod_dt,
                        'date_display': mod_dt.strftime('%d %b %Y, %H:%M:%S'),
                        'date_iso': mod_dt.isoformat(),
                        'is_safety': is_safety,
                        'gdrive_status': log_entry.get('gdrive_status', 'none'),
                        'gdrive_details': log_entry.get('gdrive_details', ''),
                        'backup_type': log_entry.get('backup_type', 'safety' if is_safety else 'manual')
                    })
                except Exception as e:
                    logger.warning(f"Error inspecting backup file {fname}: {e}")
                    
    backups.sort(key=lambda x: x['modified_at'], reverse=True)
    return backups

def create_backup(backup_type='manual', note='', save_to_gdrive=None):
    """
    Creates a PostgreSQL database backup as a .sql file with date/time in the filename.
    Automatically syncs all uploaded images into the database before export so the SQL backup
    fully contains all database records AND all uploaded images and attachments.
    Optionally saves automatically to Google Drive.
    """
    ensure_backup_tables()
    b_dir = get_backup_dir()
    settings = get_backup_settings()
    
    # 1. Sync all disk uploads into PostgreSQL app_uploaded_files table before export
    img_sync = {'synced': 0, 'total': 0, 'bytes': 0}
    try:
        img_sync = sync_disk_uploads_to_db()
    except Exception as img_err:
        logger.warning(f"Image sync before backup warning: {img_err}")
    
    # Filename format with full date and time: inflow_premium_backup_YYYY-MM-DD_HHMMSS.sql
    now = datetime.datetime.now()
    date_str = now.strftime('%Y-%m-%d_%H%M%S')
    
    if backup_type == 'pre_restore':
        filename = f"pre_restore_safety_backup_{date_str}.sql"
    else:
        filename = f"inflow_premium_backup_{date_str}.sql"
        
    out_file = os.path.join(b_dir, filename)
    
    pg_dump_bin = find_pg_binary('pg_dump')
    if not pg_dump_bin:
        err = "pg_dump binary not found on server. Please check PostgreSQL runtime installation."
        logger.error(err)
        return {'success': False, 'error': err}
        
    # Database connection parameters from Config
    db_host = getattr(Config, 'PG_HOST', '127.0.0.1')
    db_port = str(getattr(Config, 'PG_PORT', 5432))
    db_user = getattr(Config, 'PG_USER', 'odoo')
    db_name = getattr(Config, 'PG_DATABASE', 'inflow_premium')
    db_pass = getattr(Config, 'PG_PASSWORD', 'odoo')
    
    env = os.environ.copy()
    env['PGPASSWORD'] = str(db_pass or '')
    if getattr(Config, 'PG_SSLMODE', None):
        env['PGSSLMODE'] = str(Config.PG_SSLMODE)
    
    cmd = [
        pg_dump_bin,
        '-h', str(db_host),
        '-p', str(db_port),
        '-U', str(db_user),
        '-d', str(db_name),
        '--no-owner',
        '--no-acl',
        '--clean',
        '--if-exists',
        '-f', out_file
    ]
    
    logger.info(f"Starting PostgreSQL full backup (data + {img_sync.get('total', 0)} images) to {out_file}...")
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            err_msg = res.stderr or "Unknown error running pg_dump."
            logger.error(f"Database backup failed: {err_msg}")
            return {'success': False, 'error': f"pg_dump error (code {res.returncode}): {err_msg}"}
            
        if not os.path.exists(out_file) or os.path.getsize(out_file) == 0:
            err_msg = "Backup file was not created or is empty."
            logger.error(err_msg)
            return {'success': False, 'error': err_msg}
            
        file_size = os.path.getsize(out_file)
        formatted_size = format_file_size(file_size)
        logger.info(f"Database backup SUCCESSFUL: {filename} ({formatted_size}, {img_sync.get('total', 0)} images)")
        
        # Decide if we save to Google Drive:
        should_save_gdrive = save_to_gdrive if save_to_gdrive is not None else settings.get('auto_save_gdrive', False)
        gdrive_res = None
        gdrive_status = 'none'
        gdrive_details = ''
        
        if should_save_gdrive:
            logger.info(f"Auto-saving backup {filename} to Google Drive...")
            gdrive_res = save_backup_to_gdrive(out_file, filename, settings)
            if gdrive_res.get('success'):
                gdrive_status = 'synced'
                gdrive_details = gdrive_res.get('message', 'Uploaded successfully')
            else:
                gdrive_status = 'failed'
                gdrive_details = gdrive_res.get('error', 'Google Drive sync failed')
                
        # Record into backup_logs
        try:
            execute("""
                INSERT INTO backup_logs (
                    filename, filepath, file_size_bytes, backup_type, status,
                    gdrive_status, gdrive_details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (
                filename, out_file, file_size, backup_type, 'completed',
                gdrive_status, gdrive_details
            ))
            
            # Update backup_settings last backup info
            execute("""
                UPDATE backup_settings SET
                    last_backup_at = CURRENT_TIMESTAMP,
                    last_backup_status = 'success',
                    last_backup_file = %s,
                    last_backup_size = %s,
                    last_gdrive_sync_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE last_gdrive_sync_at END,
                    last_gdrive_sync_status = CASE WHEN %s THEN %s ELSE last_gdrive_sync_status END,
                    last_gdrive_error = CASE WHEN %s THEN %s ELSE last_gdrive_error END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (SELECT id FROM backup_settings LIMIT 1);
            """, (
                filename, file_size,
                should_save_gdrive,
                should_save_gdrive, gdrive_status,
                should_save_gdrive, gdrive_details if gdrive_status == 'failed' else None
            ))
        except Exception as log_err:
            logger.warning(f"Could not record backup log: {log_err}")
            
        # Clean up old backups according to retention count
        clean_old_backups(settings.get('retention_count', 15))
        
        return {
            'success': True,
            'filename': filename,
            'filepath': out_file,
            'size_bytes': file_size,
            'formatted_size': formatted_size,
            'date_str': date_str,
            'images_count': img_sync.get('total', 0),
            'images_synced': img_sync.get('synced', 0),
            'gdrive_saved': should_save_gdrive,
            'gdrive_result': gdrive_res
        }
        
    except subprocess.TimeoutExpired:
        err = "pg_dump timed out after 300 seconds."
        logger.error(err)
        return {'success': False, 'error': err}
    except Exception as e:
        logger.error(f"Exception during backup creation: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}

def restore_backup(sql_filepath, create_safety_backup=True):
    """
    Restores the PostgreSQL database and all uploaded images from a .sql (or .zip) backup file.
    Creates an automatic safety backup before restoring if requested.
    Isolates active connections, cleans existing schema public to prevent foreign-key drop failures,
    executes psql, re-initializes connection pool, resyncs serial sequences,
    and extracts all uploaded images from app_uploaded_files back to disk.
    """
    import zipfile
    import tempfile
    import psycopg2
    
    if not os.path.exists(sql_filepath):
        return {'success': False, 'error': f"Backup file not found at: {sql_filepath}"}
        
    if os.path.getsize(sql_filepath) == 0:
        return {'success': False, 'error': "Backup file is empty (0 bytes)."}
        
    psql_bin = find_pg_binary('psql')
    if not psql_bin:
        return {'success': False, 'error': "psql executable not found on server."}
        
    temp_extract_dir = None
    actual_sql_path = sql_filepath
    
    # 1. Handle .zip archive if uploaded
    if zipfile.is_zipfile(sql_filepath) or sql_filepath.lower().endswith('.zip'):
        try:
            temp_extract_dir = tempfile.mkdtemp(prefix='inflow_restore_zip_')
            with zipfile.ZipFile(sql_filepath, 'r') as z:
                z.extractall(temp_extract_dir)
                
            sql_candidates = []
            for root, dirs, files in os.walk(temp_extract_dir):
                for f in files:
                    if f.lower().endswith('.sql'):
                        sql_candidates.append(os.path.join(root, f))
                        
            if not sql_candidates:
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
                return {'success': False, 'error': "No .sql database file found inside the uploaded zip archive."}
                
            sql_candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
            actual_sql_path = sql_candidates[0]
            
            # If the zip has an uploads folder, extract to static/uploads
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            uploads_dest = os.path.join(base_dir, 'static', 'uploads')
            for check_name in ('uploads', 'static/uploads'):
                check_path = os.path.join(temp_extract_dir, check_name.replace('/', os.sep))
                if os.path.exists(check_path) and os.path.isdir(check_path):
                    for r, d, f_list in os.walk(check_path):
                        for fn in f_list:
                            src_fp = os.path.join(r, fn)
                            rel_fn = os.path.relpath(src_fp, check_path)
                            dest_fp = os.path.join(uploads_dest, rel_fn)
                            os.makedirs(os.path.dirname(dest_fp), exist_ok=True)
                            shutil.copy2(src_fp, dest_fp)
        except Exception as ze:
            if temp_extract_dir:
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            return {'success': False, 'error': f"Failed to extract zip archive: {ze}"}
            
    safety_res = None
    if create_safety_backup:
        logger.info("Generating automatic pre-restore safety backup...")
        try:
            safety_res = create_backup(backup_type='pre_restore', note='Auto pre-restore safety snapshot', save_to_gdrive=False)
            if not safety_res.get('success'):
                logger.warning(f"Pre-restore safety backup could not be completed: {safety_res.get('error')}")
        except Exception as sb_err:
            logger.warning(f"Pre-restore safety backup exception: {sb_err}")
            
    db_host = getattr(Config, 'PG_HOST', '127.0.0.1')
    db_port = str(getattr(Config, 'PG_PORT', 5432))
    db_user = getattr(Config, 'PG_USER', 'odoo')
    db_name = getattr(Config, 'PG_DATABASE', 'inflow_premium')
    db_pass = getattr(Config, 'PG_PASSWORD', 'odoo')
    
    # 2. Close active connection pool to avoid stale connections or lock conflicts
    try:
        close_connection_pool()
    except Exception as cp_err:
        logger.warning(f"Connection pool close note: {cp_err}")
        
    # 3. Terminate other connections and drop/recreate public schema for a 100% clean restore
    try:
        clean_conn = psycopg2.connect(
            host=str(db_host),
            port=str(db_port),
            user=str(db_user),
            password=str(db_pass or ''),
            dbname=str(db_name),
            connect_timeout=15
        )
        clean_conn.autocommit = True
        with clean_conn.cursor() as cur:
            # Terminate other sessions
            cur.execute("""
                SELECT pg_terminate_backend(pid) 
                FROM pg_stat_activity 
                WHERE datname = %s AND pid <> pg_backend_pid();
            """, (str(db_name),))
            # Clean schema public
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
            cur.execute("GRANT ALL ON SCHEMA public TO public;")
        clean_conn.close()
    except Exception as prep_err:
        logger.warning(f"Clean database preparation note: {prep_err}")
        
    env = os.environ.copy()
    env['PGPASSWORD'] = str(db_pass or '')
    if getattr(Config, 'PG_SSLMODE', None):
        env['PGSSLMODE'] = str(Config.PG_SSLMODE)
        
    cmd = [
        psql_bin,
        '-h', str(db_host),
        '-p', str(db_port),
        '-U', str(db_user),
        '-d', str(db_name),
        '-f', actual_sql_path
    ]
    
    logger.info(f"Starting database restoration from {actual_sql_path}...")
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        
        # Verify psql returncode
        if res.returncode != 0:
            err_msg = res.stderr or res.stdout or f"psql exited with code {res.returncode}"
            logger.error(f"psql restore failed: {err_msg}")
            reset_connection_pool()
            if temp_extract_dir:
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            return {'success': False, 'error': f"Database restore failed: {err_msg}"}
            
        # 4. Re-initialize connection pool
        reset_connection_pool()
        
        # 5. Synchronize all order & ID sequences
        try:
            resync_all_sequences()
        except Exception as seq_err:
            logger.warning(f"Post-restore sequence sync warning: {seq_err}")
            
        # 6. Extract all uploaded images from database back to disk
        restored_images = 0
        try:
            restored_images = restore_db_uploaded_files_to_disk()
        except Exception as img_err:
            logger.warning(f"Post-restore image recovery warning: {img_err}")
            
        # 7. Ensure backup tables & record restore in logs
        try:
            ensure_backup_tables()
            execute("""
                INSERT INTO backup_logs (
                    filename, filepath, file_size_bytes, backup_type, status, error_message
                ) VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                os.path.basename(sql_filepath), sql_filepath, os.path.getsize(sql_filepath),
                'restore', 'completed', f'Restored database with {restored_images} images'
            ))
        except Exception as log_err:
            logger.warning(f"Could not log restore event: {log_err}")
            
        if temp_extract_dir:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            
        logger.info(f"Database restoration completed successfully! Restored {restored_images} images.")
        return {
            'success': True,
            'message': f"Database successfully restored from backup! {restored_images} uploaded images recovered.",
            'restored_images': restored_images,
            'safety_backup': safety_res.get('filename') if safety_res else None,
            'stdout_tail': (res.stdout or '')[-300:] if res.stdout else ''
        }
    except subprocess.TimeoutExpired:
        reset_connection_pool()
        if temp_extract_dir:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
        return {'success': False, 'error': "psql restoration timed out after 600 seconds."}
    except Exception as e:
        reset_connection_pool()
        if temp_extract_dir:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
        logger.error(f"Error during restore: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def clean_old_backups(retention_count=15):
    """
    Keeps the latest N backups, deleting older backups to preserve disk space.
    Safety backups (pre_restore_) are preserved separately.
    """
    try:
        b_dir = get_backup_dir()
        if not os.path.exists(b_dir):
            return
            
        files = []
        for f in os.listdir(b_dir):
            if f.lower().endswith('.sql') and not f.startswith('pre_restore_'):
                fp = os.path.join(b_dir, f)
                files.append((fp, os.path.getmtime(fp)))
                
        files.sort(key=lambda x: x[1], reverse=True)
        
        if len(files) > retention_count:
            for fp, _ in files[retention_count:]:
                try:
                    os.remove(fp)
                    logger.info(f"Retention policy removed old backup: {os.path.basename(fp)}")
                except Exception as e:
                    logger.warning(f"Could not remove old backup {fp}: {e}")
    except Exception as e:
        logger.warning(f"Error cleaning old backups: {e}")

# =========================================================================
# Google Drive Integration: Local Folder Sync & Cloud Direct API
# =========================================================================

def save_backup_to_gdrive(filepath, filename, settings=None):
    """
    Saves the backup file to Google Drive using either:
    1) Local Sync Folder (Google Drive for Desktop)
    2) Direct Cloud API (Service Account OAuth2 & Resumable Upload)
    """
    if not settings:
        settings = get_backup_settings()
        
    mode = settings.get('gdrive_mode', 'local_sync')
    
    if mode == 'local_sync':
        return _save_to_local_gdrive_folder(filepath, filename, settings.get('gdrive_local_path'))
    elif mode == 'cloud_api':
        return _upload_to_gdrive_cloud_api(
            filepath,
            filename,
            settings.get('gdrive_service_account_json'),
            settings.get('gdrive_folder_id')
        )
    else:
        return {'success': False, 'error': f"Unknown Google Drive mode: {mode}"}

def _save_to_local_gdrive_folder(filepath, filename, target_dir):
    """
    Copies the dated backup .sql file to a local Google Drive sync directory.
    Google Drive for Desktop automatically syncs this directory to Google Drive Cloud.
    """
    if not target_dir or not str(target_dir).strip():
        return {'success': False, 'error': "Google Drive folder path is empty. Please enter a valid sync path."}
        
    target_dir = os.path.expandvars(os.path.expanduser(str(target_dir).strip()))
    
    try:
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, filename)
        shutil.copy2(filepath, dest_path)
        
        if os.path.exists(dest_path) and os.path.getsize(dest_path) == os.path.getsize(filepath):
            logger.info(f"Backup copied to Google Drive sync folder: {dest_path}")
            return {
                'success': True,
                'mode': 'local_sync',
                'dest_path': dest_path,
                'message': f"Saved to Google Drive sync folder ({dest_path})"
            }
        else:
            return {'success': False, 'error': "File copied but destination verification failed."}
    except Exception as e:
        logger.error(f"Failed to copy to Google Drive sync directory '{target_dir}': {e}")
        return {'success': False, 'error': f"Could not write to Google Drive folder: {e}"}

def _get_gdrive_oauth_token(service_account_dict):
    """
    Generates a Google OAuth2 access token from a Service Account JSON dictionary
    using standard RS256 JWT assertion. No external google-auth library needed.
    """
    import requests
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    
    client_email = service_account_dict.get('client_email')
    private_key_raw = service_account_dict.get('private_key')
    token_uri = service_account_dict.get('token_uri', 'https://oauth2.googleapis.com/token')
    
    if not client_email or not private_key_raw:
        raise ValueError("Service Account JSON must contain 'client_email' and 'private_key'")
        
    private_key = load_pem_private_key(private_key_raw.encode('utf-8'), password=None)
    
    now = int(time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    payload = {
        'iss': client_email,
        'scope': 'https://www.googleapis.com/auth/drive.file',
        'aud': token_uri,
        'exp': now + 3600,
        'iat': now
    }
    
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=')
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=')
    signing_input = h_b64 + b'.' + p_b64
    
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b'=')
    jwt_token = (signing_input + b'.' + sig_b64).decode('utf-8')
    
    token_resp = requests.post(
        token_uri,
        data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': jwt_token
        },
        timeout=20
    )
    
    if token_resp.status_code != 200:
        raise RuntimeError(f"Google OAuth token request failed ({token_resp.status_code}): {token_resp.text}")
        
    return token_resp.json().get('access_token')

def _upload_to_gdrive_cloud_api(filepath, filename, sa_json_str, folder_id=None):
    """
    Directly uploads a file to Google Drive via Google Drive API v3 (Resumable Upload).
    Works for any file size and streaming.
    """
    import requests
    
    if not sa_json_str or not sa_json_str.strip():
        return {'success': False, 'error': "Google Service Account JSON credentials are not configured."}
        
    try:
        sa_dict = json.loads(sa_json_str.strip())
    except Exception as e:
        return {'success': False, 'error': f"Invalid JSON credentials format: {e}"}
        
    try:
        access_token = _get_gdrive_oauth_token(sa_dict)
    except Exception as e:
        return {'success': False, 'error': f"Failed to authenticate with Google: {e}"}
        
    file_size = os.path.getsize(filepath)
    folder_id = folder_id.strip() if folder_id else ''
    
    # Metadata for file creation
    metadata = {'name': filename}
    if folder_id:
        metadata['parents'] = [folder_id]
        
    try:
        # Step 1: Initiate Resumable Upload
        init_url = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable'
        init_headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'application/sql',
            'X-Upload-Content-Length': str(file_size)
        }
        
        init_resp = requests.post(init_url, headers=init_headers, data=json.dumps(metadata), timeout=30)
        if init_resp.status_code not in (200, 201):
            return {'success': False, 'error': f"Google Drive upload initiation failed ({init_resp.status_code}): {init_resp.text}"}
            
        upload_location = init_resp.headers.get('Location')
        if not upload_location:
            return {'success': False, 'error': "Google Drive API did not return an upload location."}
            
        # Step 2: Stream file content to upload location
        with open(filepath, 'rb') as f:
            upload_headers = {
                'Content-Length': str(file_size),
                'Content-Type': 'application/sql'
            }
            upload_resp = requests.put(upload_location, headers=upload_headers, data=f, timeout=300)
            
        if upload_resp.status_code in (200, 201):
            res_data = upload_resp.json()
            file_id = res_data.get('id')
            logger.info(f"File uploaded to Google Drive API successfully! File ID: {file_id}")
            return {
                'success': True,
                'mode': 'cloud_api',
                'file_id': file_id,
                'filename': filename,
                'message': f"Uploaded directly to Google Drive (ID: {file_id})"
            }
        else:
            return {'success': False, 'error': f"Upload failed ({upload_resp.status_code}): {upload_resp.text}"}
            
    except Exception as e:
        logger.error(f"Google Drive API upload error: {e}", exc_info=True)
        return {'success': False, 'error': f"Google Drive API upload exception: {e}"}

def test_gdrive_config(mode=None, local_path=None, sa_json=None, folder_id=None):
    """
    Validates Google Drive configuration settings.
    """
    if mode is None:
        settings = get_backup_settings()
        mode = settings.get('gdrive_mode', 'local_sync')
        local_path = settings.get('gdrive_local_path')
        sa_json = settings.get('gdrive_service_account_json')
        folder_id = settings.get('gdrive_folder_id')
        
    if mode == 'local_sync':
        if not local_path or not str(local_path).strip():
            return {'success': False, 'error': 'Google Drive folder path cannot be blank.'}
        p = os.path.expandvars(os.path.expanduser(str(local_path).strip()))
        try:
            os.makedirs(p, exist_ok=True)
            test_file = os.path.join(p, '.inflow_probe_test.tmp')
            with open(test_file, 'w') as f:
                f.write('probe')
            os.remove(test_file)
            return {'success': True, 'message': f'Ready! Local folder "{p}" exists and is writable by inFlow.'}
        except Exception as e:
            return {'success': False, 'error': f'Cannot write to folder "{p}": {e}'}
            
    elif mode == 'cloud_api':
        if not sa_json or not sa_json.strip():
            return {'success': False, 'error': 'Service Account JSON key is missing.'}
        try:
            sa_dict = json.loads(sa_json.strip())
            token = _get_gdrive_oauth_token(sa_dict)
            client_email = sa_dict.get('client_email', 'Service Account')
            
            # If folder_id is provided, verify folder access
            if folder_id and folder_id.strip():
                import requests
                f_resp = requests.get(
                    f'https://www.googleapis.com/drive/v3/files/{folder_id.strip()}?fields=id,name,capabilities',
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=15
                )
                if f_resp.status_code == 200:
                    folder_name = f_resp.json().get('name', 'Google Drive Folder')
                    return {'success': True, 'message': f'Connected to Google Drive as {client_email}! Folder "{folder_name}" verified.'}
                else:
                    return {'success': False, 'error': f'Connected as {client_email}, but cannot access Folder ID "{folder_id}": {f_resp.text}'}
                    
            return {'success': True, 'message': f'Connected to Google Drive API successfully as {client_email}!'}
        except Exception as e:
            return {'success': False, 'error': f'Google Drive API connection test failed: {e}'}
            
    return {'success': False, 'error': f'Invalid mode: {mode}'}

# =========================================================================
# Automatic Background Backup Scheduler
# =========================================================================

_scheduler_running = False

def check_and_run_scheduled_backup():
    """
    Checks if a scheduled backup is due and runs it.
    """
    try:
        settings = get_backup_settings()
        if not settings.get('auto_backup_enabled'):
            return
            
        freq = settings.get('auto_backup_frequency', 'daily')
        sched_time_str = settings.get('auto_backup_time', '23:00')
        last_backup_at = settings.get('last_backup_at')
        
        now = datetime.datetime.now()
        
        # Check minimum interval since last backup
        interval_hours = {
            'every_6h': 6,
            'every_12h': 12,
            'daily': 23,
            'weekly': 160
        }.get(freq, 23)
        
        if last_backup_at:
            if isinstance(last_backup_at, str):
                try:
                    last_backup_at = datetime.datetime.fromisoformat(last_backup_at.replace('Z', '+00:00'))
                except Exception:
                    last_backup_at = None
            if last_backup_at:
                diff = now - (last_backup_at.replace(tzinfo=None) if hasattr(last_backup_at, 'tzinfo') and last_backup_at.tzinfo else last_backup_at)
                if diff.total_seconds() < interval_hours * 3600:
                    return # Not due yet
                    
        # If daily or weekly, check if current time matches scheduled hour
        if freq in ('daily', 'weekly'):
            try:
                target_hour, target_min = map(int, sched_time_str.split(':'))
                if now.hour != target_hour or abs(now.minute - target_min) > 15:
                    return # Not within time window
            except Exception:
                pass
                
        logger.info(f"Triggering scheduled automated backup (frequency={freq})...")
        res = create_backup(backup_type='scheduled', note=f'Automatic {freq} scheduled backup')
        if res.get('success'):
            logger.info(f"Scheduled backup completed: {res.get('filename')}")
        else:
            logger.error(f"Scheduled backup failed: {res.get('error')}")
            
    except Exception as e:
        logger.error(f"Error in backup scheduler loop: {e}", exc_info=True)

def start_backup_scheduler():
    """
    Spawns a background thread that periodically checks for scheduled backups.
    """
    global _scheduler_running
    if _scheduler_running:
        return
        
    import threading
    _scheduler_running = True
    
    def _loop():
        logger.info("inFlow Premium automated backup scheduler thread started.")
        # Initial brief wait on startup
        time.sleep(30)
        while True:
            try:
                check_and_run_scheduled_backup()
            except Exception as e:
                logger.warning(f"Scheduler tick error: {e}")
            time.sleep(300) # Check every 5 minutes
            
    t = threading.Thread(target=_loop, daemon=True, name="inflow_backup_scheduler")
    t.start()
