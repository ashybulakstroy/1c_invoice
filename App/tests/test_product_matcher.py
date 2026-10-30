"""Matcher integration and preservation of the original fallback."""
from App.invoicing import catalog_1c as catalog
from App.invoicing.product_matcher import measurements


def test_heating_cable_precedes_ties_on_real_catalog():
    result=catalog.search_catalog('Кабель Нагревающийся Красный (100 м в бухте)')
    assert result['match_method']=='product_matcher_v1'
    assert 'Кабель нагревательный' in result['items'][0]['name']
    assert 'стяжки' not in result['items'][0]['name']
    assert result['items'][0]['reasons']


def test_short_manual_query_keeps_heating_cables_first():
    result=catalog.search_catalog('кабель наг')
    assert 'Кабель нагревательный' in result['items'][0]['name']


def test_no_type_match_falls_back_to_unchanged_default():
    query='Отбойник TEXA T26501'
    expected=catalog.default_search_catalog(query,limit=10)
    actual=catalog.search_catalog(query,limit=10)
    assert actual['match_method']=='default_fallback'
    assert actual['total']==expected['total']
    assert [{k:v for k,v in row.items() if k!='match_method'} for row in actual['items']]==expected['items']


def test_empty_results_and_empty_query_keep_fallback():
    assert catalog.search_catalog('кулер')['match_method']=='default_fallback'
    assert catalog.search_catalog('кулер')['items']==[]
    assert catalog.search_catalog('')['items'][0]['id']==catalog.default_search_catalog('')['items'][0]['id']


def test_exact_code_is_preserved():
    result=catalog.search_catalog('00000019886')
    assert result['items'][0]['code']=='00000019886'
    assert result['items'][0]['score']==100


def test_units_are_not_interchangeable():
    assert measurements('100 м')!=measurements('100 Вт')
    assert measurements('100 см')==measurements('1 м')


def test_best_candidate_used_even_below_old_threshold():
    query='Кронштейн 450x550x2 большой (пара)'
    expected=catalog.search_catalog(query,limit=1,include_invoices=True)['items'][0]
    actual=catalog.suggest_catalog(query)
    assert actual['id']==expected['id']
    assert actual['code']=='00000011571'
    assert actual['score']<70


def test_empty_search_still_has_no_suggestion():
    assert catalog.suggest_catalog('кулер') is None
