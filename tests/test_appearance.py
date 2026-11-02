from io import BytesIO
import httpx
import pytest
from PIL import Image
from deckhand import NationStates
from deckhand.api import APIError
from deckhand.appearance import flag_accent


@pytest.mark.parametrize('color', ['red', 'blue', 'green', 'black', 'white'])
def test_flag_palette_readable_on_dark_background(color):
    data = BytesIO()
    Image.new('RGB', (8, 8), color).save(data, format='PNG')
    accent = flag_accent(data.getvalue())
    assert len(accent) == 7 and accent.startswith('#')
    channels = [int(accent[i:i+2], 16) / 255 for i in (1, 3, 5)]
    def lum(values):
        return sum((v / 12.92 if v <= .04045 else ((v+.055)/1.055)**2.4) * w
            for v, w in zip(values, (.2126, .7152, .0722)))
    assert (lum(channels) + .05) / (lum((11/255, 18/255, 32/255)) + .05) >= 4.5


async def test_flag_public_reads_use_gate_and_no_credentials():
    seen, attempts = [], []
    def handle(request):
        seen.append(request)
        assert 'X-Password' not in request.headers and 'X-Pin' not in request.headers
        if request.url.path.endswith('api.cgi'):
            assert request.url.params['nation'] == 'alpha'
            return httpx.Response(200, text='<NATION id="alpha"><FLAG>https://www.nationstates.net/images/flags/test.png</FLAG></NATION>')
        return httpx.Response(200, content=b'flag-image')
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(handle)) as api:
        api._pin = 'synthetic-never-send'
        api.gate.interval = 0
        api.gate.on_request = lambda: attempts.append(1)
        assert await api.flag_image() == b'flag-image'
    assert len(attempts) == len(seen) == 2


@pytest.mark.parametrize('location', ['https://example.com/flag.png', 'http://www.nationstates.net/images/flags/a.png', 'https://www.nationstates.net/cgi-bin/api.cgi'])
async def test_flag_rejects_unexpected_download_location(location):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, text=f'<NATION id="alpha"><FLAG>{location}</FLAG></NATION>')
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(handle)) as api:
        with pytest.raises(APIError):
            await api.flag_image()
    assert len(requests) == 1
