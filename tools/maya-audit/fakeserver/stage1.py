"""Socket-free, deterministic audit fixture for Stage 1 tests and preview."""
import httpx


def mock_site(count=3):
    seen = []
    def respond(request):
        assert request.url.host == "127.0.0.1", "fixture must stay on loopback"
        seen.append(str(request.url))
        path = request.url.path
        if path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /', headers={'content-type': 'text/plain'})
        if path == '/':
            links = ''.join(f'<a href="/page-{i}">Page {i}</a>' for i in range(1, count))
        elif path.startswith('/page-'):
            links = '<a href="/">Home</a>'
        else:
            return httpx.Response(404)
        return httpx.Response(200, text=f'<html lang="en"><title>Example {path}</title><main><h1>Example {path}</h1>'
                             f'<p>Useful factual content for a local test page {path}.</p>{links}</main></html>',
                             headers={'content-type': 'text/html'})
    return httpx.MockTransport(respond), seen

