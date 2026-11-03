import sys, json, unittest, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_data as build
import render
from pypdf import PdfWriter

class Wording:
 mod=None
 def title(self,c,t): return t,False
 def fix(self,t): return t,False
 def expected(self,t): return t,False

def data(urls, complete=None):
 f={'id':'STR-2-generic','check_id':'STR-2','title':'Missing heading','severity':'S4','confidence':'estimated','scope':{'kind':'template','count':30,'urls':urls},'how_to_fix':'Inspect headings','expected':'Meaningful heading','evidence':{},'launch_gated':['LG-1']}
 r={'checks':[{'findings':[f]}],'findings_in_priority_order':[f['id']],'problem_summary':{'problems':1,'by_severity':{'S4':1}},'crawl':{'origin':'https://sample.example','started_at':'2026-10-23T00:00:00+00:00'},'audit_status':{'content_coverage':{'pages_read':2,'level':'partial'}}}
 return build.Builder(r,'en',render.LABELS['en'],json.loads((build.REFS/'sahip_efor.json').read_text()),Wording(),None,'test',False,complete).build()

class Compatibility(unittest.TestCase):
 def test_complete_membership_not_capped(self):
  urls=[f'https://sample.example/page-{i}'for i in range(30)]
  d=data(urls[:25],{'STR-2-generic':urls});self.assertEqual(d['todos'][0]['more'],26)
 def test_scope_membership_not_shrunk_by_actionable_subset(self):
  urls=[f'https://sample.example/p{i}'for i in range(7)]
  self.assertEqual(data(urls,{'STR-2-generic':urls[:2]})['todos'][0]['more'],3)
 def test_legacy_without_companion_unchanged(self):
  self.assertEqual(data(['https://sample.example/p'])['todos'][0]['more'],0)
 def test_absent_measurements_remain_missing(self):
  d=data([]);self.assertIsNone(d['lab']);self.assertIsNone(d['field']);self.assertEqual(d['search']['state'],'missing');self.assertEqual(d['kpis'][3]['state'],'missing');self.assertIn('No lab test',d['limits']['text']);self.assertIn('Not measured',render.page3(d,render.LABELS['en']))
 def test_uncertainty_visible_on_action_card(self):
  d=data([]);t=d['todos'][0];t.update(title='Review heading',steps='Inspect source\nConfirm purpose',verify='Check the heading tree');page=render.todo_pages(d,render.LABELS['en'])[0];self.assertIn('>Estimated<',page);self.assertNotIn('not yet validated',page)  # DECISIONS 300 (7)
 def test_sitemap_probe_units_are_urls_not_content_pages(self):
  b=build.Builder({},'en',render.LABELS['en'],{},Wording(),None,'test')
  f={'check_id':'IDX-5','title':'Sitemap URL observations','scope':{'kind':'template','count':30}}
  self.assertEqual(b.scope_text(f),'30 URLs')
  f['check_id']='STR-2';self.assertEqual(b.scope_text(f),'30 pages')
 def test_gap_label_does_not_claim_whole_checks(self):
  b=build.Builder({'checks':[{'coverage':{'not_assessed':[{'part':'headers','reason':'missing'},{'part':'body','reason':'missing'}]}}]},'en',render.LABELS['en'],{},Wording(),None,'test')
  self.assertEqual(b.gaps(),2)
  self.assertEqual(render.LABELS['en']['cov_gaps'],'Unassessed scope items')
 def test_page_count_fallback_and_excess(self):
  with tempfile.TemporaryDirectory()as tmp:
   for count,valid in [(4,True),(5,False),(51,False)]:
    w=PdfWriter()
    for _ in range(count):w.add_blank_page(width=1120,height=792)
    p=Path(tmp)/'sample.pdf';w.write(p);issues=render.check_pdf(p,{'todos':[],'lang':'en'});self.assertEqual(not any(x.startswith('HATA')for x in issues),valid)
if __name__=='__main__':unittest.main()
