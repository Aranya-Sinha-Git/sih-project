import json
import sqlite3
import runpy
from pathlib import Path


module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'migrate_sqlite_to_supabase.py'))


def test_malformed_legacy_analysis_is_preserved_as_json_object():
    result = module['json_object']('{legacy malformed}')
    assert result['legacy_raw_analysis'] == '{legacy malformed}'
    assert result['screening']['decision'] == 'UNKNOWN'


def test_incident_payload_preserves_ids_dates_and_analysis(tmp_path):
    db = tmp_path / 'legacy.db'
    connection = sqlite3.connect(db)
    connection.execute('CREATE TABLE incidents (id TEXT PRIMARY KEY, report_date TEXT, site TEXT, activity TEXT, narrative TEXT, source TEXT, sif_probability REAL, risk TEXT, high_potential INTEGER, sif_potential INTEGER, sif_label_status TEXT, analysis TEXT, review_status TEXT, reviewer TEXT, review_comment TEXT, created_at TEXT, report_type TEXT, import_batch_id TEXT)')
    connection.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('OSHA-1','2025-01-02','Site','Activity','A preserved legacy narrative.','osha',.2,'Low',0,0,'manual_reviewed',json.dumps({'screening': {'decision':'NON_SIF_POTENTIAL'}}),'Reviewed','Reviewer','ok','2025-01-02T00:00:00','Incident','IMP-1'))
    connection.commit()
    row = connection.execute('SELECT * FROM incidents').fetchone()
    connection.row_factory = sqlite3.Row
    row = connection.execute('SELECT * FROM incidents').fetchone()
    payload = module['incident_payload'](row)
    assert payload['id'] == 'OSHA-1' and payload['report_date'] == '2025-01-02' and payload['analysis']['screening']['decision'] == 'NON_SIF_POTENTIAL'
    connection.close()


def test_repeated_migration_skips_existing_rows(tmp_path):
    db = tmp_path / 'legacy.db'
    connection = sqlite3.connect(db)
    connection.execute('CREATE TABLE incidents (id TEXT PRIMARY KEY, report_date TEXT, site TEXT, activity TEXT, narrative TEXT, source TEXT, sif_probability REAL, risk TEXT, high_potential INTEGER, sif_potential INTEGER, sif_label_status TEXT, analysis TEXT, review_status TEXT, reviewer TEXT, review_comment TEXT, created_at TEXT, report_type TEXT, import_batch_id TEXT)')
    connection.execute('CREATE TABLE review_history (id INTEGER PRIMARY KEY, incident_id TEXT, outcome TEXT, reviewer TEXT, comment TEXT, timestamp TEXT, previous_outcome TEXT, new_outcome TEXT, screening_version TEXT)')
    connection.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', ('ANL-1','2025-01-02','Site','Activity','A restart-safe migration narrative.','source',.2,'Low',0,0,'classifier_screened','{}','Not required',None,None,'2025-01-02T00:00:00','Incident',None))
    connection.commit(); connection.close()

    class FakeClient:
        def __init__(self): self.tables={'incidents':{},'review_history':{}}
        def existing(self,table,column,value): return [row for row in self.tables[table].values() if str(row.get(column))==str(value)]
        def insert(self,table,payload): self.tables[table][str(payload['id'])]=payload
        def request(self,method,table,**kwargs): return list(self.tables[table].values())
        def rpc(self,function,payload=None): assert function == 'sync_review_history_identity'
        def all_rows(self,table,select='*'): return list(self.tables[table].values())

    client=FakeClient()
    first=module['migrate'](db,client); second=module['migrate'](db,client)
    assert first['inserted']==1 and second['skipped']==1 and len(client.tables['incidents'])==1


def test_timestamp_comparison_uses_the_same_instant():
    assert module['canonical_timestamp']('2025-01-02T00:00:00') == module['canonical_timestamp']('2025-01-02T00:00:00+00:00')
    assert module['comparable_incident']({'id':'A','created_at':'2025-01-02T00:00:00+00:00'}, {'id':'A','created_at':'2025-01-02T00:00:00'})
