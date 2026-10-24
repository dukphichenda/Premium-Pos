import os
import sys
import time
import shutil
import tempfile
import unittest
import psycopg2
from config import Config
from app import create_app
from database import query_one, query_all, execute
from services.backup_service import (
    ensure_backup_tables,
    sync_disk_uploads_to_db,
    sync_file_to_db,
    restore_db_uploaded_files_to_disk,
    create_backup,
    restore_backup,
    list_backups,
    find_pg_binary,
    get_backup_dir
)

class TestBackupAndRestoreWithImages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()
        ensure_backup_tables()

    def test_01_ensure_backup_tables(self):
        """Verify that app_uploaded_files and backup tables exist"""
        ensure_backup_tables()
        row = query_one("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'app_uploaded_files'
            );
        """)
        self.assertTrue(row['exists'])

    def test_02_sync_single_file_to_db(self):
        """Verify sync_file_to_db stores binary file data into app_uploaded_files"""
        sample_path = "static/uploads/test_sample_img.jpg"
        sample_data = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xFF\xDB\x00C\x00test_binary_content_123"
        
        ok = sync_file_to_db(sample_path, sample_data)
        self.assertTrue(ok)
        
        row = query_one("SELECT rel_path, file_size, file_data FROM app_uploaded_files WHERE rel_path = %s", (sample_path,))
        self.assertIsNotNone(row)
        self.assertEqual(row['file_size'], len(sample_data))
        self.assertEqual(bytes(row['file_data']), sample_data)

    def test_03_sync_disk_uploads_to_db(self):
        """Verify sync_disk_uploads_to_db scans static/uploads and records files"""
        res = sync_disk_uploads_to_db()
        self.assertIn('total', res)
        self.assertGreater(res['total'], 0)
        
        count_row = query_one("SELECT COUNT(*) as c FROM app_uploaded_files")
        self.assertGreater(count_row['c'], 0)

    def test_04_create_backup_includes_images_and_all_data(self):
        """Verify create_backup creates a .sql file with both tables and images"""
        res = create_backup(backup_type='manual', note='Unit test backup', save_to_gdrive=False)
        self.assertTrue(res.get('success'), f"Backup failed: {res.get('error')}")
        self.assertTrue(os.path.exists(res['filepath']))
        self.assertGreater(res['size_bytes'], 1000000) # Should be substantial (>1MB)
        self.assertGreater(res.get('images_count', 0), 0)
        
        # Verify the file is in list_backups()
        all_backups = list_backups()
        filenames = [b['filename'] for b in all_backups]
        self.assertIn(res['filename'], filenames)

    def test_05_restore_to_test_database(self):
        """Verify full restore into an isolated database restores tables and images"""
        test_db = 'inflow_unit_restore_test'
        conn = psycopg2.connect(
            host=Config.PG_HOST, port=Config.PG_PORT,
            user=Config.PG_USER, password=Config.PG_PASSWORD,
            dbname='postgres'
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {test_db};")
        cur.execute(f"CREATE DATABASE {test_db};")
        cur.close()
        conn.close()

        # Find latest backup
        backups = list_backups()
        latest = [b for b in backups if not b['filename'].startswith('pre_restore_')][0]
        
        # Run restore into test_db
        import subprocess
        psql_bin = find_pg_binary('psql')
        env = os.environ.copy()
        env['PGPASSWORD'] = Config.PG_PASSWORD
        cmd = [psql_bin, '-h', Config.PG_HOST, '-p', str(Config.PG_PORT), '-U', Config.PG_USER, '-d', test_db, '-f', latest['filepath']]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(res.returncode, 0, f"psql restore failed: {res.stderr}")

        # Check tables and images count in test_db
        conn = psycopg2.connect(
            host=Config.PG_HOST, port=Config.PG_PORT,
            user=Config.PG_USER, password=Config.PG_PASSWORD,
            dbname=test_db
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM app_uploaded_files")
        img_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM products")
        prod_count = cur.fetchone()[0]
        cur.close()
        conn.close()

        self.assertGreater(img_count, 0)
        self.assertGreater(prod_count, 0)

        # Cleanup test DB
        conn = psycopg2.connect(
            host=Config.PG_HOST, port=Config.PG_PORT,
            user=Config.PG_USER, password=Config.PG_PASSWORD,
            dbname='postgres'
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {test_db};")
        cur.close()
        conn.close()

    def test_06_restore_backup_error_handling(self):
        """Verify restore_backup fails gracefully on non-existent or empty files"""
        res_nonexistent = restore_backup('non_existent_file.sql', create_safety_backup=False)
        self.assertFalse(res_nonexistent['success'])
        self.assertIn("not found", res_nonexistent['error'])

        # Test empty file
        b_dir = get_backup_dir()
        empty_path = os.path.join(b_dir, 'empty_test.sql')
        with open(empty_path, 'w') as f:
            pass
        try:
            res_empty = restore_backup(empty_path, create_safety_backup=False)
            self.assertFalse(res_empty['success'])
            self.assertIn("empty", res_empty['error'])
        finally:
            if os.path.exists(empty_path):
                os.remove(empty_path)

    def test_07_api_create_backup_endpoint(self):
        """Verify POST /settings/backup/create generates a full backup with json response"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'main_admin'
            
        resp = self.client.post('/settings/backup/create', json={'note': 'Test via API', 'save_to_gdrive': False})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('Database backup created', data.get('message', ''))

if __name__ == '__main__':
    unittest.main()
