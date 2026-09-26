from fastapi import FastAPI
from api.movements import router

app = FastAPI()
app.include_router(router)


@app.get("/")
async def root():
    return {"message": "Hello, world!"}
