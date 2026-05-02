from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from data.models import Beer
from web.api_auth import require_admin
from web.server import get_db

router = APIRouter()


class BeerResponse(BaseModel):
    id:          int
    name:        str
    company:     str
    location:    str
    style:       str
    abv:         float
    ibu:         int
    description: str
    catalog_id:  Optional[str]
    label_url:   str


class BeerRequest(BaseModel):
    name:        str
    company:     str           = ""
    location:    str           = ""
    style:       str           = ""
    abv:         float         = 0.0
    ibu:         int           = 0
    description: str           = ""
    catalog_id:  Optional[str] = None
    label_url:   str           = ""


def _out(beer: Beer) -> BeerResponse:
    return BeerResponse(
        id=beer.id, name=beer.name, company=beer.company,
        location=beer.location, style=beer.style, abv=beer.abv,
        ibu=beer.ibu, description=beer.description,
        catalog_id=beer.catalog_id,
        label_url=beer.label_url,
    )


@router.get("/beers", response_model=list[BeerResponse], dependencies=[Depends(require_admin)])
async def list_beers():
    return [_out(b) for b in get_db().get_all_beers()]


@router.get("/beers/{beer_id}", response_model=BeerResponse, dependencies=[Depends(require_admin)])
async def get_beer(beer_id: int):
    beer = get_db().get_beer(beer_id)
    if not beer:
        raise HTTPException(404, "Beer not found")
    return _out(beer)


@router.post("/beers", response_model=BeerResponse, dependencies=[Depends(require_admin)])
async def add_beer(body: BeerRequest):
    db   = get_db()
    beer = Beer(
        id=None, name=body.name.strip(), company=body.company.strip(),
        location=body.location.strip(), style=body.style.strip(),
        abv=body.abv, ibu=body.ibu, description=body.description.strip(),
        catalog_id=body.catalog_id,
        label_url=body.label_url.strip(),
    )
    db.save_beer(beer)
    return _out(beer)


@router.put("/beers/{beer_id}", response_model=BeerResponse, dependencies=[Depends(require_admin)])
async def update_beer(beer_id: int, body: BeerRequest):
    db   = get_db()
    beer = db.get_beer(beer_id)
    if not beer:
        raise HTTPException(404, "Beer not found")
    beer.name           = body.name.strip()
    beer.company        = body.company.strip()
    beer.location       = body.location.strip()
    beer.style          = body.style.strip()
    beer.abv            = body.abv
    beer.ibu            = body.ibu
    beer.description    = body.description.strip()
    beer.catalog_id  = body.catalog_id
    beer.label_url   = body.label_url.strip()
    db.save_beer(beer)
    return _out(beer)


@router.delete("/beers/{beer_id}", dependencies=[Depends(require_admin)])
async def delete_beer(beer_id: int):
    db = get_db()
    if not db.get_beer(beer_id):
        raise HTTPException(404, "Beer not found")
    db.delete_beer(beer_id)
    return {"ok": True}
