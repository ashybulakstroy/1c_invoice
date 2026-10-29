import pytest

from App.server_config import server_settings


def test_reads_project_env(tmp_path):
    path = tmp_path / '.env'
    path.write_text('OCR_WEB_HOST=0.0.0.0\nOCR_WEB_PORT=8016\n', encoding='utf-8')
    config = server_settings(path, {})
    assert config.host == '0.0.0.0' and config.port == 8016
    assert config.browser_url == 'http://127.0.0.1:8016'


def test_environment_overrides_file(tmp_path):
    path = tmp_path / '.env'
    path.write_text('OCR_WEB_HOST=0.0.0.0\nOCR_WEB_PORT=8016\n', encoding='utf-8')
    config = server_settings(path, {'OCR_WEB_PORT': '8042', 'OCR_WEB_HOST': 'localhost'})
    assert config.browser_url == 'http://localhost:8042'


@pytest.mark.parametrize('value', ['abc', '0', '-1', '65536'])
def test_invalid_port_has_clear_error(tmp_path, value):
    with pytest.raises(ValueError, match='OCR_WEB_PORT'):
        server_settings(tmp_path / '.env', {'OCR_WEB_PORT': value})


def test_invalid_host_has_clear_error(tmp_path):
    with pytest.raises(ValueError, match='OCR_WEB_HOST'):
        server_settings(tmp_path / '.env', {'OCR_WEB_HOST': 'http://localhost'})
