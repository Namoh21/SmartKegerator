from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from data.models import Beer
from web.server import get_db, templates, ctx

router = APIRouter(prefix="/beers")


@router.get("/", response_class=HTMLResponse)
async def beer_list(request: Request):
    db    = get_db()
    beers = db.get_all_beers()

    # Attach keg count per beer
    kegs = db.get_all_kegs()
    keg_counts = {}
    for keg in kegs:
        keg_counts[keg.beer_id] = keg_counts.get(keg.beer_id, 0) + 1

    return templates.TemplateResponse(
        "beers.html",
        ctx(request, beers=beers, keg_counts=keg_counts),
    )


@router.post("/add", response_class=RedirectResponse)
async def beer_add(
    request: Request,
    name:     str   = Form(...),
    company:  str   = Form(""),
    location: str   = Form(""),
    style:    str   = Form(""),
    abv:      float = Form(0.0),
    ibu:      int   = Form(0),
):
    db   = get_db()
    beer = Beer(id=None, name=name.strip(), company=company.strip(),
                location=location.strip(), style=style.strip(), abv=abv, ibu=ibu)
    db.save_beer(beer)
    return RedirectResponse("/beers/", status_code=303)


@router.post("/{beer_id}/edit", response_class=RedirectResponse)
async def beer_edit(
    beer_id:  int,
    name:     str   = Form(...),
    company:  str   = Form(""),
    location: str   = Form(""),
    style:    str   = Form(""),
    abv:      float = Form(0.0),
    ibu:      int   = Form(0),
):
    db   = get_db()
    beer = db.get_beer(beer_id)
    if beer:
        beer.name     = name.strip()
        beer.company  = company.strip()
        beer.location = location.strip()
        beer.style    = style.strip()
        beer.abv      = abv
        beer.ibu      = ibu
        db.save_beer(beer)
    return RedirectResponse("/beers/", status_code=303)


@router.post("/{beer_id}/delete", response_class=RedirectResponse)
async def beer_delete(beer_id: int):
    db = get_db()
    db.delete_beer(beer_id)
    return RedirectResponse("/beers/", status_code=303)
