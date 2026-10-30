import csv
from pathlib import Path
import pytest
from App.invoicing import ai_matching, catalog_1c
from App.invoicing.user_mapping import normalize_mapping_key


def write_csv(path,rows):
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,delimiter=';');writer.writeheader();writer.writerows(rows)


def card(code,name):return dict(id=code,name=name,code=code,unit='шт',service=False)


def test_actual_csv_loaded_completely():
    data=ai_matching._load(ai_matching.signature())
    assert data['rows']==24722 and not data['errors']


def test_live_codes_names_alternatives_and_unconfirmed_status(tmp_path):
    write_csv(tmp_path/'mapping.csv',[{'Название Торгсофт':'Имя из чека','Артикул Торгсофт':'0017',
        'Рекомендуемый код 1С':'00001','Рекомендуемая номенклатура 1С':'Старое имя CSV',
        'Оценка совпадения, %':'40.5','Оператор подтвердил':'Да',
        'Альтернатива №2 код 1С':'00002','Альтернатива №2 %':'20'}])
    index=dict(by_code={'00001':[card('00001','Актуальное имя 1С')],'00002':[card('00002','Альтернатива')]})
    found=ai_matching.proposals('имя из чека',index,directory=tmp_path)
    assert [r['code'] for r in found['items']]==['00001','00002']
    assert found['items'][0]['name']=='Актуальное имя 1С'
    assert found['items'][0]['score']==40.5
    assert 'confirmed' not in found['items'][0] and found['items'][0]['match_method']=='ai_matching'
    assert ai_matching.proposals('OCR другое имя',index,article='0017',directory=tmp_path)['items']


def test_missing_or_ambiguous_codes_not_fabricated(tmp_path):
    write_csv(tmp_path/'mapping.csv',[{'Название Торгсофт':'Товар','Рекомендуемый код 1С':'missing',
        'Альтернатива №2 код 1С':'double','Альтернатива №3 код 1С':'ok','Альтернатива №3 %':'5'}])
    index=dict(by_code={'double':[card('double','A'),card('double','B')],'ok':[card('ok','C')]})
    found=ai_matching.proposals('Товар',index,directory=tmp_path)
    assert [r['code'] for r in found['items']]==['ok']
    assert len(found['errors'])==2


def test_ai_used_only_when_name_search_is_empty(tmp_path,monkeypatch):
    write_csv(tmp_path/'mapping.csv',[{'Название Торгсофт':'НетПрямогоИмени','Рекомендуемый код 1С':'00000019886','Оценка совпадения, %':'22'}])
    monkeypatch.setattr(ai_matching,'DIRECTORY',tmp_path)
    result=catalog_1c.search_catalog('НетПрямогоИмени')
    assert result['match_method']=='ai_matching'
    assert result['items'][0]['code']=='00000019886' and result['items'][0]['score']==22
    primary=catalog_1c.search_catalog('скотч упаковочный')
    assert primary['match_method']=='product_matcher_v1'


def test_mapping_update_invalidates_cached_suggestion(tmp_path,monkeypatch):
    path=tmp_path/'mapping.csv'
    monkeypatch.setattr(ai_matching,'DIRECTORY',tmp_path)
    write_csv(path,[{'Название Торгсофт':'НетПрямогоИмени','Рекомендуемый код 1С':'00000019886','Оценка совпадения, %':'20'}])
    assert catalog_1c.suggest_catalog('НетПрямогоИмени')['score']==20
    write_csv(path,[{'Название Торгсофт':'НетПрямогоИмени','Рекомендуемый код 1С':'00000019886','Оценка совпадения, %':'88.5'}])
    assert catalog_1c.suggest_catalog('НетПрямогоИмени')['score']==88.5


def test_missing_directory_and_unknown_name_are_empty(tmp_path):
    assert ai_matching.proposals('нет',dict(by_code={}),directory=tmp_path)['items']==[]


def test_ai_fallback_reaches_invoice_without_confirmation_or_price_changes(tmp_path,monkeypatch):
    import copy
    from io import BytesIO
    from pypdf import PdfReader
    from App.tests.test_invoicing_invoice_api import RECEIPT
    from App.invoicing.invoice_service import invoice_model, render_invoice
    write_csv(tmp_path/'mapping.csv',[{'Название Торгсофт':'НетПрямогоИмени','Рекомендуемый код 1С':'00000019886','Оценка совпадения, %':'22'}])
    monkeypatch.setattr(ai_matching,'DIRECTORY',tmp_path)
    receipt=copy.deepcopy(RECEIPT)
    receipt['job_id']='c'*32
    receipt['rows'][1].update(name='НетПрямогоИмени',name_raw='НетПрямогоИмени',article='')
    before=copy.deepcopy(receipt)
    model=invoice_model(receipt)
    item=model['generation']['items'][0]
    assert item['suggestion_method']=='ai_matching' and item['match_status']=='suggested'
    assert item['code']=='00000019886' and item['price']=='1200.00'
    assert model['selections']=={} and receipt==before
    payload=render_invoice(model,model['revision'],model['token'])
    assert ' '.join(item['name'].split()) in ' '.join(' '.join(page.extract_text() for page in PdfReader(BytesIO(payload)).pages).split())
