# FastAPI: Untyped `request` parameter causes 422

## Symptom
A FastAPI route returns `422 Unprocessable Content` with error:
```json
{"detail":[{"type":"missing","loc":["query","request"],"msg":"Field required"}]}
```

## Root cause
The route handler declared `request` without a type annotation:
```python
@app.get("/")
async def root(request):  # BAD — FastAPI treats this as a query parameter
```

FastAPI uses type annotations to distinguish between special objects (like `Request`) and user-supplied parameters. Without the annotation, `request` is interpreted as a required query parameter named "request".

## Fix
```python
from fastapi import Request

@app.get("/")
async def root(request: Request):  # GOOD — recognized as the HTTP request object
```

## Why it's not obvious
- Starlette (which FastAPI wraps) recognizes `request` by name, so this works in pure Starlette apps
- The route may have worked historically if it was defined before FastAPI's stricter parameter resolution
- The 422 error message says "Field required" which doesn't hint at a type annotation issue
