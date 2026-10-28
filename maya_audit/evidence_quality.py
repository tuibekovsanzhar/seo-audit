"""Source-bound qualifications shared by normal and client report adapters."""


def qualifications(finding):
    evidence = finding.get('evidence') or {}
    out = []
    if finding.get('check_id') == 'IDX-6':
        links = evidence.get('links') or []
        head_only = [r for r in links if r.get('method') == 'HEAD' and r.get('status') in (404, 410)
                     and not any(a.get('method') == 'GET' and a.get('status') in (404,410) and not a.get('error')
                                 for a in r.get('attempts') or [])]
        if head_only:
            out.append('Saved evidence contains HEAD failures without GET corroboration; whether these destinations are gone is uncertain. Do not remove them solely on this observation.')
    if finding.get('check_id') == 'IDX-1' and 'empty page' in finding.get('title',''):
        strength = evidence.get('observation_strength')
        if not strength:
            out.append('Historical empty-response finding combines evidence strengths; inspect complete request records. A single probe or a percentage alone does not confirm persistent critical failure.')
        elif strength != 'repeated_empty':
            out.append('Single empty response or unavailable corroboration; persistent failure and business impact remain uncertain.')
    return out
