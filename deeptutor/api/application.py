"""无本地启动副作用的通用 API 组合工厂；入口显式选择路由与 lifespan。"""

from fastapi import FastAPI


def create_api_application(*, routers, lifespan, title="DeepTutor", middleware=()):
    app = FastAPI(
        title=title, lifespan=lifespan, middleware=list(middleware), docs_url=None, redoc_url=None
    )
    seen = set()
    for router, prefix in routers:
        for route in router.routes:
            key = (prefix + route.path, tuple(sorted(getattr(route, "methods", ()) or ())))
            if key in seen:
                raise ValueError("duplicate application route")
            seen.add(key)
        app.include_router(router, prefix=prefix)
    return app
