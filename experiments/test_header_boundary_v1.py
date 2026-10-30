import pytest
from experiments.header_boundary_v1 import without_table_headers
from App.ocr_catalog_eval import aligned_lines, parse_rows
from App.tests.test_table_headers import line, LAYOUT
from unittest.mock import patch


@pytest.mark.parametrize('name,quantity,price',[
    ('Тауардың атауы','Саны','Багасы'),
    ('Тауардың атауы','Саны','Бағасы'),
    ('Наименование','Количество','Цена')])
def test_header_with_numeric_ocr_and_noise_above_is_excluded(name,quantity,price):
    payload=[line('Кассир 100',180,15),line('N8',30,40),line(name,180,40),
             line(quantity,370,40),line(price,460,40),line('Доска',180,90),
             line('51',370,90),line('1880',460,90)]
    with patch('App.table_headers.without_table_headers',without_table_headers):
        rows=parse_rows(aligned_lines(dict(lines=payload),{}),LAYOUT,[0,25,60,120])
    assert len(rows)==1 and rows[0]['name_raw']=='Доска'
    assert rows[0]['quantity_raw']=='51' and rows[0]['price_raw']=='1880'


def test_no_header_does_not_remove_numeric_or_name_lines():
    lines=aligned_lines(dict(lines=[line('N8',180,40),line('51',370,40),line('1880',460,40)]),{})
    assert without_table_headers(lines,LAYOUT)==lines
