from experiments.product_matcher_v1 import rank_products


def card(name,code):return dict(name=name,code=code,unit='шт')


def test_heating_cable_ranks_above_cable_ties():
    cards=[card('ЗУБР кабельные стяжки 100 мм 100 шт','tie'),
           card('Кабель нагревательный Теплолюкс 13 м 190 Вт','heat')]
    result=rank_products('Кабель Нагревающийся Красный (100 м в бухте)',cards)
    assert result[0]['code']=='heat'
    assert any('числа требуют проверки' in reason for reason in result[0]['reasons'])


def test_brand_alone_does_not_match_wrong_type():
    assert rank_products('Отбойник TEXA T26501',[card('Триммер Бензиновый TEXA','trim')])==[]


def test_code_overrides_lexical_ranking():
    assert rank_products('00001',[card('Кабель','00002'),card('Скотч','00001')])[0]['code']=='00001'


def test_packaging_tape_ranks_above_paper_tape():
    cards=[card('Бумажный скотч 4,5 см 40 м','paper'),card('Скотч упаковочный 45 мм *400 м','pack')]
    assert rank_products('Скотч упаковочный прозрачный 45 мм 400 м ОФИЦИАЛ',cards)[0]['code']=='pack'
