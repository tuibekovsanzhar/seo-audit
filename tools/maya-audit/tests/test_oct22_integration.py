"""Integration invariants: retain stronger local protections while adopting incoming improvements."""
from copy import deepcopy
from maya_audit.client_reporting import from_maya_report as F, grouped

def test_required_unverified_evidence_does_not_create_a_score():
    cfg=F.load_json(F.REFS/'onem_kurallari.json')['score']
    cov={'score_status':'assessed_sample','pages_read':10,'assessed_checks':1,'check_denominators':{'STR-1':10}}
    card={'id':'title','_scored':True,'maya':{'check_id':'STR-1','severity_report':'S2','launch_gated':['LG-9']},'where':{'count':1,'affected_urls':['https://clinic.example/services']}}
    assert F.score([card],cov,cfg)==(None,{})
    assessed=deepcopy(card);assessed['maya']['launch_gated']=[]
    assert 0<=F.score([assessed],cov,cfg)[0]<100

def test_compact_members_keep_qualification_and_identity():
    card={'id':'STR-7-clinic-image','title':'Görsel rolü belirsiz','severity':'Bilgi','where':{'count':1,'affected_urls':['https://clinic.example/treatment']},'steps':['Amacı kanıtla doğrulamalısınız.'],'_source_context':{'notes':['CSS ve işlev kanıtı eksik; dekoratif olabilir.']},'could_be_intentional':True}
    text=grouped.row(card,'https://clinic.example')
    assert card['id']in text and 'href="https://clinic.example/treatment"'in text
    assert 'CSS ve işlev kanıtı eksik; dekoratif olabilir.'in text
    assert 'içerik sahibinin amacı'in text
    certain=deepcopy(card);certain['_source_context']['notes']=[];certain['could_be_intentional']=False
    assert 'member-qualification'not in grouped.row(certain,'https://clinic.example')
