#server.py
from aiohttp import web
# Performance improvement: Use uvloop if available
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

async def ingest(request):
    try:
        data = await request.json()
    except Exception:
        data = None
    return web.json_response({"ok": True})

app = web.Application()
app.add_routes([web.post('/ingest', ingest)])

if __name__ == "__main__":
    web.run_app(app, port=8080)