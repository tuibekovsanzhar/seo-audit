"""Evidence-bound Turkish procedures; no new observations, selectors or provider calls."""
import re


def procedure(finding, row):
    cid=finding['check_id'];title=(finding.get('title')or'').lower();ev=finding.get('evidence')or{}
    urls=list(dict.fromkeys((finding.get('scope')or{}).get('_all_urls')or(finding.get('scope')or{}).get('urls')or[]))
    targets=[];elements=[]
    for name in ('links','pages','images','items','tables'):
        records=ev.get(name)
        # Several checks use e.g. evidence.pages for a numeric count, not records.
        if not isinstance(records,(list,tuple)):continue
        for record in records:
            if not isinstance(record,dict):continue
            for key in ('target','href','iframe_src','src'):
                if record.get(key):targets.append(str(record[key]))
            for key in ('element_id','selector','component'):
                if record.get(key):elements.append(str(record[key]))
    targets=list(dict.fromkeys(targets));elements=list(dict.fromkeys(elements))
    where='Bu adreslerde kaydı incelemelisiniz. Kaynak adresler: '+(', '.join(urls[:3])if urls else 'kayıtlı kapsamda adres belirtilmemiş')+'.'
    if len(urls)>3:where+=' Tam adres listesi raporun JSON ekindedir.'
    if targets:where+=' Kayıtlı hedef / öğe: '+', '.join(targets[:3])+'.'
    if elements:where+=' Kayıtlı öğe referansı: '+', '.join(elements[:3])+'.'
    from maya_audit_web import wording
    qualified_action=(row.get('judgment')or{}).get('action')or{}
    translated_fix,fix_ok=wording.fix(qualified_action.get('text')or finding.get('how_to_fix')or'', 'tr')
    repair=(translated_fix if fix_ok else None)or'Kanıtın kapsamını ve sayfanın amacını incelemelisiniz; neden belirlenmeden değişiklik seçmemelisiniz.'
    if not re.search(r'm[ae]l[ıi]s[ıi]n[ıi]z',repair,re.I):
        repair='Kayıtlı öneriyi ve kapsam koşullarını değerlendirerek karar vermelisiniz: '+repair
    subtype=cid+':'+str((row.get('judgment')or{}).get('kind')or title)
    expected,expected_ok=wording.expected(finding.get('expected')or'', 'tr')
    verify='Beklenen özellik: '+str(expected if expected_ok else 'kayıtlı gözlemin koşulları; tam teknik tanım JSON ekindedir')+'. Aynı adres/istemci koşullarında sonucu ve zamanı kanıtla kaydetmelisiniz.'
    decide='Karar vermelisiniz: '+repair
    if cid=='STR-2' and ('no <h1>'in title or 'no meaningful <h1>'in title):
        subtype='STR-2:missing-h1'
        repair='Mevcut boş h1 varsa sayfanın gerçek konusuyla doldurmalısınız; h1 öğesi yoksa boş olmayan anlamlı bir ana başlık eklemelisiniz. Eski özetler boş öğeleri saklamamış olabilir.'
        verify='Kaynak HTML ve erişilebilir başlık ağacında sayfanın konusunu belirten boş olmayan bir h1 bulunduğunu doğrulamalısınız; yalnızca boş etiketi eklemek yeterli değildir.'
        decide='Karar vermelisiniz: Sayfanın gerçek konusunu belirten ana başlığı içerik sahibiyle seçmelisiniz; yeni iş bilgileri uydurulmamalıdır.'
    elif cid=='STR-2' and 'no subheadings'in title:
        subtype='STR-2:missing-subheadings'
        verify='Okuma sırasını ve bölüm başlıklarını incelemelisiniz. Tablolar veya listeler zaten yeterli yapı sağlıyorsa ek başlık zorunlu sayılmamalıdır.'
    elif cid=='ACC-3' and ('noindex'in title.lower() or 'nosnippet'in title.lower()):
        subtype='ACC-3:indexing-intent'
        repair='İçerik sahibiyle dizine ekleme amacını doğrulamalısınız. Bilinçli dışlamayı korumalı; yalnızca dizine girmesi istenen sayfada noindex değiştirmelisiniz. Sitemap üyeliğini ayrıca değerlendirmelisiniz.'
        verify='Aynı URL için yönergeyi ve içerik sahibinin dizine ekleme kararını kaydetmelisiniz; rapor onayı canlı doğrulama değildir.'
        decide='Karar vermelisiniz: Bu sayfanın aramada yer alması isteniyor mu? Bilinçli dışlamayı otomatik kaldırmamalısınız.'
    elif cid=='STR-7' and ('WebP'in title or 'AVIF'in title):
        subtype='STR-7:format-evidence'
        repair='İşaretlemedeki biçim referanslarını kayıtlı HTTP yanıt biçimlerinden ayırmalısınız. Bayt boyutu, görsel kalite ve uygun alternatifleri karşılaştırmadan dönüşüm kararı vermemelisiniz.'
        verify='Aynı istemci ve zamanda Content-Type, Accept/Vary, dosya boyutu ve görsel kaliteyi karşılaştırmalısınız. Dosya uzantısı sunulan biçimi kanıtlamaz; eksik yanıt bilgisi ölçülmemiştir.'
        decide='Karar vermelisiniz: Ölçülen boyut ve kaliteye göre hangi teslim seçeneği uygundur? Her WebP/AVIF dönüşümü iyileşme garantilemez.'
    elif cid=='IDX-6':
        subtype='IDX-6:'+str((row.get('judgment')or{}).get('status'))
        verify='Kayıtlı kaynak bağlantısını ve hedefini aynı istemciyle, izinler ve istek sınırları içinde GET ile doğrulamalısınız; son durum kodunu, yönlendirmeleri, içeriği ve zamanı kaydetmelisiniz. HEAD hatası tek başına hedefin kaldırıldığını kanıtlamaz.'
        decide='Karar vermelisiniz: Hedefin beklenen işlevini ve GET sonucunu doğrulamadan bağlantıyı kaldırmamalısınız; doğrulanan hatada doğru hedefi içerik sahibiyle seçmelisiniz.'
    elif cid=='RND-4' and 'accessible name'in title:
        subtype='RND-4:iframe-name'
        verify='Tarayıcının erişilebilirlik ağacında her iframe için açıklayıcı erişilebilir ad bulunduğunu doğrulamalısınız; title, aria-label veya çözümlenebilir aria-labelledby metni ilgili çerçeveyi açıklamalıdır.'
    elif cid=='STR-7' and 'placeholder'in title:
        subtype='STR-7:placeholder-alt'
        verify='Görselin işlevini ve eşdeğer metni incelemelisiniz. Bilgi aktarıyorsa alt gerçek içeriğini açıklamalı; dekoratifse boş alt ve uygun sunum amacı korunmalıdır.'
    if cid=='STR-2' and subtype=='STR-2:missing-subheadings':
        repair='Sayfanın okuma sırasını incelemelisiniz. Tablo ve listeler bilgiyi zaten yapılandırıyorsa zorunlu başlık eklememeli; anlamlı bölümler varsa açıklayıcı alt başlıklar kullanmalısınız.'
        decide='Karar vermelisiniz: Sayfanın gerçek bölüm yapısını ve amacını içerik sahibiyle belirlemelisiniz.'
    # The addresses are said once, in the steps (CR-11): the verification refers to "the same addresses".
    return {'subtype':subtype,'repair':repair,'verification':verify,'decision':decide,'where':where,
            'steps':[repair,where],'verify':verify,'decide':decide,'targets':targets}


def edited(card):
    """Whether an editor changed a generated card (its title, steps, verification, explanation, proposed text, owner or
    effort). Such a card is shown whole, never folded into a shared procedure."""
    p=card.get('_procedure')or{}
    if not p:return False
    return {k:card.get(k)for k in('title','steps','verify','why','what_to_write','owner','effort')}!=p.get('generated')


def group_signature(card):
    p=card.get('_procedure')or{}
    if not p:return None
    # Any owner edit may change meaning: keep that card separate rather than guess compatibility.
    if edited(card):return None
    j=card.get('judgment')or{}
    return (card.get('maya',{}).get('check_id'),p['subtype'],card.get('severity'),
            p['repair'],p['verification'],p['decision'],card.get('owner'),card.get('effort'),
            j.get('status'),j.get('interpretation'),tuple(j.get('alternatives')or[]),
            j.get('verification_status'),card.get('could_be_intentional'),card.get('rule_applied'),bool((card.get('evidence')or{}).get('verification')),card.get('_needs_live_check'))
