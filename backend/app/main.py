from fastapi import Depends, FastAPI

from .auth import CurrentUser, get_optional_user

app = FastAPI(title="AGISAJA Stock")


@app.get("/api/me")
def me(user: CurrentUser | None = Depends(get_optional_user)) -> dict:
    return {"user": user}
