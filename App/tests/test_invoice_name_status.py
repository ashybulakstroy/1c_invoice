"""Names in the payment document must be 1C names; suggestions stay unconfirmed."""
import copy
from io import BytesIO
import pytest
from pypdf import PdfReader
from App.tests.test_invoicing_invoice_api import RECEIPT
from App.invoicing.invoice_service import invoice_model, render_invoice


def test_tape_suggested_from_actual_catalog_without_confirming():
    receipt=copy.deepcopy(RECEIPT)
    receipt['job_id']='a'*32
    receipt['rows'][1]['name']='Скотч упаковочный прозрачный 45 мм * 400 м ОФИЦИАЛ'
    receipt['rows'][1]['name_raw']=receipt['rows'][1]['name']
    receipt['rows'][1]['article']=''
    before=copy.deepcopy(receipt)
    model=invoice_model(receipt)
    row=model['generation']['items'][0]
    assert row['match_status']=='suggested'
    assert row['code']=='00000019886'
    assert row['name']=='Скотч упаковочный  45 мм *400 м'
    assert model['selections']=={}
    assert not model['ready'] and model['can_render']
    assert model['candidates']['2']['items']
    assert receipt==before


def test_bracket_best_candidate_is_used_in_document_despite_low_score():
    from App.receipt_editing import update_receipt
    receipt=copy.deepcopy(RECEIPT)
    receipt['job_id']='b'*32
    row=receipt['rows'][1]
    row.update(name='Кронштейн 450x550x2 большой (пара)',name_raw='Кронштейн 450x550x2 большой (пара)',
               article='',quantity='17',price='5550',line_total='94350')
    receipt['rows']=[row,dict(row=6,kind='tax',name='НДС',quantity='15096',price='1',line_total='15096')]
    receipt['expected_total']='109446'
    receipt=update_receipt(receipt)
    before=copy.deepcopy(receipt)
    model=invoice_model(receipt)
    item=model['generation']['items'][0]
    assert item['code']=='00000011571'
    assert item['match_status']=='suggested' and item['name']=='Кронштейн 400х450х1,5'
    assert model['selections']=={} and receipt==before
    pdf=render_invoice(model,model['revision'],model['token'])
    text=' '.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    assert 'Кронштейн 400х450х1,5' in text
    assert '109 446,00' in text


def test_unresolved_name_blank_red_and_suggestion_yellow():
    from App.tests.test_invoicing_invoice_generation import generation_document
    from App.invoicing.invoice_pdf import render_invoice_pdf
    pdfium=pytest.importorskip('pypdfium2')
    document=generation_document()
    first=copy.deepcopy(document['items'][0])
    first.update(name=None,source_name='OCR NAME MUST NOT BE PRINTED',match_status='unmatched')
    second=copy.deepcopy(first)
    second.update(name='1C SUGGESTION',match_status='suggested')
    document['items']=[first,second]
    from App.invoicing.invoice_presentation import print_fields
    document['print_form']=print_fields(document)
    payload=render_invoice_pdf(document)
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(payload)).pages)
    assert 'OCR NAME MUST NOT BE PRINTED' not in text
    assert '1C SUGGESTION' in text
    pdf=pdfium.PdfDocument(payload)
    image=pdf[0].render(scale=1).to_pil().convert('RGB')
    colors=image.getcolors(image.width*image.height)
    assert sum(count for count,color in colors if color==(255,214,214))>100
    assert sum(count for count,color in colors if color==(255,240,166))>100


def test_suggestion_shade_tracks_similarity_without_becoming_white():
    from App.invoicing.invoice_presentation import suggestion_fill
    assert suggestion_fill(None)==suggestion_fill('bad')==suggestion_fill('NaN')=='#fff0a6'
    assert suggestion_fill(0)==suggestion_fill(50)=='#fff0a6'
    shades=[suggestion_fill(score) for score in (50,70,85,95,100)]
    values=[tuple(int(shade[i:i+2],16) for i in (1,3,5)) for shade in shades]
    assert all(a[1]<=b[1] and a[2]<b[2] for a,b in zip(values,values[1:]))
    assert shades[-1]=='#fffceb' and '#ffffff' not in shades
    assert suggestion_fill(200)==suggestion_fill(100)


def test_automatic_learned_service_cannot_replace_receipt_price(monkeypatch):
    from App.invoicing import invoice_generation as generation
    monkeypatch.setattr(generation,'apply_training_pairs',lambda *args,**kwargs:dict(items=[
        dict(source_index=0,name='Доставка 1С',quantity='1',unit='усл',price='15000',quantity_mode='service')]))
    source=dict(items=[dict(row_id='1',name='Доставка Рынок',quantity='15000',price='1')],
                vat_amount='2400',total='17400')
    result=generation.build_generation(source,vat_in_line_amounts=False)
    row=result['items'][0]
    assert row['quantity']=='15000' and row['price']=='1' and row['amount']=='15000.00'
    assert result['total']=='17400' and result['vat_amount']=='2400'


def test_vat_prices_include_tax_and_have_exactly_two_decimals():
    from App.receipt_editing import update_receipt
    from decimal import Decimal
    receipt=copy.deepcopy(RECEIPT);receipt['job_id']='c'*32
    row=receipt['rows'][1]
    row.update(quantity='51',price='1880',line_total='95880')
    receipt['rows']=[row,dict(row=6,kind='tax',name='НДС 16 %',quantity='15341',price='1',line_total='15341')]
    receipt['expected_total']='111221'
    receipt=update_receipt(receipt);before=copy.deepcopy(receipt)
    model=invoice_model(receipt);item=model['generation']['items'][0]
    assert item['price']=='2180.80'
    assert model['document']['print_form']['items'][0]['price']=='2 180,80'
    assert Decimal(item['amount'])==Decimal('111221')
    assert Decimal(model['document']['total'])==Decimal('111221')
    assert Decimal(item['price_rounding_difference'])==Decimal('-.20')
    assert model['rounding_notes'] and receipt==before
    assert model['document']['print_form']['vat_label']=='В том числе НДС:'


def test_no_separate_vat_does_not_add_tax_to_prices():
    receipt=copy.deepcopy(RECEIPT);receipt['job_id']='d'*32
    model=invoice_model(receipt)
    assert model['generation']['vat_in_line_amounts'] is False
    assert model['generation'].get('price_decimal_places') is None
    assert model['rounding_notes']==[]
