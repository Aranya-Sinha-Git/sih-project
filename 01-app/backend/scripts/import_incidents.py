"""Validate and import operational CSV records without losing source identifiers or dates."""
import csv,sqlite3,sys
from datetime import date
from hashlib import sha1
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.main import REPORT_TYPES, init_db, persist_incident
from app.services.engine import analyze_text

TYPE_ALIASES={'ua':'Unsafe Act','unsafe act':'Unsafe Act','uc':'Unsafe Condition','unsafe condition':'Unsafe Condition','near miss':'Near Miss','incident':'Incident'}

def main(path):
 init_db();total=ok=bad=0;seen=set();batch_id='IMP-'+sha1(str(Path(path).resolve()).encode()).hexdigest()[:10].upper()
 with open(path,newline='',encoding='utf-8-sig')as f:
  for r in csv.DictReader(f):
   total+=1
   if not all(r.get(k,'').strip()for k in('report_id','date','site','activity','narrative'))or r['report_id'] in seen:bad+=1;continue
   try:
    date.fromisoformat(r['date'])
    report_type=TYPE_ALIASES.get(r.get('report_type','').strip().lower(),r.get('report_type','').strip() or 'Unspecified')
    if report_type not in REPORT_TYPES:raise ValueError('unsupported report type')
    analysis=analyze_text(r['narrative'])
    analysis['provenance']={'source_type':'operational_import','source_report_id':r['report_id'],'import_batch_id':batch_id,'source_reference':r.get('source','').strip() or None}
    persist_incident(narrative=r['narrative'],site=r['site'],activity=r['activity'],report_type=report_type,analysis=analysis,report_id=r['report_id'],report_date=r['date'],source=r.get('source','').strip() or 'operational_import',import_batch_id=batch_id)
    seen.add(r['report_id']);ok+=1
   except (ValueError,KeyError,sqlite3.IntegrityError):bad+=1
 print(f'Processed={total} imported={ok} invalid_or_duplicate={bad} batch={batch_id}')
if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('Usage: python scripts/import_incidents.py /path/to/incidents.csv')
 main(sys.argv[1])
